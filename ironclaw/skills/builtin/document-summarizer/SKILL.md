---
name: document-summarizer
description: Summarise long documents, reports, articles, or PDFs into concise, structured notes. Use when the user shares a file or long text and wants a summary, key points, or TL;DR.
license: Apache-2.0
compatibility: Requires file:read tool. For PDFs, pdfminer or pypdf must be available.
metadata:
  author: ironclaw
  version: "1.0"
  certified: "true"
allowed-tools: file:read shell:execute
---

# Document Summarizer Skill

## Overview

Read long documents and produce structured, accurate summaries at the right level of detail.

## Instructions

### Step 1 — Load the document

- Use `file:read` for plain text, Markdown, or code files
- For PDFs, extract text via shell:
  ```bash
  python3 -c "import sys; from pdfminer.high_level import extract_text; print(extract_text(sys.argv[1]))" document.pdf
  ```
  Or with pypdf:
  ```python
  import pypdf
  reader = pypdf.PdfReader("document.pdf")
  text = "\n".join(p.extract_text() for p in reader.pages)
  print(text[:5000])
  ```

### Step 2 — Assess length and structure

- Short (< 1000 words): read fully, summarise all key points
- Medium (1000–5000 words): read fully, identify 5–10 key points
- Long (> 5000 words): chunk into sections, summarise each, then produce a master summary

### Step 3 — Identify document type

Apply the right template:

| Type                  | Focus on                                       |
|-----------------------|------------------------------------------------|
| Research paper        | Problem, method, results, limitations          |
| Business report       | Findings, recommendations, action items        |
| Legal document        | Obligations, rights, key dates, risk areas     |
| News article          | Who/what/when/where/why, key quotes            |
| Technical docs        | Purpose, prerequisites, key APIs/steps         |
| Meeting notes         | Decisions made, action items, owners, deadlines|

### Step 4 — Write the summary

**Standard format:**

```
## TL;DR
[1–3 sentence executive summary]

## Key Points
1. ...
2. ...
3. ...

## Details
[Longer explanation of important sections, if needed]

## Action Items / Recommendations
- [ ] [Item] — Owner — Deadline

## Notable Quotes
> "[exact quote]" — [source/page]
```

**Short format (for quick requests):**
```
**Summary:** [2–4 sentences]
**Key takeaways:** bullet list of 3–5 points
```

### Step 5 — Accuracy rules

- Do **not** add facts not present in the document
- Do **not** remove critical caveats or warnings
- Preserve specific numbers, dates, and names exactly
- If the document is ambiguous, say so

## Handling large documents

For very long documents (books, large reports):
1. Read the table of contents / headings first
2. Summarise chapter by chapter
3. Produce an overall synthesis at the end
4. Ask the user if they want to deep-dive any section
