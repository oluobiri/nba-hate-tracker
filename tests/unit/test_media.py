"""
Tests for pipeline/media.py: first-party headshots and logos.

Nothing here touches the network: the CDN is a requests.get stand-in,
and every file lands in tmp_path.
"""

import io
from pathlib import Path
from unittest.mock import Mock, call, patch

import pytest
import requests
from PIL import Image

from pipeline.media import (
    PNG_MAGIC,
    TMP_SUFFIX,
    MediaError,
    Variant,
    build_plan,
    fetch_asset,
    fetch_originals,
    generate_variant,
    generate_variants,
    headshot_asset,
    headshot_name,
    headshot_source_url,
    is_png,
    is_svg,
    logo_asset,
    logo_name,
    logo_source_url,
    sync_media,
    variant_height,
    variant_name,
    verify_config_urls,
)
from utils.constants import NBA_CDN_HEADSHOT_ACCEPT, NBA_CDN_USER_AGENT

PLAYER = 203500
TEAM = 1610612737
WIDTHS = (18, 42)

PNG = PNG_MAGIC + b"not really pixels"
SVG = b'<?xml version="1.0" encoding="utf-8"?>\r\n<!-- Generator: x -->\r\n<svg xmlns="http://www.w3.org/2000/svg"></svg>'
HTML = b"<!DOCTYPE html><html><body>Access denied</body></html>"


def _player(player_id: int | None = PLAYER, url: str | None = None) -> dict:
    """A players.yaml entry as load_player_metadata() returns it."""
    if url is None and player_id is not None:
        url = headshot_source_url(player_id)
    return {
        "team": "X",
        "conference": "East",
        "player_id": player_id,
        "headshot_url": url,
    }


def _team(team_id: int = TEAM, url: str | None = None) -> dict:
    """A teams.yaml entry as load_team_config() returns it."""
    return {
        "abbreviation": "X",
        "team_id": team_id,
        "logo_url": url or logo_source_url(team_id),
    }


def _response(body: bytes, status: int = 200) -> Mock:
    """One CDN response."""
    response = Mock()
    response.status_code = status
    response.content = body
    if status >= 400:
        response.raise_for_status.side_effect = requests.HTTPError(f"HTTP {status}")
    return response


def _http_get(body: bytes, status: int = 200) -> Mock:
    """A requests.get stand-in serving one body for every URL."""
    return Mock(return_value=_response(body, status))


def _png_image(mode: str = "P") -> bytes:
    """A 104x76 cutout: opaque square on a transparent field, like the CDN's."""
    image = Image.new("RGBA", (104, 76), (0, 0, 0, 0))
    for x in range(20, 80):
        for y in range(10, 70):
            image.putpixel((x, y), (200, 30, 30, 255))
    if mode == "P":
        image = image.quantize(colors=4)
    out = io.BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


@pytest.fixture(scope="module")
def png_palette() -> bytes:
    """The CDN's shape: a palette PNG with a transparency entry."""
    return _png_image("P")


@pytest.fixture(scope="module")
def png_rgba() -> bytes:
    """A straight RGBA PNG."""
    return _png_image("RGBA")


def _variant(media_dir: Path, width: int, player_id: int = PLAYER) -> Variant:
    """A variant record for the test player."""
    return Variant(
        player_id=player_id,
        width=width,
        source=media_dir / headshot_name(player_id),
        name=variant_name(player_id, width),
        path=media_dir / variant_name(player_id, width),
    )


def _routing_http_get(png: bytes) -> Mock:
    """A requests.get stand-in serving the PNG for headshots, SVG for logos."""
    return Mock(
        side_effect=lambda url, **_: _response(png if url.endswith(".png") else SVG)
    )


@pytest.fixture
def media_dir(tmp_path) -> Path:
    """An empty media root."""
    return tmp_path / "media"


@pytest.fixture
def sleep():
    """time.sleep patched out; the fetcher's delays and backoff must never run."""
    with patch("pipeline.media.time.sleep") as mock_sleep:
        yield mock_sleep


