#!/bin/bash
# usage: ./run_claude_single.sh 1 2

set -o pipefail

INPUT="prompts/auditing.txt"
START=$1
END=$2
count=0
LOG="logs/auditing.log"

awk 'BEGIN{RS="---"} NR>1' "$INPUT" | while IFS= read -r prompt; do
    count=$((count + 1))

    [[ $count -lt $START ]] && continue
    [[ $count -gt $END ]] && break

    echo "[$count] starting" | tee -a "$LOG"

    claude \
        --dangerously-skip-permissions \
        --no-session-persistence \
        --model claude-sonnet-4-6 \
        "$prompt" 2>&1 | tee -a "$LOG"

    status=${PIPESTATUS[0]}
    if [[ $status -eq 0 ]]; then
        echo "[$count] completed" | tee -a "$LOG"
    else
        echo "[$count] failed with exit code $status" | tee -a "$LOG"
        exit "$status"
    fi
done
