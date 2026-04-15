#!/bin/sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
START=$1
END=$2

INPUT="$SCRIPT_DIR/prompts/auditing.txt"
LOG="$SCRIPT_DIR/logs/auditing.log"
TRACE_PATTERN='[xbrl-auditing MCP]'
SERVER_START_PATTERN='[xbrl-auditing MCP] server starting'
REQUIRED_TOOLS='locate_filing extract_xbrl_facts get_calculation_network get_balance_type write_audit_result'

mkdir -p "$SCRIPT_DIR/logs"
mkdir -p "$SCRIPT_DIR/results"

extract_prompt_id() {
    printf '%s\n' "$1" | sed -n 's/.*(id: \([^)]*\)).*/\1/p'
}

extract_output_dir() {
    printf '%s\n' "$1" | sed -n 's/.*please save the output to \([^[:space:]]*\)\..*/\1/p'
}

replace_first_literal() {
    printf '%s\n' "$1" | awk -v old="$2" -v new="$3" '
        {
            pos = index($0, old)
            if (pos == 0) {
                print $0
            } else {
                printf "%s%s%s\n", substr($0, 1, pos - 1), new, substr($0, pos + length(old))
            }
        }
    '
}

count=0

while IFS= read -r prompt || [ -n "$prompt" ]; do
    count=$((count + 1))

    [ "$count" -lt "$START" ] && continue
    [ "$count" -gt "$END" ] && break

    echo "[$count] starting at $(date): $prompt" | tee -a "$LOG"

    prompt_id="$(extract_prompt_id "$prompt")"
    if [ -z "$prompt_id" ]; then
        echo "[$count] failed: could not parse task id from prompt" | tee -a "$LOG"
        exit 1
    fi

    requested_output_dir="$(extract_output_dir "$prompt")"
    if [ -z "$requested_output_dir" ]; then
        echo "[$count] failed: could not parse output directory from prompt" | tee -a "$LOG"
        exit 1
    fi

    tmp_output_dir="$(mktemp -d "$SCRIPT_DIR/results/.codex_tmp_${prompt_id}_XXXXXX")"
    run_prompt="$(replace_first_literal "$prompt" "$requested_output_dir" "$tmp_output_dir")"
    codex_output_log="$(mktemp "$SCRIPT_DIR/logs/.codex_exec_${prompt_id}_XXXXXX")"
    mcp_debug_log="$(mktemp "$SCRIPT_DIR/logs/.codex_mcp_${prompt_id}_XXXXXX")"

    if codex -a never exec "Use the auditing skill for this task. You must execute exactly one auditing request: the single request pasted below. Do not read batch prompt files such as prompts/auditing.txt. Do not process any other mr_* task. Write exactly one JSON result for ${prompt_id} into ${tmp_output_dir}. If you cannot complete only that one task, fail.

The xbrl-auditing MCP server is required for this run. Use the MCP tools locate_filing, extract_xbrl_facts, get_calculation_network, get_balance_type, and write_audit_result. Do not parse XML/XSD/JSONL files directly with shell commands or ad hoc scripts when the MCP server is available. If any required MCP tool is unavailable or fails, stop and fail the task instead of falling back.

$run_prompt" \
        --model gpt-5.3-codex \
        --skip-git-repo-check \
        -c 'mcp_servers.xbrl-auditing.command="bash"' \
        -c 'mcp_servers.xbrl-auditing.args=["mcp/xbrl_auditing/run_server.sh"]' \
        -c "mcp_servers.xbrl-auditing.cwd=\"$SCRIPT_DIR\"" \
        -c "mcp_servers.xbrl-auditing.env={XBRL_AUDITING_MCP_LOG=\"$mcp_debug_log\"}" \
        -c 'mcp_servers.xbrl-auditing.startup_timeout_sec=20' \
        -c 'mcp_servers.xbrl-auditing.tool_timeout_sec=120' \
        -c 'mcp_servers.xbrl-auditing.enabled=true' \
        -c 'mcp_servers.xbrl-auditing.required=true' \
        >"$codex_output_log" 2>&1; then
        status=0
    else
        status=$?
    fi

    tee -a "$LOG" < "$codex_output_log"
    rm -f "$codex_output_log"

    if [ "$status" -eq 0 ]; then
        if [ -f "$mcp_debug_log" ]; then
            tee -a "$LOG" < "$mcp_debug_log"
        fi

        tool_trace_count=0
        if [ -f "$mcp_debug_log" ] && grep -F "$TRACE_PATTERN" "$mcp_debug_log" >/dev/null 2>&1; then
            tool_trace_count="$(grep -F "$TRACE_PATTERN" "$mcp_debug_log" | grep -Fv "$SERVER_START_PATTERN" | wc -l | tr -d ' ')"
        fi
        if [ "$tool_trace_count" -lt 5 ]; then
            echo "[$count] failed: expected at least 5 xbrl-auditing MCP tool calls for ${prompt_id}, found ${tool_trace_count}" | tee -a "$LOG"
            rm -rf "$tmp_output_dir"
            rm -f "$mcp_debug_log"
            exit 1
        fi
        for required_tool in $REQUIRED_TOOLS; do
            if ! grep -F "[xbrl-auditing MCP] ${required_tool} called" "$mcp_debug_log" >/dev/null 2>&1; then
                echo "[$count] failed: required MCP tool ${required_tool} was not called for ${prompt_id}" | tee -a "$LOG"
                rm -rf "$tmp_output_dir"
                rm -f "$mcp_debug_log"
                exit 1
            fi
        done

        result_file_count="$(find "$tmp_output_dir" -maxdepth 1 -type f -name '*.json' | wc -l | tr -d ' ')"
        if [ "$result_file_count" -ne 1 ]; then
            echo "[$count] failed: expected exactly 1 result file for ${prompt_id}, found ${result_file_count} in ${tmp_output_dir}" | tee -a "$LOG"
            rm -f "$mcp_debug_log"
            exit 1
        fi

        result_file="$(find "$tmp_output_dir" -maxdepth 1 -type f -name '*.json' | sort | head -n 1)"
        case "$result_file" in
            *"_${prompt_id}_"*)
                ;;
            *)
                echo "[$count] failed: result file does not match expected id ${prompt_id}: ${result_file}" | tee -a "$LOG"
                rm -f "$mcp_debug_log"
                exit 1
                ;;
        esac

        mkdir -p "$requested_output_dir"
        mv "$result_file" "$requested_output_dir/"
        rm -rf "$tmp_output_dir"
        rm -f "$mcp_debug_log"
        echo "[$count] completed at $(date)" | tee -a "$LOG"
    else
        rm -rf "$tmp_output_dir"
        rm -f "$mcp_debug_log"
        echo "[$count] failed with exit code $status at $(date)" | tee -a "$LOG"
        exit "$status"
    fi

done < "$INPUT"