class TestSourceUrls:
    """Source URLs derive from ids, never from config values."""

    def test_headshot_url_from_player_id(self):
        """The 1040x760 headshot pattern keyed by player_id."""
        url = headshot_source_url(PLAYER)
        assert url == "https://cdn.nba.com/headshots/nba/latest/1040x760/203500.png"

    def test_logo_url_from_team_id(self):
        """The primary SVG logo pattern keyed by team_id."""
        url = logo_source_url(TEAM)
        assert url == "https://cdn.nba.com/logos/nba/1610612737/primary/L/logo.svg"


class TestNames:
    """The naming convention the site builds its srcset from."""

    @pytest.mark.parametrize(
        "name,expected",
        [
            (headshot_name(PLAYER), "headshots/203500.png"),
            (variant_name(PLAYER, 180), "headshots/203500-180.webp"),
            (logo_name(TEAM), "logos/1610612737.svg"),
        ],
    )
    def test_naming_convention(self, name, expected):
        """Original, variant, and logo names are relative to the media root."""
        assert name == expected

    def test_asset_path_is_the_name_under_the_media_dir(self, media_dir):
        """The local path is the media root plus the name, so name is the key."""
        asset = headshot_asset(PLAYER, media_dir)
        assert asset.path == media_dir / asset.name
        assert asset.name == headshot_name(PLAYER)

    def test_headshot_pins_accept_and_logo_does_not(self, media_dir):
        """Only the PNG has a negotiated sibling worth pinning against."""
        assert headshot_asset(PLAYER, media_dir).accept == NBA_CDN_HEADSHOT_ACCEPT
        assert logo_asset(TEAM, media_dir).accept is None


class TestVerifyConfigUrls:
    """Config URLs must equal the derived form so the fetch can trust ids."""

    def test_matching_config_passes(self):
        """Every entry derived from its id: nothing to report."""
        verify_config_urls({"A": _player()}, {"T": _team()})

    def test_headshot_mismatch_names_the_player(self):
        """A hand-edited headshot_url is named with both URLs."""
        bad = "https://cdn.nba.com/headshots/nba/latest/260x190/203500.png"
        with pytest.raises(MediaError, match="A") as exc:
            verify_config_urls({"A": _player(url=bad)}, {"T": _team()})
        assert bad in str(exc.value)
        assert headshot_source_url(PLAYER) in str(exc.value)

    def test_missing_player_id_is_a_mismatch(self):
        """A player without an id has no derivable URL: loud, not a TypeError."""
        with pytest.raises(MediaError, match="A"):
            verify_config_urls({"A": _player(player_id=None)}, {})

    def test_logo_mismatch_names_the_team(self):
        """A hand-edited logo_url is named."""
        with pytest.raises(MediaError, match="T"):
            verify_config_urls({}, {"T": _team(url="https://example.com/x.svg")})

    def test_reports_every_mismatch_at_once(self):
        """One error lists every bad entry, not just the first."""
        players = {"A": _player(url="x"), "B": _player(player_id=1, url="y")}
        with pytest.raises(MediaError, match="2 config URLs") as exc:
            verify_config_urls(players, {})
        assert "A" in str(exc.value) and "B" in str(exc.value)

    def test_injected_builders_are_honoured(self):
        """The expected form is pluggable, for the first-party URL switch."""
        players = {
            "A": _player(url="https://courtsentiment.com/media/headshots/203500.png")
        }
        verify_config_urls(
            players,
            {},
            headshot_url=lambda pid: f"https://courtsentiment.com/media/headshots/{pid}.png",
        )


