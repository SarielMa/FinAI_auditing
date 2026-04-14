---
name: trading
description: >
  Executes a daily trading decision task (BUY/SELL/HOLD) for a single stock over a
  3-month window using parquet data files that contain price, news, 10-K, 10-Q, and
  momentum fields. Handles data loading, strict chronological day-by-day processing
  (no future data leakage), reasoning over multi-modal signals, and writing the final
  structured JSON result to results/trading/.

  Use this skill whenever the user asks you to run a single stock trading task, make trading
  decisions from parquet data, execute a stock trading simulation, or produce a
  trading results JSON — even if they phrase it as "trade AAPL", "run the trading
  experiment", "do the trading task for MSFT", or "process the trading data".
---

# Trading Skill

You are executing a daily-frequency trading decision task for a single stock over a
3-month window (2025-03-01 to 2025-05-31). Your job is to reason over multi-modal
signals — price, news, earnings filings, momentum — and output one of three actions
per trading day: **BUY**, **SELL**, or **HOLD**.

Integrity of the simulation depends entirely on you never using future information.
Read this skill carefully before starting.

For the input and outpu data, user will provide a path to the input files and also 
a path to the output. e.g., "The dataset is at `/data/trading`", "Please output the
final json to `/results/trading`.

User's full request would look like the following:

```
Please make trading decision for AAPL. The input data is at /data/trading, 
please save the output json to /results/trading.
```

---

## Setup

### Identify the target ticker

The user will specify (or you can infer from context) which of the 10 available
tickers to trade:

`AAPL`, `ADBE`, `AMZN`, `BMRN`, `CRM`, `GOOGL`, `META`, `MSFT`, `NVDA`, `TSLA`

The data file for ticker `XYZ` lives at:

```
data/trading/XYZ-00000-of-00001.parquet
```

### Identify the model name

The output filename encodes which model produced the results. Use the actual model
identifier from your system context (e.g., `claude-sonnet-4-6`). Sanitize both
`ticker` and `model` for use in filenames: replace any characters that are not
alphanumeric, `-`, or `_` with `_`, and lowercase the model name.

Example: `claude-code_trading_AAPL_claude-sonnet-4-6.json`

### Ensure the output directory exists

You can create the following folder to save the output:

```
results/trading/
```

Create it if it doesn't exist yet.

---

## Loading the data

Use Python + pandas to read the parquet file:

```python
import pandas as pd
df = pd.read_parquet("data/trading/TICKER-00000-of-00001.parquet")
df = df.sort_values("date").reset_index(drop=True)
```

**Schema** — each row is one calendar date for the ticker:

| Field      | Type            | Notes |
|------------|-----------------|-------|
| `date`     | string          | e.g., `"2025-01-02"` |
| `asset`    | string          | ticker symbol |
| `prices`   | float64         | daily price (use as close price) |
| `news`     | list[string] / ndarray | news headlines/summaries for that day |
| `10k`      | list[string] / ndarray | 10-K excerpts (may be empty most days) |
| `10q`      | list[string] / ndarray | 10-Q excerpts (may be empty most days) |
| `momentum` | string          | directional label, e.g. `"up"`, `"down"`, `"neutral"` |

**Important:** After `read_parquet`, the list fields (`news`, `10k`, `10q`) may come
back as `numpy.ndarray` objects, not Python `list`. Do **not** check `isinstance(x,
list)` to decide if a field is empty. Instead use:

```python
import numpy as np

def is_nonempty(val):
    if val is None:
        return False
    if isinstance(val, (list, np.ndarray)):
        return len(val) > 0
    return bool(val)
```

---

## The trading loop — strict chronological order

This is the heart of the task. Process days one at a time, in order. **Never read
ahead.**

```
for each trading day t in [2025-03-01 .. 2025-05-31]:
    1. Slice the dataframe to rows where date <= t  (visible history up to and including t)
    2. Extract today's row (date == t); skip if not in the dataset (non-trading day)
    3. Gather signals for today
    4. Reason and decide: BUY / SELL / HOLD
    5. Record the decision immediately — once recorded, never change it
    6. Move to t+1
```

Why does order matter so much? Because this task is measuring whether you can make
realistic trading decisions without peeking at future prices or future filings. Even
reading tomorrow's news in a pre-scan before making today's decision would be
cheating. Treat each day as if you are sitting at a terminal on that morning.

### Which days to process

Only process days that actually appear in the dataset within the window — skip
weekends and holidays (they have no rows). The loop should cover the window
`2025-03-01` through `2025-05-31` inclusive.

---

## Signals and reasoning

On each trading day, you have access to:

- **`prices`** — today's price, plus all historical prices you've seen so far
- **`momentum`** — today's directional label
- **`news`** — today's news items (could be empty)
- **`10k`** / **`10q`** — any earnings/filing excerpts released on or before today

### How to reason

Your `trajectory` field (see output format below) should briefly explain:
1. What signals you saw today (momentum label, any notable news, any filings)
2. How those signals influenced your decision
3. The action you chose and a one-sentence rationale

You don't need to be exhaustive — 2-4 sentences is fine. The point is that the
reasoning is traceable and grounded in the data you actually observed.

**Good example:**
> "Momentum: up. News: positive analyst upgrade. No filings today. Strong bullish
> signal — prior 5-day trend also upward. Decision: BUY."

**Bad example (uses future info):**
> "The stock will drop next week, so I'll sell now."

---

## Output format

Write a single JSON file to `results/trading/{agent_name}_trading_{ticker}_{model}.json`, the `agent_name` is your name, e.g., "codex" or "claude-code":

```json
{
  "status": "completed",
  "start_date": "2025-03-01",
  "end_date": "2025-05-28",
  "model": "claude-sonnet-4-6",
  "recommendations": [
    {
      "date": "2025-03-02",
      "price": 182.45,
      "recommended_action": "BUY",
      "trajectory": "Momentum: up. News mentions strong holiday sales. Decision: BUY on positive sentiment."
    },
    {
      "date": "2025-03-03",
      "price": 180.10,
      "recommended_action": "HOLD",
      "trajectory": "Momentum: neutral. No notable news. Holding position to avoid whipsaw."
    }
  ]
}
```

**Field rules:**

| Field | Rule |
|-------|------|
| `status` | `"completed"` if all days processed successfully; `"partial"` if stopped early |
| `start_date` | First date actually processed |
| `end_date` | Last date actually processed |
| `model` | The model identifier (sanitized for filename use) |
| `recommendations[].date` | Trading date string `YYYY-MM-DD` |
| `recommendations[].price` | The `prices` value for that day (float) |
| `recommendations[].recommended_action` | Exactly one of: `"BUY"`, `"SELL"`, `"HOLD"` (uppercase) |
| `recommendations[].trajectory` | Your reasoning for that day (1-4 sentences) |

**Write the file once, at the end**, after all decisions are made. Accumulate
decisions in memory and write one final JSON.

---

## What NOT to do

- Do not pre-scan the full date range before starting the loop
- Do not compute statistics across the whole window before trading (e.g., "on 60% of
  days news was positive" — that uses future data)
- Do not create temporary `.py` files, notebooks, debug logs, or intermediate files
- Do not modify the result file once written
- Do not output multiple result files for the same run

If you need to compute something, do it in memory within the loop.

---

## Implementation approach

The cleanest approach: write a short inline Python script via the Bash tool that
loads the parquet, loops over trading days chronologically, collects
`(date, price, action, trajectory)` tuples, then writes the final JSON. Keep all
intermediate computation in memory. Do not save the script to disk.
