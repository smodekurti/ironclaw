---
name: image-analyzer
description: Describe, analyse, and extract information from images. Use when the user shares an image and wants a description, text extraction, diagram analysis, or visual QA.
license: Apache-2.0
compatibility: Requires a vision-capable model (claude-3+, gpt-4o, gemini-2.0+). Images must be accessible as file paths or URLs.
metadata:
  author: ironclaw
  version: "1.0"
  certified: "true"
---

# Image Analyzer Skill

## Overview

Analyse images with precision. Describe content, extract text, interpret charts, and answer visual questions.

## Instructions

### Step 1 — Confirm vision capability

Before attempting image analysis, verify the current model supports vision. If not, inform the user and suggest switching to a vision model (claude-sonnet-4-6, gpt-4o, gemini-2.5-flash, etc.).

### Step 2 — Understand the request type

Choose the right analysis mode:

| Request type          | Approach                                                    |
|-----------------------|-------------------------------------------------------------|
| General description   | Describe all visible elements systematically               |
| Text extraction (OCR) | Read all visible text, preserve formatting                  |
| Chart / graph         | Identify chart type, axes, data series, trends, anomalies   |
| Diagram               | Explain components, relationships, flow                     |
| Screenshot            | Describe UI, identify errors, explain what's shown          |
| Photo (people/places) | Describe setting, actions, notable elements (no ID of people)|
| Document image        | Extract text, note structure (tables, headings, etc.)       |

### Step 3 — Systematic description

When describing an image, cover:
1. **Overall**: What type of image is this? What is the main subject?
2. **Foreground**: Key objects, text, or elements in focus
3. **Background**: Setting, context, additional elements
4. **Text**: Any written content, verbatim
5. **Numbers/data**: Any metrics, measurements, or quantitative information
6. **Colours/condition**: Relevant visual properties

### Step 4 — For charts and graphs

Provide:
- Chart type (bar, line, pie, scatter, etc.)
- X and Y axis labels and ranges
- Each data series and its values
- Overall trend (increasing, decreasing, volatile, flat)
- Peak and trough values with dates/labels
- Any notable anomalies or outliers

### Step 5 — For technical content

For code screenshots, error messages, or technical diagrams:
- Transcribe code or error messages exactly
- Identify the programming language or tool
- Explain what the code does or what the error means
- Suggest fixes if it's an error

## Output format

**General description:**
```
**Type:** [photo / diagram / screenshot / chart]
**Subject:** [main subject in one line]

**Description:**
[Detailed description in natural language]

**Extracted text:**
[Any text visible in the image, verbatim]
```

**Chart analysis:**
```
**Chart type:** [type]
**Data:** [description of data series and key values]
**Trend:** [overall trend]
**Key insight:** [most important takeaway]
```

## Privacy and ethics

- Never attempt to identify specific individuals from photos
- Do not make assumptions about people's identity, health, or background from appearance
- For sensitive images (medical, legal, security), note the sensitivity and handle with care
