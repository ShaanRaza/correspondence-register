# PRODUCT.md

## What this is

A per-package correspondence register for Indian national-highway EPC contractors. It ingests every letter between the contractor, the Authority Engineer and the Project Director, extracts reference numbers, dates, chainages and contract clauses, links letters into threads by citation, and reconstructs the dated chronology of a dispute on demand.

It is not a chatbot over documents. It is a claim-ready evidentiary register with retrieval on top. The output is used to argue extension-of-time claims in front of arbitral tribunals.

This build is a pre-sales demo running on 10 documents: one contractor, one package, one deep thread — a single dispute chronology carried end to end.

## Product lane

Internal operational tool. Case management. Not a SaaS product page, not a consumer app, not a dashboard.

The nearest honest comparisons are legal docket systems, court e-filing portals, and document review platforms. Not Linear, not Notion, not an analytics dashboard.

## Audience

Contracts managers, planning managers and claims consultants at Indian highway EPC firms. Secondarily arbitration counsel.

- Typically 40–60, desktop Windows, often 1366×768
- Read dense contractual documents all day; high tolerance for information density, zero tolerance for ambiguity about what a number means
- Today they keep this by hand in an Excel correspondence register — letter no., date, subject, reply-to, typed and maintained manually. That file is the incumbent this replaces, and its column grammar is familiar ground.
- Not design-literate, but extremely detail-literate — they will notice a wrong date format before they notice the layout
- They are evaluating whether this system could be trusted in front of a tribunal. Every visual decision either supports or undermines that.

## Voice

Factual and terse. Labels, not sentences. Never celebratory, never explanatory-friendly.

- "94 days" — not "Wow, 94 days!" and not "It took 94 days for a response"
- "3 documents need review" — not "Oops! We had trouble with a few files"
- No empty states with illustrations and encouraging copy. An empty register says "No documents match these filters."
- No onboarding tone. Assume the reader knows what a chainage is.

## What makes a polished result feel wrong

Confirmed by the author. These are disqualifying, not preferences.

- **Looking like a startup product.** Rounded cards, generous whitespace, a friendly accent, soft shadows. Reads as unserious beside a scanned Authority Engineer letter.
- **Looking like an analytics dashboard.** KPI tiles, charts, sparklines, any "health" metric. Implies interpretation the tool has no standing to offer before a tribunal.
- **Any ambiguity about what a number means.** No unlabelled count. No elapsed-days figure without its two endpoints. No date whose format could be read two ways.
- **Hiding density behind progressive disclosure.** No collapsed rows, no "show more", no drawers over the data. Everything on screen at 1366×768. Clicks to reach data already retrieved are a defect.

## Primary jobs

1. See every letter on a package in one filterable table
2. Filter by chainage range, date range, direction, counterparty
3. Open one thread and read its chronology with elapsed days between letters
4. See response latency per thread — the number an EOT claim is built from
5. Click any extracted value and land on the original page with it highlighted
6. Triage documents that failed extraction
7. Generate an annexure bundle

**Completeness is the reason the product exists. Job 1 — every letter on the package, nothing missed — and the visible quality of extraction are the most prominent things in the application.**

Job 4 (response latency) stays exact, computed and always available: a column in the register, a figure on every thread, never typed by hand. It is not the hero. A latency figure never appears without both dated endpoints that produced it.

*(Amended 2026-08-30. The brief originally read "Job 4 is the reason the product exists." Superseded on the author's instruction: latency is not the headline; completeness and extraction quality are.)*

## Design system

All frontend work goes through Impeccable. It is installed in this repo and its rules are authoritative for typography, colour, spacing, density and motion.

- `DESIGN.md` in this repo holds the project-specific direction. Read it before writing any component.
- Do not introduce a second design skill. Taste Skill, shadcn presets and any other component or design system stay out — they occupy the same slot and will conflict.
- When Impeccable's default direction conflicts with `DESIGN.md`, `DESIGN.md` wins. It is tuned for a data-dense evidentiary tool; Impeccable's defaults lean toward product and marketing surfaces.
- Run `/impeccable audit` before showing me any screen.

## Constraints

- Light mode only. No dark mode. This is shown in meeting rooms and often projected.
- Desktop only. No mobile, no responsive breakpoints below 1280px.
- Bilingual content: English and Devanagari appear in the same document body, sometimes the same line.
- Scanned page images sit next to UI chrome constantly — the interface must not clash with off-white paper.
