#!/bin/bash
# usage: ./run.sh 1 10

INPUT="prompts/auditing.txt"
START=$1
END=$2
count=0
LOG="logs/auditing.log"

# > "$LOG"  # clear the log

while IFS= read -r prompt; do
    count=$((count + 1))
    [[ $count -lt $START ]] && continue
    [[ $count -gt $END ]] && break
    echo "[$count] starting: $prompt" | tee -a "$LOG"
    claude \
        --dangerously-skip-permissions \
        --no-session-persistence \
        --model claude-sonnet-4-6 \
        "$prompt" | tee -a "$LOG"
    echo "[$count] completed" | tee -a "$LOG"
done < "$INPUT"
