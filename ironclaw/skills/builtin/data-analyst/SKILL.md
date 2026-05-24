---
name: data-analyst
description: Analyse CSV, JSON, or tabular data to produce summaries, statistics, trends, and insights. Use when the user shares data files or asks questions about data, datasets, metrics, or numbers.
license: Apache-2.0
compatibility: Requires file:read and optionally shell:execute with Python/pandas available.
metadata:
  author: ironclaw
  version: "1.0"
  certified: "true"
allowed-tools: file:read file:write shell:execute
---

# Data Analyst Skill

## Overview

Load, explore, and analyse structured data. Produce clear summaries, statistics, and actionable insights.

## Instructions

### Step 1 — Load the data

- Use `file:read` to inspect the file (first ~50 lines to understand structure)
- Identify: format (CSV/JSON/TSV), column names, data types, approximate row count
- Note obvious quality issues: missing values, mixed types, encoding problems

### Step 2 — Exploratory analysis

Run the appropriate analysis via `shell:execute`:

**For CSV/tabular data (Python + pandas):**
```python
import pandas as pd
df = pd.read_csv("path/to/file.csv")
print(f"Shape: {df.shape}")
print(df.dtypes)
print(df.describe())
print(df.isnull().sum())
print(df.head())
```

**For JSON data:**
```python
import json, pandas as pd
data = json.load(open("path/to/file.json"))
# Inspect structure, then convert to DataFrame if applicable
```

### Step 3 — Answer the specific question

Focus on what the user actually asked:
- Aggregations: group-by, sum, mean, count
- Trends: sort by date/time column, compute deltas
- Comparisons: filter subsets, compute percentages
- Outliers: identify rows outside N standard deviations

### Step 4 — Present results clearly

- Use plain tables for small result sets (≤ 20 rows)
- Summarise large results: "Top 5 of 10,000 rows…"
- Always include units (if known)
- Highlight the 2–3 most important findings first

### Step 5 — Offer next steps

Suggest 2–3 follow-up analyses the user might find useful.

## Output format

```
**Dataset overview**
- Rows: N | Columns: M
- Key columns: col1 (type), col2 (type)
- Missing data: col3 has 12% missing

**Analysis results**
[tables, numbers, or charts here]

**Key findings**
1. ...
2. ...

**Suggested next steps**
- ...
```

## Data quality checklist

Before drawing conclusions, check:
- [ ] Are date columns parsed correctly?
- [ ] Are numeric columns free of string contamination?
- [ ] Are there duplicate rows?
- [ ] Is the sample size large enough to be meaningful?
