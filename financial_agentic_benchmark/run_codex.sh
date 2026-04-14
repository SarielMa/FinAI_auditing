#!/bin/bash

START=$1
END=$2

INPUT="prompts/auditing.txt"
LOG="logs/auditing.log"

mkdir -p logs

count=0

while IFS= read -r prompt; do
    count=$((count + 1))

    [[ $count -lt $START ]] && continue
    [[ $count -gt $END ]] && break

    echo "[$count] starting: $prompt" | tee -a "$LOG"

    codex exec "$prompt" \
        --model gpt-5 \
        --skip-git-repo-check \
        2>&1 | tee -a "$LOG"

    echo "[$count] completed" | tee -a "$LOG"

done < "$INPUT"

