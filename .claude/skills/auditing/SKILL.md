---
name: auditing
description: >
  Audits XBRL numeric facts in SEC-style filings by comparing the reported (book)
  value from the instance document against the correct (true) expected value derived
  from the filing's calculation linkbase, US-GAAP taxonomy, and XBRL sign conventions.
  The correct value may be a summation recomputation, a sign correction for directional
  concepts (expenditures, losses must be positive), or an algebraic derivation.
  Handles fact extraction, context resolution, period matching, balance-type checking,
  and writing the final JSON result to results/auditing/.

  Use this skill whenever the user asks to audit a filing, verify a reported XBRL
  value, compute a calculated value from linkbases, or check numeric consistency in
  a 10-K or 10-Q — even if they phrase it as "what is the reported value of X",
  "audit this concept", "check the filing math", or "verify AssetsCurrent for FY2021".
---

# Auditing Skill

You are auditing a single XBRL numeric fact in an SEC-style filing. Your job is to:
1. Extract the **reported (book) value** — the number literally stored in the filing's instance document.
2. Determine the **correct (true) value** — what the number *should be* in a valid XBRL filing.
3. Write one line of JSON to the output file.

These two values may differ. The correct value is **not always a mathematical recomputation** — it depends on the nature of the concept:
- For **summation concepts** (a concept that is the parent of children in `*_cal.xml`): recompute by summing weighted children.
- For **directional concepts** (expenditures, losses, deductions, contra-assets): the correct value is always a **positive absolute value** — the sign is encoded in the concept semantics, not in a negative number.
- For **child concepts** (a component within a parent sum): derive algebraically from the parent and siblings.
- For **other concepts** with no calculation relationships: report the value as found if it is consistent with its balance type.

Integrity of the audit depends on never substituting taxonomy-inferred relationships
for filing-specific ones, and never silently mismatching periods or contexts.
Read this skill carefully before starting.

For input and output paths, the user will provide them directly. For example:
"The data is at `/data/auditing`", "Please save results to `/results/auditing`".

A typical user request looks like:

```
Please audit the value of us-gaap:AdjustmentsRelatedToTaxWithholdingForShareBasedCompensation
for 2023-01-01 to 2023-12-31 in the 10k filing released by rrr on 2023-12-31.
What's the reported value? What's the actual value calculated from the relevant
linkbases and US-GAAP taxonomy? (id: mr_1)
The input data is at /data/auditing, please save the output to /results/auditing.
```

---

## Setup

### Parse the request into these parameters

| Parameter     | Example                    | Notes |
|---------------|----------------------------|-------|
| `agent_name`  | `claude-code`, `codex`     | your agent name, e.g. "claude-code"; used in output filename |
| `ticker`      | `rrr`, `zions`             | **lowercase** as it appears in folder names |
| `issue_time`  | `20231231`                 | format `YYYYMMDD` |
| `filing_name` | `10k`, `10q`               | lowercase |
| `concept_id`  | `us-gaap:AssetsCurrent`    | exact concept name including namespace prefix |
| `period`      | `FY2021`, `Q3 2022`, `2021-12-31`, `2021-01-01 to 2021-12-31` | user's expression |
| `id`          | `mr_1`                     | the value from `(id: ...)` in the user's request; used verbatim in the output filename |
| `model`       | `claude-sonnet-4-6`        | your model identifier from system context; sanitize for filename use |

### Ensure the output directory exists

```
results/auditing/
```

Create it if it doesn't exist yet.

---

## The audit workflow

Work through this checklist in order. **Use the MCP tools from the `xbrl-auditing` server at each step — do not write Python scripts.**

### Step 0 — Locate the filing

Call **`locate_filing`** first. This resolves the natural-language filing reference
into concrete file paths used by all downstream tools.

```
locate_filing(
  data_dir   = <user-provided data path>,   # e.g. "/data/auditing"
  filing_type = "10k" | "10q",
  ticker      = <ticker, lowercase>,
  issue_date  = <issue_time>                # "YYYYMMDD" or "YYYY-MM-DD"
)
```

Returns: `folder`, `instance_doc`, `cal_xml`, `xsd`, `def_xml`, `lab_xml`, `pre_xml`, `taxonomy_dir`.

Use these paths in all subsequent tool calls. If the tool returns an `"error"` key,
stop and report the error — do not guess file paths manually.

---

### Step 1 — Extract reported facts for the target concept

Call **`extract_xbrl_facts`** with the `instance_doc` path and the **local name**
of the concept (strip the namespace prefix: `us-gaap:AssetsCurrent` → `AssetsCurrent`).

```
extract_xbrl_facts(
  instance_doc_path  = <instance_doc from Step 0>,
  concept_local_name = <local name only, no prefix>
)
```

Each returned fact contains: `value`, `context_id`, `period_type`, `start_date`,
`end_date`, `instant_date`, `dimensions`.

Keep only facts whose resolved period matches the user's requested period exactly.
Do not silently switch between:
- instant and duration
- quarter-only and year-to-date
- current period and prior period
- consolidated and dimensional contexts

### Step 2 — Select the best candidate fact

Rank candidates by these preferences (highest first):