class TestSniff:
    """Blocked responses can be HTML with a 200, so bytes are checked."""

    @pytest.mark.parametrize(
        "body,expected",
        [
            (PNG, True),
            (HTML, False),
            (b"RIFF\x00\x00\x00\x00WEBPVP8 ", False),
            (b"", False),
        ],
    )
    def test_png_magic(self, body, expected):
        """Only the PNG signature passes."""
        assert is_png(body) is expected

    def test_svg_with_xml_prolog_and_comment(self):
        """The CDN's logos open with a prolog and a generator comment."""
        assert is_svg(SVG)

    def test_svg_without_prolog(self):
        """A bare svg root passes."""
        assert is_svg(b'<svg xmlns="http://www.w3.org/2000/svg"/>')

    def test_leading_whitespace_tolerated(self):
        """Whitespace before the prolog is fine."""
        assert is_svg(b"\n  " + SVG)

    def test_html_is_not_svg(self):
        """A block page's DOCTYPE and html root fail."""
        assert not is_svg(HTML)

    def test_png_is_not_svg(self):
        """A PNG offered as a logo fails."""
        assert not is_svg(PNG)


class TestBuildPlan:
    """What a run will do, decided from disk state alone."""

    def test_empty_dir_fetches_everything(self, media_dir):
        """No files: every original fetches and every variant generates."""
        plan = build_plan([PLAYER, 2], [TEAM], media_dir, widths=WIDTHS)
        assert len(plan.fetch) == 3
        assert plan.present == ()
        assert len(plan.generate) == 2 * len(WIDTHS)
        assert plan.up_to_date == ()

    def test_present_original_is_skipped_but_its_variants_generate(self, media_dir):
        """Resume: an original on disk is not refetched; missing variants still generate."""
        (media_dir / "headshots").mkdir(parents=True)
        (media_dir / headshot_name(PLAYER)).write_bytes(PNG)
        plan = build_plan([PLAYER], [], media_dir, widths=WIDTHS)
        assert plan.fetch == ()
        assert [a.name for a in plan.present] == [headshot_name(PLAYER)]
        assert [v.width for v in plan.generate] == list(WIDTHS)

    def test_only_the_missing_width_generates(self, media_dir):
        """A variant on disk is up to date; its missing sibling generates."""
        (media_dir / "headshots").mkdir(parents=True)
        (media_dir / variant_name(PLAYER, 18)).write_bytes(b"webp")
        plan = build_plan([PLAYER], [], media_dir, widths=WIDTHS)
        assert [v.width for v in plan.generate] == [42]
        assert [v.width for v in plan.up_to_date] == [18]

    def test_force_refetches_and_regenerates_everything(self, media_dir):
        """--force ignores disk state."""
        (media_dir / "headshots").mkdir(parents=True)
        (media_dir / headshot_name(PLAYER)).write_bytes(PNG)
        (media_dir / variant_name(PLAYER, 18)).write_bytes(b"webp")
        plan = build_plan([PLAYER], [], media_dir, widths=WIDTHS, force=True)
        assert len(plan.fetch) == 1 and plan.present == ()
        assert len(plan.generate) == 2 and plan.up_to_date == ()

    def test_order_is_headshots_then_logos_by_id(self, media_dir):
        """Deterministic order for logs and resume."""
        plan = build_plan([9, 1], [5, 3], media_dir, widths=WIDTHS)
        assert [a.entity_id for a in plan.fetch] == [1, 9, 3, 5]
        assert [a.kind for a in plan.fetch] == ["headshot", "headshot", "logo", "logo"]

    def test_variant_source_is_the_original_path(self, media_dir):
        """Each variant knows the PNG it derives from."""
        plan = build_plan([PLAYER], [], media_dir, widths=WIDTHS)
        assert {v.source for v in plan.generate} == {media_dir / headshot_name(PLAYER)}
        assert plan.generate[0].path == media_dir / variant_name(PLAYER, 18)

    def test_describe_counts_each_action(self, media_dir):
        """The dry-run block names the counts and every action."""
        (media_dir / "logos").mkdir(parents=True)
        (media_dir / logo_name(TEAM)).write_bytes(SVG)
        plan = build_plan([PLAYER], [TEAM], media_dir, widths=WIDTHS)
        text = plan.describe()
        assert "1 fetch, 1 present, 2 generate, 0 up to date" in text
        assert f"fetch     {headshot_name(PLAYER)}" in text
        assert f"present   {logo_name(TEAM)}" in text
        assert f"generate  {variant_name(PLAYER, 42)}" in text


