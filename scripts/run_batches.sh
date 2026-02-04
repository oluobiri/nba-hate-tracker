#!/bin/bash
while true; do
    echo "=== $(date) ==="
    
    uv run python -m scripts.collect_results --no-wait
    
    PROCESSING=$(cat data/batches/state.json | jq '[.batches[] | select(.status != "ended")] | length')
    
    if [ "$PROCESSING" -gt 0 ]; then
        echo "$PROCESSING batch(es) still processing, waiting..."
    else
        uv run python -m scripts.submit_batches --batches 1 || break
    fi
    
    TOTAL=$(cat data/batches/state.json | jq '.batches | length')
    PENDING=$(cat data/batches/state.json | jq '[.batches[] | select(.status != "ended")] | length')
    
    echo "Progress: $TOTAL/20 submitted, $PENDING processing"
    
    if [ "$TOTAL" -eq 20 ] && [ "$PENDING" -eq 0 ]; then
        echo "All batches complete!"
        break
    fi
    
    echo "Sleeping 30 minutes..."
    sleep 1800
done
