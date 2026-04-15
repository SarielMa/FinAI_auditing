#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export XBRL_AUDITING_MCP_ACTIVE=1
export XBRL_AUDITING_MCP_LOG="${XBRL_AUDITING_MCP_LOG:-/tmp/xbrl_auditing_mcp.log}"

exec python -u "$SCRIPT_DIR/server.py"