class TestFetchAsset:
    """One original: headers, retries, validation, atomic write."""

    def test_writes_the_validated_bytes(self, media_dir, sleep):
        """The file holds exactly the body; no temp file survives."""
        asset = headshot_asset(PLAYER, media_dir)
        fetch_asset(asset, http_get=_http_get(PNG))
        assert asset.path.read_bytes() == PNG
        assert not list(media_dir.rglob(f"*{TMP_SUFFIX}"))
        sleep.assert_not_called()

    def test_sends_plain_user_agent_and_pinned_accept(self, media_dir, sleep):
        """The UA carries no bot signature; the headshot pins image/png."""
        http_get = _http_get(PNG)
        fetch_asset(headshot_asset(PLAYER, media_dir), http_get=http_get)
        _, kwargs = http_get.call_args
        headers = kwargs["headers"]
        assert headers["User-Agent"] == NBA_CDN_USER_AGENT
        assert "fetch" not in headers["User-Agent"]
        assert "http" not in headers["User-Agent"]
        assert headers["Accept"] == NBA_CDN_HEADSHOT_ACCEPT
        assert kwargs["timeout"] > 0

    def test_logo_sends_no_accept(self, media_dir, sleep):
        """SVG has no negotiated sibling, so requests' default Accept stands."""
        http_get = _http_get(SVG)
        fetch_asset(logo_asset(TEAM, media_dir), http_get=http_get)
        assert "Accept" not in http_get.call_args.kwargs["headers"]

    def test_http_error_is_not_retried(self, media_dir, sleep):
        """A 404 is a real answer: raised once, nothing written."""
        asset = headshot_asset(PLAYER, media_dir)
        http_get = _http_get(b"", status=404)
        with pytest.raises(requests.HTTPError):
            fetch_asset(asset, http_get=http_get)
        assert http_get.call_count == 1
        sleep.assert_not_called()
        assert not asset.path.exists()

    def test_wrong_bytes_are_a_media_error(self, media_dir, sleep):
        """A 200 that is not the image is a miss, and nothing is written."""
        asset = headshot_asset(PLAYER, media_dir)
        with pytest.raises(MediaError, match="PNG"):
            fetch_asset(asset, http_get=_http_get(HTML))
        assert not asset.path.exists()
        assert not list(media_dir.rglob("*"))

    def test_transient_errors_retry_with_backoff(self, media_dir, sleep):
        """Connection errors and timeouts back off 2s, 4s, then succeed."""
        asset = headshot_asset(PLAYER, media_dir)
        http_get = Mock(
            side_effect=[
                requests.ConnectionError("reset"),
                requests.Timeout("hang"),
                _response(PNG),
            ]
        )
        fetch_asset(asset, http_get=http_get, max_attempts=4, retry_backoff=2.0)
        assert http_get.call_count == 3
        assert sleep.call_args_list == [call(2.0), call(4.0)]
        assert asset.path.read_bytes() == PNG

    def test_exhaustion_raises_the_last_error(self, media_dir, sleep):
        """After max_attempts the last transient error propagates."""
        asset = headshot_asset(PLAYER, media_dir)
        http_get = Mock(side_effect=requests.Timeout("hang"))
        with pytest.raises(requests.Timeout):
            fetch_asset(asset, http_get=http_get, max_attempts=4, retry_backoff=2.0)
        assert http_get.call_count == 4
        assert sleep.call_args_list == [call(2.0), call(4.0), call(8.0)]
        assert not asset.path.exists()


