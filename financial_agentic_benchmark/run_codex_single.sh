#!/bin/bash

START=$1
END=$2

INPUT="prompts/auditing.txt"
LOG="logs/auditing.log"

mkdir -p logs

count=0

awk 'BEGIN{RS="---"} NR>1' "$INPUT" | while IFS= read -r prompt; do
    count=$((count + 1))

    [[ $count -lt $START ]] && continue
    [[ $count -gt $END ]] && break

    echo "[$count] starting" | tee -a "$LOG"

    codex exec "use auditing skill to solve this task:
$prompt" \
        --model gpt-5.3-codex \
        --skip-git-repo-check \
        2>&1 | tee -a "$LOG"

    echo "[$count] completed" | tee -a "$LOG"

done