#!/bin/bash

set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
START=$1
END=$2

INPUT="$SCRIPT_DIR/prompts/auditing.txt"
LOG="$SCRIPT_DIR/logs/auditing.log"

mkdir -p "$SCRIPT_DIR/logs"

count=0

while IFS= read -r prompt; do
    count=$((count + 1))

    [[ $count -lt $START ]] && continue
    [[ $count -gt $END ]] && break

    echo "[$count] starting at $(date): $prompt" | tee -a "$LOG"

    codex exec "Use the auditing skill for this task. If the xbrl-auditing MCP server is available, use its tools rather than writing ad hoc parsing scripts.

$prompt" \
        --model gpt-5.3-codex \
        --skip-git-repo-check \
        -c 'mcp_servers.xbrl-auditing.command="python"' \
        -c 'mcp_servers.xbrl-auditing.args=["mcp/xbrl_auditing/server.py"]' \
        -c "mcp_servers.xbrl-auditing.cwd=\"$SCRIPT_DIR\"" \
        -c 'mcp_servers.xbrl-auditing.startup_timeout_sec=20' \
        -c 'mcp_servers.xbrl-auditing.tool_timeout_sec=120' \
        -c 'mcp_servers.xbrl-auditing.enabled=true' \
        -c 'mcp_servers.xbrl-auditing.required=true' \
        2>&1 | tee -a "$LOG"

    status=${PIPESTATUS[0]}
    if [[ $status -eq 0 ]]; then
        echo "[$count] completed at $(date)" | tee -a "$LOG"
    else
        echo "[$count] failed with exit code $status at $(date)" | tee -a "$LOG"
        exit "$status"
    fi

done < "$INPUT"