class TestFetchOriginals:
    """Phase one over a plan: misses are collected, the run continues."""

    def test_collects_misses_and_keeps_going(self, media_dir, sleep):
        """A 404 becomes a Miss naming the asset; the next asset still lands."""
        assets = [headshot_asset(PLAYER, media_dir), logo_asset(TEAM, media_dir)]
        http_get = Mock(side_effect=[_response(b"", 404), _response(SVG)])
        misses = fetch_originals(assets, http_get=http_get, delay=0.5)
        assert [m.name for m in misses] == [headshot_name(PLAYER)]
        assert "HTTP 404" in misses[0].reason
        assert assets[1].path.read_bytes() == SVG

    def test_bad_bytes_are_a_miss(self, media_dir, sleep):
        """A validation failure is reported like any other miss."""
        misses = fetch_originals(
            [headshot_asset(PLAYER, media_dir)], http_get=_http_get(HTML), delay=0.5
        )
        assert len(misses) == 1 and "PNG" in misses[0].reason

    def test_sleeps_the_delay_after_each_request(self, media_dir, sleep):
        """Polite spacing between every request, misses included."""
        assets = [headshot_asset(PLAYER, media_dir), logo_asset(TEAM, media_dir)]
        http_get = Mock(side_effect=[_response(PNG), _response(SVG)])
        fetch_originals(assets, http_get=http_get, delay=0.5)
        assert sleep.call_args_list == [call(0.5), call(0.5)]

    def test_no_misses_on_success(self, media_dir, sleep):
        """A clean run reports nothing."""
        assert (
            fetch_originals([logo_asset(TEAM, media_dir)], http_get=_http_get(SVG))
            == []
        )


class TestGenerateVariant:
    """One WebP from one PNG: geometry, alpha, and the no-upscale rule."""

    def test_writes_webp_at_target_width_and_rounded_height(
        self, media_dir, png_palette
    ):
        """104x76 at width 42 gives 42x31 (76 * 42 / 104 = 30.7)."""
        variant = _variant(media_dir, 42)
        media_dir.joinpath("headshots").mkdir(parents=True)
        variant.source.write_bytes(png_palette)
        generate_variant(variant)
        with Image.open(variant.path) as out:
            assert out.format == "WEBP"
            assert out.size == (42, 31)
        assert not list(media_dir.rglob(f"*{TMP_SUFFIX}"))

    def test_alpha_is_kept_from_a_palette_source(self, media_dir, png_palette):
        """The transparent field stays transparent; the cutout stays opaque."""
        variant = _variant(media_dir, 42)
        media_dir.joinpath("headshots").mkdir(parents=True)
        variant.source.write_bytes(png_palette)
        generate_variant(variant)
        with Image.open(variant.path) as out:
            out = out.convert("RGBA")
            assert out.getpixel((0, 0))[3] == 0
            assert out.getpixel((21, 15))[3] == 255

    def test_rgba_source_also_works(self, media_dir, png_rgba):
        """A straight RGBA PNG converts the same way."""
        variant = _variant(media_dir, 18)
        media_dir.joinpath("headshots").mkdir(parents=True)
        variant.source.write_bytes(png_rgba)
        generate_variant(variant)
        with Image.open(variant.path) as out:
            assert out.size == (18, 13)
            assert out.convert("RGBA").getpixel((0, 0))[3] == 0

    def test_source_narrower_than_target_raises(self, media_dir, png_palette):
        """Never upscale: a 104px source cannot make an 840px variant."""
        variant = _variant(media_dir, 840)
        media_dir.joinpath("headshots").mkdir(parents=True)
        variant.source.write_bytes(png_palette)
        with pytest.raises(MediaError, match="104") as exc:
            generate_variant(variant)
        assert "840" in str(exc.value)
        assert not variant.path.exists()

    @pytest.mark.parametrize("width,expected", [(180, 132), (420, 307), (840, 614)])
    def test_real_source_geometry(self, width, expected):
        """The 1040x760 source at each planned width."""
        assert variant_height(1040, 760, width) == expected


