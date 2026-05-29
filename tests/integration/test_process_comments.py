"""Integration tests for the process_comments script."""

import json

from scripts.process_comments import process_file


class TestProcessComments:
    """End-to-end tests for the comment processing pipeline."""

    def _make_comment(self, **overrides) -> dict:
        """Build a raw comment dict with sensible defaults."""
        base = {
            "id": "test1",
            "body": "LeBron is the GOAT",
            "author": "user1",
            "author_flair_text": "Lakers",
            "author_flair_css_class": "lakers",
            "subreddit": "nba",
            "created_utc": 1709251200,
            "score": 42,
            "controversiality": 0,
            "parent_id": "t1_xyz789",
            "link_id": "t3_post123",
        }
        base.update(overrides)
        return base

    def test_valid_comment_with_player_mention_accepted(self, tmp_path):
        """Comment with valid body and player mention passes through."""
        input_file = tmp_path / "input.jsonl"
        output_file = tmp_path / "output.jsonl"

        comment = self._make_comment()
        input_file.write_text(json.dumps(comment) + "\n")

        stats, _ = process_file(input_file, output_file, skip_line_count=True)

        results = [json.loads(line) for line in output_file.read_text().strip().split("\n")]
        assert len(results) == 1
        assert "LeBron James" in results[0]["mentioned_players"]
        assert stats.total_comments == 1
        assert stats.accepted_comments == 1

    def test_deleted_body_rejected(self, tmp_path):
        """Comment with [deleted] body is rejected."""
        input_file = tmp_path / "input.jsonl"
        output_file = tmp_path / "output.jsonl"

        comment = self._make_comment(id="del1", body="[deleted]")
        input_file.write_text(json.dumps(comment) + "\n")

        stats, _ = process_file(input_file, output_file, skip_line_count=True)

        assert stats.rejected_body == 1
        assert stats.accepted_comments == 0
        assert output_file.read_text() == ""

    def test_no_player_mention_rejected(self, tmp_path):
        """Comment with valid body but no player mention is rejected."""
        input_file = tmp_path / "input.jsonl"
        output_file = tmp_path / "output.jsonl"

        comment = self._make_comment(id="nopl1", body="Great game last night")
        input_file.write_text(json.dumps(comment) + "\n")

        stats, _ = process_file(input_file, output_file, skip_line_count=True)

        assert stats.rejected_no_player_mention == 1
        assert stats.accepted_comments == 0

    def test_malformed_json_rejected(self, tmp_path):
        """Malformed JSON lines are counted and skipped."""
        input_file = tmp_path / "input.jsonl"
        output_file = tmp_path / "output.jsonl"

        input_file.write_text("this is not json\n")

        stats, _ = process_file(input_file, output_file, skip_line_count=True)

        assert stats.rejected_malformed == 1
        assert stats.accepted_comments == 0

    def test_mixed_input_produces_correct_stats(self, tmp_path):
        """Mixed input correctly categorizes each line."""
        input_file = tmp_path / "input.jsonl"
        output_file = tmp_path / "output.jsonl"

        lines = [
            json.dumps(self._make_comment(id="1", body="LeBron is great")),
            json.dumps(self._make_comment(id="2", body="[deleted]")),
            "not json at all",
            json.dumps(self._make_comment(id="3", body="What a game!")),
            json.dumps(self._make_comment(id="4", body="KD is unstoppable")),
        ]
        input_file.write_text("\n".join(lines) + "\n")

        stats, _ = process_file(input_file, output_file, skip_line_count=True)

        assert stats.total_comments == 5
        assert stats.accepted_comments == 2
        assert stats.rejected_body == 1
        assert stats.rejected_malformed == 1
        assert stats.rejected_no_player_mention == 1
        assert stats.rejected_comments == 3

        output_lines = output_file.read_text().strip().split("\n")
        assert len(output_lines) == 2

    def test_limit_stops_early(self, tmp_path):
        """--limit flag stops processing after N lines."""
        input_file = tmp_path / "input.jsonl"
        output_file = tmp_path / "output.jsonl"

        lines = [
            json.dumps(self._make_comment(id=str(i), body="LeBron is great"))
            for i in range(10)
        ]
        input_file.write_text("\n".join(lines) + "\n")

        stats, _ = process_file(input_file, output_file, limit=3, skip_line_count=True)

        assert stats.total_comments == 3
