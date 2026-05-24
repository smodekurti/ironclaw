---
name: web-research
description: Search the web and synthesise accurate, cited answers. Use when the user asks for current information, facts, news, comparisons, or anything that benefits from live web data.
license: Apache-2.0
compatibility: Requires web:search and web:fetch tools enabled on the agent.
metadata:
  author: ironclaw
  version: "1.0"
  certified: "true"
allowed-tools: web:search web:fetch
---

# Web Research Skill

## Overview

This skill guides the agent to perform structured web research: search, retrieve, synthesise, and cite sources clearly.

## Instructions

Follow these steps for every web research task:

1. **Understand the question** — identify key entities, time sensitivity, and required depth (quick fact vs. deep analysis).

2. **Formulate search queries** — use 2–4 targeted queries. Vary phrasing to catch different angles. Avoid overly broad or overly narrow terms.

3. **Search and retrieve** — use `web:search` for each query. For the most promising results, follow up with `web:fetch` to read the full page.

4. **Evaluate sources** — prefer:
   - Official documentation, primary sources, reputable publications
   - Pages with a clear date (prioritise recent results for time-sensitive topics)
   - Avoid paywalled or login-required pages unless the snippet is sufficient

5. **Synthesise** — combine information from multiple sources. Note where sources agree or disagree. Do not copy-paste; write a coherent answer.

6. **Cite your sources** — at the end of your answer include a "Sources" section with:
   - Title of the page
   - URL
   - Date (if visible)

7. **Flag uncertainty** — if information is conflicting or unavailable, say so explicitly.

## Output format

```
[Your synthesised answer]

**Sources**
- [Page Title](URL) — published YYYY-MM-DD
- [Page Title](URL)
```

## Edge cases

- If search returns no useful results, try alternative query formulations before saying you cannot find information.
- For rapidly changing topics (prices, stock, live scores), note that data may be stale.
- If asked for an opinion, clearly label it as such after presenting the facts.
