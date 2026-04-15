# XBRL Auditing MCP README

This repository contains the benchmarking setup for XBRL auditing with a dedicated MCP server. The MCP server exposes a small set of auditing tools so the model does not need to parse XBRL files with ad hoc scripts.

## Project tree

The main project structure is:

```text
FinAI_auditing_project/
├── README.md
├── .claude/
│   └── skills/
│       ├── auditing/           <- new skills for the MCP tools
│       ├── pair_trading/
│       ├── report_evaluation/
│       ├── report_generation/
│       └── trading/
├── .codex/
│   └── skills/
│       ├── auditing/            
│       ├── pair_trading/        
│       ├── report_evaluation/  
│       ├── report_generation/   
│       └── trading/             
└── financial_agentic_benchmark/
    ├── run_claude.sh
    ├── run_codex.sh
    ├── data/
    ├── evaluation/
    ├── logs/
    ├── prompts/
    ├── results/
    └── mcp/
        ├── mcp_config.json
        └── xbrl_auditing/
            ├── run_server.sh    <- MCP server launcher
            └── server.py        <- MCP tool definitions
```

Highlights:

- MCP tools are implemented in `financial_agentic_benchmark/mcp/xbrl_auditing/server.py`.
- The MCP server wrapper is `financial_agentic_benchmark/mcp/xbrl_auditing/run_server.sh`.
- The updated skills are under `.claude/skills/`.

## 1. The five MCP tools used in the audit workflow

The operational audit flow uses these five MCP tools from the `xbrl-auditing` server. Their definitions are implemented in `financial_agentic_benchmark/mcp/xbrl_auditing/server.py`.

### 1. `locate_filing`

Purpose: resolve a natural-language filing reference into concrete paths inside the benchmark dataset.

Inputs:

- `data_dir: str`
  Root directory that contains the `XBRL/` and `US_GAAP_Taxonomy/` folders.
- `filing_type: str`
  Filing type such as `10k`, `10q`, or equivalent normalized forms.
- `ticker: str`
  Company ticker, case-insensitive.
- `issue_date: str`
  Filing issue date in `YYYYMMDD` or `YYYY-MM-DD`.

Output:

```json
{
  "folder": "str",
  "instance_doc": "str",
  "cal_xml": "str",
  "xsd": "str | null",
  "def_xml": "str | null",
  "lab_xml": "str | null",
  "pre_xml": "str | null",
  "taxonomy_dir": "str | null"
}
```

Error output:

```json
{
  "error": "str"
}
```

Use in the workflow: this is always the first call. All downstream tool calls depend on the file paths it returns.

### 2. `extract_xbrl_facts`

Purpose: extract the reported numeric facts for a target concept from the filing instance document.

Inputs:

- `instance_doc_path: str`
  Absolute path to the filing instance document, usually `*_htm.xml`.
- `concept_local_name: str`
  Local concept name only, with namespace prefix removed. Example: `AssetsCurrent`.

Output:

```json
[
  {
    "value": "str",
    "context_id": "str",
    "period_type": "duration | instant | null",
    "start_date": "str | null",
    "end_date": "str | null",
    "instant_date": "str | null",
    "dimensions": {
      "dimension_name": "member_value"
    }
  }
]
```

Parse-failure output:

```json
[
  {
    "error": "str"
  }
]
```

Use in the workflow: used first to get the reported value of the audited concept, then reused to fetch parent, child, or sibling facts when the calculation tree has to be recomputed.

### 3. `get_calculation_network`

Purpose: inspect the filing calculation linkbase and show whether the concept is a parent, a child, both, or not present in the calculation graph.

Inputs:

- `cal_xml_path: str`
  Absolute path to the filing calculation linkbase, usually `*_cal.xml`.
- `concept_id: str`
  Full concept id including namespace prefix, for example `us-gaap:AssetsCurrent`.

Output:

```json
{
  "role": "parent | child | both | none",
  "as_parent": [
    {
      "role_uri": "str",
      "children": [
        {
          "concept": "str",
          "weight": "float"
        }
      ]
    }
  ],
  "as_child": [
    {
      "role_uri": "str",
      "parent": "str",
      "own_weight": "float",
      "siblings": [
        {
          "concept": "str",
          "weight": "float"
        }
      ]
    }
  ]
}
```

Error output:

```json
{
  "error": "str"
}
```

Use in the workflow: tells the agent whether to recompute a summation, solve a missing child algebraically, or leave the fact as a non-calculation concept.

### 4. `get_balance_type`

Purpose: determine the XBRL balance type for the concept, checking the filing extension schema first and the US-GAAP taxonomy second.

Inputs:

- `xsd_path: str`
  Absolute path to the filing extension schema `.xsd`.
- `taxonomy_dir: str`
  Path to the matching `gaap_chunks_<year>/` taxonomy directory.
- `concept_id: str`
  Full concept id including namespace prefix.

Output:

```json
{
  "balance": "debit | credit | none",
  "source": "xsd | taxonomy | not_found"
}
```

Use in the workflow: used mainly for sign handling and directional concepts, such as outflows, deductions, and contra concepts.

### 5. `write_audit_result`

Purpose: persist the final answer for one audit task as a one-line JSON file.

Inputs:

- `output_dir: str`
  Target output directory, typically `results/auditing/`.
- `filename: str`
  Output filename without extension.
- `extracted_value: str`
  The raw reported value exactly as found in the filing.
- `calculated_value: str`
  The corrected or recomputed expected value.

Output:

```json
{
  "status": "ok",
  "path": "str"
}
```

Error output:

```json
{
  "status": "error",
  "message": "str"
}
```

Use in the workflow: this is the final tool call. It writes the benchmark artifact consumed by evaluation.

Note: the server also defines a small `ping` tool for connectivity checks, but the core audit workflow above is the five-tool path enforced by the runner.

## 2. Skill paths under `.claude` and `.codex`

The legacy Claude auditing skill file is:

```text
.claude/skills/auditing/SKILL.md
```

The new Codex auditing skill file is:

```text
.codex/skills/auditing/SKILL.md
```

Additional new Codex skills are:

```text
.codex/skills/pair_trading/SKILL.md
.codex/skills/report_evaluation/SKILL.md
.codex/skills/report_generation/SKILL.md
.codex/skills/trading/SKILL.md
```

These skill files describe the task workflows and instruct the model to use the available MCP tools or local project artifacts instead of writing ad hoc parsing code.

### How the auditing skill uses the five tools

The skill is a workflow layer on top of the MCP server:

1. It parses the user request into filing metadata, concept id, period, output path, and run id.
2. It calls `locate_filing` to resolve the filing into concrete file paths.
3. It calls `extract_xbrl_facts` to identify the reported fact for the audited concept.
4. It calls `get_calculation_network` to determine whether the concept is a parent, a child, both, or has no calculation relationship.
5. It calls `get_balance_type` to determine whether sign normalization is required.
6. It may call `extract_xbrl_facts` additional times for children, siblings, or parents needed for recomputation.
7. It calls `write_audit_result` to save the final JSON output.

In short, the skill provides the decision logic, while the MCP tools provide the authoritative filing lookups and output writing.

## 3. How the MCP server is added and configured

There are two configuration paths in this workspace.

### Batch runs through `financial_agentic_benchmark/run_claude.sh`

`financial_agentic_benchmark/run_claude.sh` passes Claude an MCP config file:

```json
{
  "mcpServers": {
    "xbrl-auditing": {
      "command": "bash",
      "args": ["mcp/xbrl_auditing/run_server.sh"]
    }
  }
}
```

That config lives at:

```text
financial_agentic_benchmark/mcp/mcp_config.json
```

The wrapper script started by Claude is:

```text
financial_agentic_benchmark/mcp/xbrl_auditing/run_server.sh
```

That wrapper:

- sets `XBRL_AUDITING_MCP_ACTIVE=1`
- sets `XBRL_AUDITING_MCP_LOG` for MCP debug tracing
- launches `financial_agentic_benchmark/mcp/xbrl_auditing/server.py`