1. Exact concept match
2. Exact period match
3. No dimensions before dimensional facts
4. Numeric facts before non-numeric facts

Use the top-ranked fact as `extracted_value`. If multiple candidates remain equally
plausible, report the ambiguity rather than forcing a single answer.

### Step 3 — Build the calculation network

Call **`get_calculation_network`** with the `cal_xml` path and the full `concept_id`
(with namespace prefix).

```
get_calculation_network(
  cal_xml_path = <cal_xml from Step 0>,
  concept_id   = <full concept_id, e.g. "us-gaap:AssetsCurrent">
)
```

Returns: `role` (`"parent"` / `"child"` / `"both"` / `"none"`), `as_parent` (children
with weights per role), `as_child` (parent + siblings with weights per role).

Use this to determine which Case applies in Step 4.

### Step 4 — Get the balance type

Call **`get_balance_type`** with the `xsd` and `taxonomy_dir` paths.

```
get_balance_type(
  xsd_path     = <xsd from Step 0>,
  taxonomy_dir = <taxonomy_dir from Step 0>,
  concept_id   = <full concept_id>
)
```

Returns: `balance` (`"debit"` / `"credit"` / `"none"`), `source`.

### Step 5 — Determine the correct (calculated) value

Cases are **not mutually exclusive** — apply every case that matches.

---

**Case A — Summation parent** (`role` is `"parent"` or `"both"`)

Recompute by summing weighted children from `as_parent`:
1. For each child concept, call `extract_xbrl_facts` to find its value
2. Keep only facts matching the chosen parent's period exactly
3. Prefer the same dimension signature as the chosen parent fact
4. Multiply each child value by its `weight` and sum all contributions

→ `calculated_value` = sum of `weight × child_value` for all matched children.

If some children have no matching fact, the recomputation is **partial** — still
report the sum of available children but note it is partial.

---

**Case B — Directional concept** (`balance` is `"debit"` and concept represents an
outflow/reduction, **or** `balance` is `"credit"` and concept represents a
contra-asset/contra-equity)

In XBRL, directional concepts must always be filed as **positive absolute values**.

- If `extracted_value` is negative → `calculated_value` = `abs(extracted_value)`
- If `extracted_value` is already positive → `calculated_value` = same value

When Cases A and B both apply: first recompute the sum (Case A), then apply
the sign rule: `calculated_value` = `abs(recomputed sum)`.

---

**Case C — Calculation child only** (`role` is `"child"` only)

Derive algebraically using sibling values from `as_child`:
`calculated_value` = `(parent_value - sum(sibling_weight × sibling_value)) / own_weight`

Call `extract_xbrl_facts` as needed to get parent and sibling values.
Use exact weights and matching contexts for all facts.

---

**Case D — No calculation relationships and neutral balance type**
(`role` is `"none"` and `balance` is `"none"`)

No recomputation is possible and no sign correction is required.
→ `calculated_value` = `extracted_value` (report as found).
State explicitly that no calculation network was found and no sign correction applies.

---

## Ambiguity handling

Pay extra attention when:

- Multiple filing folders match the same ticker and issue date
- The concept appears as a parent in several calculation roles
- The filing uses extension concepts (custom `xlink:href` fragments) that change the expected subtotal
- The selected calculation role has many missing children
- Multiple candidate facts survive period filtering (dimensional vs. non-dimensional)

In these cases, surface the ambiguity in a brief note before writing the output file —
but the output file must still contain exactly one JSON line.

---

## Output format

Call **`write_audit_result`** to write the final output:

```
write_audit_result(
  output_dir       = <user-provided output path>,   # e.g. "/results/auditing"
  filename         = "{agent_name}_auditing_{filing_name}_{ticker}_{issue_time}_{id}_{model}",
  extracted_value  = "<value string>",
  calculated_value = "<value string>"
)
```

Example filename: `claude-code_auditing_10k_rrr_20231231_mr_1_claude-sonnet-4-6`

The tool writes exactly one line:
```json
{"extracted_value": "-1234567000", "calculated_value": "1234567000"}
```

**Field rules:**

| Field | Rule |
|-------|------|
| `extracted_value` | Numeric string **exactly as it appears** in the instance document (may be negative); `"0"` if not found |
| `calculated_value` | Numeric string of the **correct expected value** per Step 5 (Case A/B/C/D); `"0"` if not determinable |

- Preserve numeric values exactly as strings (do not reformat or round).
- Do not call `write_audit_result` more than once per audit run.

---

## What NOT to do

- Do not write inline Python scripts or use the Bash tool for XBRL parsing — use the MCP tools
- Do not replace filing-specific calculation networks with taxonomy-only relationships
  unless the filing network is absent (and state that fallback explicitly)
- Do not silently switch period types (instant vs. duration, quarter vs. YTD)
- Do not use `.htm` files — always work with the XML files returned by `locate_filing`
- Do not confuse arc direction: `xlink:from` = parent (sum), `xlink:to` = child (component)
- Do not report a negative `calculated_value` for directional concepts (expenditures, losses, deductions) — these must always be positive absolute values in valid XBRL
- Do not create temporary scripts, debug logs, or intermediate files
- Do not write multiple output files for the same audit run
- Do not add any text outside the JSON on the output line