class TestGenerateVariants:
    """Phase two over a plan: originals that missed are skipped, not reported twice."""

    def test_skips_variants_whose_original_missed(self, media_dir, png_palette):
        """A missed original's variants are neither attempted nor a Miss."""
        missing = _variant(media_dir, 18, player_id=1)
        present = _variant(media_dir, 18)
        media_dir.joinpath("headshots").mkdir(parents=True)
        present.source.write_bytes(png_palette)
        misses = generate_variants([missing, present], missing_sources={missing.source})
        assert misses == []
        assert present.path.exists()
        assert not missing.path.exists()

    def test_generation_error_is_a_miss_and_siblings_continue(
        self, media_dir, png_palette
    ):
        """A narrow source is a Miss; the width that fits still generates."""
        too_wide = _variant(media_dir, 840)
        fits = _variant(media_dir, 18)
        media_dir.joinpath("headshots").mkdir(parents=True)
        fits.source.write_bytes(png_palette)
        misses = generate_variants([too_wide, fits], missing_sources=set())
        assert [m.name for m in misses] == [too_wide.name]
        assert fits.path.exists()


class TestSyncMedia:
    """Both phases end to end, resumable, with misses reported once."""

    def test_two_phases_end_to_end(self, media_dir, png_palette, sleep):
        """Originals and every variant land; the report is clean."""
        report = sync_media(
            [PLAYER],
            [TEAM],
            media_dir,
            widths=WIDTHS,
            http_get=_routing_http_get(png_palette),
        )
        assert report.ok
        assert (media_dir / headshot_name(PLAYER)).read_bytes() == png_palette
        assert (media_dir / logo_name(TEAM)).read_bytes() == SVG
        for width in WIDTHS:
            assert (media_dir / variant_name(PLAYER, width)).exists()
        assert report.fetched == [headshot_name(PLAYER), logo_name(TEAM)]
        assert report.generated == [variant_name(PLAYER, w) for w in WIDTHS]

    def test_rerun_touches_nothing(self, media_dir, png_palette, sleep):
        """A second run makes no request and writes nothing."""
        sync_media(
            [PLAYER],
            [TEAM],
            media_dir,
            widths=WIDTHS,
            http_get=_routing_http_get(png_palette),
        )
        refusing = Mock(side_effect=AssertionError("network on a resumed run"))
        report = sync_media(
            [PLAYER], [TEAM], media_dir, widths=WIDTHS, http_get=refusing
        )
        assert report.ok
        assert report.fetched == [] and report.generated == []

    def test_missing_variant_regenerates_without_a_refetch(
        self, media_dir, png_palette, sleep
    ):
        """Delete one WebP: only that file is regenerated, no request made."""
        sync_media(
            [PLAYER],
            [],
            media_dir,
            widths=WIDTHS,
            http_get=_routing_http_get(png_palette),
        )
        (media_dir / variant_name(PLAYER, 42)).unlink()
        refusing = Mock(side_effect=AssertionError("network on a resumed run"))
        report = sync_media([PLAYER], [], media_dir, widths=WIDTHS, http_get=refusing)
        assert report.generated == [variant_name(PLAYER, 42)]
        assert (media_dir / variant_name(PLAYER, 42)).exists()

    def test_missed_headshot_reports_once(self, media_dir, sleep):
        """A 404 headshot is one Miss; its variants are not counted again."""
        report = sync_media(
            [PLAYER], [], media_dir, widths=WIDTHS, http_get=_http_get(b"", status=404)
        )
        assert not report.ok
        assert [m.name for m in report.misses] == [headshot_name(PLAYER)]
        assert not list(media_dir.rglob("*.webp"))

    def test_force_refetches_everything(self, media_dir, png_palette, sleep):
        """--force: every original is requested again even though present."""
        sync_media(
            [PLAYER],
            [TEAM],
            media_dir,
            widths=WIDTHS,
            http_get=_routing_http_get(png_palette),
        )
        http_get = _routing_http_get(png_palette)
        report = sync_media(
            [PLAYER], [TEAM], media_dir, widths=WIDTHS, http_get=http_get, force=True
        )
        assert http_get.call_count == 2
        assert len(report.generated) == len(WIDTHS)