### Local Claude Code settings

There is also a Claude settings file in this workspace:

```text
.claude/settings.local.json
```

It defines the same MCP server as a stdio server using a direct Python command:

```json
{
  "mcpServers": {
    "xbrl-auditing": {
      "type": "stdio",
      "command": "/home/lm2445/.conda/envs/finben_vllm3/bin/python3",
      "args": [
        "/nfs/roberts/project/pi_sjf37/lm2445/FinAI_auditing_project/financial_agentic_benchmark/mcp/xbrl_auditing/server.py"
      ]
    }
  }
}
```

## 4. How to run `sh run_claude.sh` and where outputs/evidence go

Run the batch script with a start and end prompt index:

```bash
cd financial_agentic_benchmark
sh run_claude.sh 1 2
```

What the script does:

1. Reads prompts from `prompts/auditing.txt`
2. Starts Claude with `--mcp-config mcp/mcp_config.json`
3. Writes Claude stdout/stderr to `logs/auditing.log`
4. Captures MCP tool-call traces in a temporary `.claude_mcp_*` log
5. Appends that MCP trace into `logs/auditing.log`
6. A separate Codex runner is available as `financial_agentic_benchmark/run_codex.sh`

### Audit evidence

The main evidence file is:

```text
financial_agentic_benchmark/logs/auditing.log
```

This log contains:

- the original prompt line
- Claude execution output
- MCP trace lines such as `[xbrl-auditing MCP] locate_filing called`
- completion or failure markers

If you meant `audit.log`, the actual file name in this repo is `logs/auditing.log`.
If you mean the repository-root path, that file is `financial_agentic_benchmark/logs/auditing.log`.

### Results path

The audit result JSON files are written under:

```text
financial_agentic_benchmark/results/auditing/
```

Current examples:

```text
financial_agentic_benchmark/results/auditing/claude-code_auditing_10k_rrr_20231231_mr_1_claude-sonnet-4-6.json
financial_agentic_benchmark/results/auditing/claude-code_auditing_10k_brn_20220930_mr_2_claude-sonnet-4-6.json
```

The prompts in `financial_agentic_benchmark/prompts/auditing.txt` explicitly tell the agent to save output to `results/auditing`, and the auditing skill also instructs the model to write results there.

## 5. Where the MCP tools are defined

The MCP tools are defined in:

```text
financial_agentic_benchmark/mcp/xbrl_auditing/server.py
```

They are registered with `FastMCP("xbrl-auditing")` and exposed through `@mcp.tool()` decorators. The relevant tool definitions in that file are:

- `ping`
- `locate_filing`
- `extract_xbrl_facts`
- `get_calculation_network`
- `get_balance_type`
- `write_audit_result`

## File map

- `financial_agentic_benchmark/run_claude.sh`: batch runner for Claude with MCP enabled
- `financial_agentic_benchmark/run_codex.sh`: batch runner for Codex
- `financial_agentic_benchmark/mcp/mcp_config.json`: MCP server config used by `run_claude.sh`
- `financial_agentic_benchmark/mcp/xbrl_auditing/run_server.sh`: MCP startup wrapper
- `financial_agentic_benchmark/mcp/xbrl_auditing/server.py`: actual MCP server and tool definitions
- `.claude/settings.local.json`: local Claude MCP configuration
- `.claude/skills/auditing/SKILL.md`: Claude auditing skill
- `.codex/skills/auditing/SKILL.md`: new Codex auditing skill
- `.codex/skills/pair_trading/SKILL.md`: new Codex pair-trading skill
- `.codex/skills/report_evaluation/SKILL.md`: new Codex report-evaluation skill
- `.codex/skills/report_generation/SKILL.md`: new Codex report-generation skill
- `.codex/skills/trading/SKILL.md`: new Codex trading skill
- `financial_agentic_benchmark/prompts/auditing.txt`: batch prompt list
- `financial_agentic_benchmark/logs/auditing.log`: execution and MCP evidence log
- `financial_agentic_benchmark/results/auditing/`: final JSON audit outputs
