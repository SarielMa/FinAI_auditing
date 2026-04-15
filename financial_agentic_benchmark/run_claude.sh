#!/bin/bash
# usage: ./run.sh 1 2

set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INPUT="$SCRIPT_DIR/prompts/auditing.txt"
START=$1
END=$2
count=0
LOG="$SCRIPT_DIR/logs/auditing.log"

# > "$LOG"  # clear the log

while IFS= read -r prompt; do
    count=$((count + 1))
    [[ $count -lt $START ]] && continue
    [[ $count -gt $END ]] && break
    echo "[$count] starting at $(date): $prompt" | tee -a "$LOG"
    mcp_debug_log="$(mktemp "$SCRIPT_DIR/logs/.claude_mcp_${count}_XXXXXX")"
    XBRL_AUDITING_MCP_LOG="$mcp_debug_log" claude \
        --dangerously-skip-permissions \
        --print \
        --no-session-persistence \
        --model claude-sonnet-4-6 \
        --append-system-prompt "The xbrl-auditing MCP server writes tool-call traces to \$XBRL_AUDITING_MCP_LOG. Use the MCP tools normally." \
        --mcp-config "$SCRIPT_DIR/mcp/mcp_config.json" \
        -- "$prompt" 2>&1 | tee -a "$LOG"
    status=${PIPESTATUS[0]}
    if [[ $status -eq 0 ]]; then
        if [[ -f "$mcp_debug_log" ]]; then
            tee -a "$LOG" < "$mcp_debug_log"
        fi
        rm -f "$mcp_debug_log"
        echo "[$count] completed at $(date)" | tee -a "$LOG"
    else
        if [[ -f "$mcp_debug_log" ]]; then
            tee -a "$LOG" < "$mcp_debug_log"
        fi
        rm -f "$mcp_debug_log"
        echo "[$count] failed with exit code $status at $(date)" | tee -a "$LOG"
        exit "$status"
    fi
done < "$INPUT"
