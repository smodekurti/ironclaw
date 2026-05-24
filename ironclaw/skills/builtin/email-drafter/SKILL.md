---
name: email-drafter
description: Draft professional emails — requests, follow-ups, introductions, complaints, pitches, rejections, and more. Use when the user asks to write, compose, or improve an email.
license: Apache-2.0
metadata:
  author: ironclaw
  version: "1.0"
  certified: "true"
---

# Email Drafter Skill

## Overview

Draft clear, professional emails tailored to the right tone, audience, and purpose.

## Instructions

### Step 1 — Gather context (if not already provided)

Before drafting, identify:
- **Purpose**: What should this email accomplish? (request / inform / follow-up / apologise / pitch / decline)
- **Recipient**: Who is this to? (colleague / client / executive / vendor / stranger)
- **Tone**: Formal, semi-formal, or casual?
- **Key points**: What must the email include?
- **Call to action**: What do you want the reader to do?

If the user hasn't specified, make reasonable assumptions and state them at the top.

### Step 2 — Draft the email

Structure:
```
Subject: [Clear, specific subject line]

[Salutation],

[Opening — establish context or relationship in one sentence]

[Body — main message in 1–3 short paragraphs]
  - Lead with the most important information
  - One idea per paragraph
  - Use bullet points for lists of 3+ items

[Call to action — specific, polite, with a deadline if applicable]

[Closing]
[Signature]
```

### Step 3 — Apply tone guidelines

| Recipient       | Tone       | Salutation           | Sign-off             |
|-----------------|------------|----------------------|----------------------|
| Executive/VIP   | Formal     | Dear [Title Name],   | Sincerely, / Regards, |
| Client/external | Semi-formal| Hi [Name], / Dear    | Best regards,        |
| Colleague       | Casual     | Hi [Name],           | Thanks, / Best,      |
| Unknown/cold    | Formal     | Dear [Title/Team],   | Regards,             |

### Step 4 — Quality checklist

Before presenting the draft:
- [ ] Subject line is specific (not "Following up" or "Question")
- [ ] Opening does not start with "I hope this email finds you well"
- [ ] Ask for one thing at a time — avoid multi-request emails
- [ ] No jargon the recipient might not know
- [ ] All names, titles, and facts are placeholders if not provided
- [ ] Under 200 words unless the topic requires more

### Step 5 — Offer variants

Offer a short/long or formal/casual variant if the user might want options.

## Email type templates

See `references/templates.md` for starter templates by email type.

## Common mistakes to avoid

- Burying the ask in the last paragraph
- Vague subject lines ("Hello" / "Hi")
- CC'ing too many people
- Multiple questions in one email
- Passive-aggressive language ("as previously mentioned…")
