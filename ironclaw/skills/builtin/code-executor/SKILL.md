---
name: code-executor
description: Write and execute Python or Bash code to solve problems, run calculations, process files, automate tasks, or test ideas. Use when the user wants to run code, compute something, or automate a task.
license: Apache-2.0
compatibility: Requires shell:execute or a code execution tool. Python 3.9+ must be available.
metadata:
  author: ironclaw
  version: "1.0"
  certified: "true"
allowed-tools: shell:execute file:read file:write
---

# Code Executor Skill

## Overview

Write, execute, and iterate on code to solve the user's task. Handle errors gracefully and explain the output.

## Instructions

1. **Understand the task** — clarify inputs, outputs, and constraints before writing code.

2. **Write clean code**:
   - Include clear comments
   - Handle errors with try/except (Python) or error checks (Bash)
   - Avoid hard-coded paths; use variables or arguments
   - Print meaningful output

3. **Execute via `shell:execute`**:
   - For Python: `python3 -c "..."` for short snippets, or write to a temp file and run it
   - For Bash: pass the script directly
   - Always include a timeout; warn the user if the task may take long

4. **Show the output**:
   - Display stdout/stderr clearly
   - If the output is long, summarise it and show the first/last N lines

5. **Iterate on errors**:
   - If execution fails, read the error message, fix the code, and retry
   - Explain what the error was and how you fixed it
   - Maximum 3 retry attempts before asking the user for guidance

6. **Save results** (if applicable):
   - Use `file:write` to save outputs the user will want to keep
   - Confirm the file path to the user

## Output format

```
**Code:**
```python
# your code here
```

**Output:**
```
execution output here
```

**Summary:** [one-sentence explanation of what happened]
```

## Security notes

- Never execute code from untrusted external sources without reviewing it first
- Avoid `rm -rf`, disk-filling loops, or network calls to unknown endpoints
- If the task requires elevated permissions, inform the user and ask for confirmation

## Common patterns

### Quick calculation
```python
import math
print(math.factorial(20))
```

### Process a file
```python
import json, pathlib
data = json.loads(pathlib.Path("input.json").read_text())
# ... process ...
print(result)
```

### Install a package and use it
```bash
pip install pandas --break-system-packages -q
python3 -c "import pandas as pd; df = pd.read_csv('data.csv'); print(df.describe())"
```
