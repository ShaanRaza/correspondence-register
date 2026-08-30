# DESIGN.md

Project-specific visual direction. Authoritative. Where Impeccable's default direction conflicts with this file, this file wins (per PRODUCT.md).

Seed key `de50035e` · mode Operate · direction pinned by the author, overriding the roll's assignment.
Written 2026-08-30, before any screen exists, at the author's instruction. Impeccable's normal order writes DESIGN.md at finish, from the built world. **This file is therefore a contract, not a description.** It will be revised once against the first built screen; until that revision it is binding but unproven, and any rule that reality defeats gets rewritten here rather than quietly ignored in code.

---

## The direction contract

**THESIS** — A despatch register is a bound instrument, and its authority comes from three properties software normally throws away: a running serial number that nothing can reorder, ruled columns that never move, and a noting margin that annotates an entry without altering it. This product keeps all three and renders them as contemporary evidentiary software. It refuses the spreadsheet (nothing is a cell you can type into; nothing re-sorts the serial), it refuses the antique (no cream, no treasury ruling, no rubber-stamp texture, no serif nostalgia, no bound-edge skeuomorphism), and it refuses the category default (the slate docket table with a left sidebar, filter chips, and a detail drawer).

**OWN-WORLD** — A cool grey-blue ground, deliberately colder and darker than scanned paper, so a scan always reads as a distinct physical object laid on a desk and never as part of the chrome. Hairline rules at two weights carry all structure; there is no elevation model and nothing floats. Noto Sans and Noto Sans Mono carry every value, Archivo caps carry every column head. Four colours have meaning and no fifth exists. Status owns a full-height gutter column at the register's left edge; scanning that edge tells you the state of the whole package without a chart.

**STORY** — The reader opens a package and sees that nothing is missing, then sees which entries the machine is not confident about, then reads any value back to the page it came from. They leave believing the register is exhaustive and that every number in it is traceable.

**FIRST VIEWPORT** — The register, full width at 1366×768. A title block states the package and its completeness as plain fact. A filter band sits under it, always visible, never a popover. Below that, one continuous ruled register grouped into thread blocks, the status gutter running down the left edge, roughly eighteen rows visible without scrolling.

**FORM** — Despatch Register. My top-ranked grounded candidate of seven; presented as the pick card, chosen by the author over the roll's assignment (Time-Impact Sheet, candidate 7).

**FINISH** — unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance.

### Disciplines carried from declined challengers

These are system rules, not borrowed clothes. One world owns the screen.

- **One struck emphasis** (from Struck Cathode Gauze). Exactly one element on screen carries emphasis at a time. The selected row is full ink; every other row is present but at reduced ink. No second highlight, no hover glow, no active-state accent competing with it.
- **Evidence is never boxed** (from Viewfinder Bracket HUD). A scanned page never sits inside a card. It runs full-bleed in its region with a 1px outline — a document has an edge, that much is honest — and viewer chrome retreats to the region's corners rather than floating over the page.
- **Colour owns regions** (from Studio Dumbar Identity). Where colour appears it fills a full-height band in its own column. Never a dot, pill, chip or badge.
- **One monumental moment** (from Alphabet Storm). One typographic moment per screen is allowed to be large. On the thread screen that is the elapsed-span figure. Nowhere else.

---

## Use scene, and why light

A contracts manager at a Windows desktop, 1366×768, in an office with overhead fluorescent light, and regularly projected onto a meeting-room wall where a dark ground would wash to grey mud. Light mode only. There is no dark mode and no theme toggle; do not build the token indirection for one.

---

## Colour

### Structure

```css
--ground:      #E8EBEE;  /* the desk. app background, gutters, pane behind evidence */
--field:       #FFFFFF;  /* the register field. rows sit on this */
--field-alt:   #F4F6F8;  /* alternate THREAD block, never alternate row */
--rule:        #D3D9DE;  /* 1px column rules, row rules */
--rule-major:  #9AA5AE;  /* 1px block rules, pane divider, the register's spine */
--ink:         #14181C;  /* all primary text */
--ink-2:       #5A646D;  /* labels, units, provenance annotations */
--ink-3:       #707A82;  /* placeholder and disabled ONLY. never carries data */
```

`--ground` is cooler and darker than every scanned letterhead this product will ever show (those run roughly `#F5F1E8` to `#EFE9DC`). That gap is load-bearing: it is what makes the paper look like paper. Do not warm the ground toward the scans to make the screen "harmonious" — that harmony is the failure.

### Meaning

This product has four colours with meaning. **A fifth is a bug.**

```css
--flag-review:   #B4341F;  /* extraction below confidence threshold — needs human review */
--flag-verified: #1F5E3D;  /* extraction checked by a human */
--locate:        #0B5CAD;  /* "this is the value you clicked" — and focus rings */
/* the fourth state is ABSENCE: machine-extracted, unverified, gutter empty */
```

Rules:

- Each of these means exactly one thing, everywhere, forever. `--flag-review` never means "urgent", "overdue", or "delete". `--locate` never means "primary action".
- Colour is never the sole carrier. Every flag colour is accompanied by its word set in Archivo caps in the same cell.
- Absence is a designed state, not an oversight. Most rows in a real package are unverified; if every row carried a colour the gutter would be noise. An empty gutter cell means *machine-extracted, not yet checked* and is documented in the column head.
- No colour anywhere else. Not on buttons, not on links, not on headers, not on hover, not on the elapsed-days figure.

### Contrast

All values verified against `--field` (#FFFFFF):

| Token | Ratio | Use |
|---|---|---|
| `--ink` | 16.9:1 | body, values |
| `--ink-2` | 5.6:1 | labels, provenance |
| `--ink-3` | 4.5:1 | placeholder/disabled only |
| `--flag-review` | 6.0:1 | ✓ |
| `--flag-verified` | 7.4:1 | ✓ |
| `--locate` | 6.7:1 | ✓ |

Every signal must also clear 4.5:1 against `--field-alt`. Re-verify if any value moves.

---

## Type

Three faces, each with a job. Self-host all three; do not rely on a system stack.

```css
--font-text: "Noto Sans", sans-serif;        /* Latin + Devanagari, 400/500/600 */
--font-value: "Noto Sans Mono", monospace;   /* every transcribable value */
--font-head: "Archivo", sans-serif;          /* column heads and section labels, 500/600 */
```

**Why Noto.** It is the face Indian bilingual official documents are actually set in. It covers Devanagari and Latin in one metric-compatible superfamily, which is the only way an English and a Devanagari word can sit on the same line at the same size without one of them looking like a quotation. It ships true tabular figures. It is a workhorse UI face, which is the correct register for an Operate surface.

**Why mono, and the rule that earns it.** Monospace as a costume for "technical" is a cliché. Here it is a semantic rule with a job:

> **If a value could be transcribed into a claim, it is set in `--font-value`.**

That covers letter reference numbers, dates, chainages, clause numbers, elapsed days, page numbers, and serial numbers. It does not cover subjects, party names, or prose. The reader can therefore tell, at a glance and without reading, which things on screen are quotable facts. This directly serves the author's stated disqualifier — *any ambiguity about what a number means*.

### Scale

Dense, tuned for 1366×768.

| Size | Face | Use |
|---|---|---|
| 10px / 600 / caps / +0.08em | Archivo | flag words in the status gutter |
| 11px / 600 / caps / +0.06em | Archivo | column heads, section labels |
| 12px / 400 | Noto Sans Mono | values inside register rows |
| 13px / 400 | Noto Sans | register body text, subjects |
| 13px / 500 | Noto Sans Mono | title-block facts |
| 15px / 600 | Noto Sans | thread subject, pane headings |
| 28px / 500 | Noto Sans Mono | the one monumental moment: the elapsed-span figure on a thread |

No size above 28px exists in this product. There is no display type. There is no hero.

**Kickers and eyebrows are banned.** A small label above a heading never appears. The heading carries itself.

### Setting

- `font-variant-numeric: tabular-nums` on every numeric context. Browser default proportional figures in a register are a defect — columns of dates must align on the digit.
- Body prose measure caps at 72ch. Applies to the subject column and to extracted body text in the viewer.
- Tracking floor −0.02em. Nothing in this product is large enough to need more.
- Headings: more space above than below.

### Bilingual — English and Devanagari

Non-negotiable. These rules exist because this content breaks defaults.

- Devanagari and Latin in the same line get the **same size, same weight, same colour**. Never restyle Devanagari, never transliterate it, never mark it as foreign, never wrap it in a language badge.
- Any region that can contain Devanagari uses `line-height: 1.55` minimum. Devanagari matras and conjuncts exceed the Latin em box; 1.35 clips them.
- **Never** `overflow: hidden` on a single-line box that can contain Devanagari — it shears the matras off the top. Let it wrap.
- **Never** `text-transform: uppercase` on any region that can contain Devanagari. It is a no-op there and produces a mixed-case line. This is why caps are confined to Archivo column heads, which are English-only strings authored by us.
- Do not disable ligatures or contextual alternates via `font-feature-settings`. Devanagari conjuncts are required ligatures, not typographic flourish.
- Test every text component with a mixed line, e.g. `Ref: NHAI/PKG3/2024/117 — भूमि अधिग्रहण के संबंध में`.

---

## Dates, numbers and units

This audience notices a wrong date format before they notice the layout. These formats are part of the design system.

- **Dates:** `DD MMM YYYY` — `14 Jun 2024`. Always. Never numeric-only (`14/06/2024` reads as 6 April to non-Indian arbitration counsel). Never ISO in the UI. Never relative ("3 months ago", "yesterday"). Mono, tabular.
- **Two different dates.** The date on the letterhead and the date of receipt are different facts and are never merged into one column. Label them `DATED` and `RECEIVED`. Where only one is known, the other cell is empty with an em dash in `--ink-3`, never silently backfilled.
- **Chainage:** `Km 12+400`. A range is `Km 12+400 – Km 14+250`, en dash, spaces both sides. Never decimal kilometres.
- **Elapsed days:** `94 d`. Mono.
- **Clause:** as printed in the contract, `Cl. 10.3.2`.
- **Counts:** always with their denominator. `10 of 10`, never `10`.

---

## Latency — visible, exact, not the hero

Per PRODUCT.md as amended: completeness leads, latency is a fact the register carries accurately.

> **An elapsed-days figure never appears without both dated endpoints that produced it.**

In the register it is a column, `94 d`, mono, `--ink`. On a thread it appears in the chronology gutter between two letters, and directly beneath it, at 11px in `--ink-2`, the two endpoints:

```
94 d
AE/PKG3/2024/117 · 12 Mar 2024  →  CTR/PKG3/2024/163 · 14 Jun 2024
```

Latency is never given a colour, never a bar, never a benchmark, never a threshold, never a trend, never a comparison to an average. It is a computed fact with its working shown. The one place it is set large is the thread screen's monumental moment — and even there both endpoints sit under it.

---

## Layout

Two surfaces. Each takes the full width and does its own job densely. Splitting them is not progressive disclosure — they answer different questions.

### Register (jobs 1, 2, 3, 6) — full width, no viewer pane

```
┌─ TITLE BLOCK ─────────────────────────────────── 60px ─┐
│ package identity · period covered · completeness fact  │
├─ FILTER BAND ─────────────────────────────────── 40px ─┤
│ chainage range · date range · direction · counterparty │
├─ COLUMN HEADS ────────────────────────────────── 28px ─┤
├─ REGISTER ──────────────────────────────── fills rest ─┤
```

Columns at 1366 (16px page gutters, 1334 usable):

| Col | Width | Face |
|---|---|---|
| STATUS | 76 | Archivo caps + full-height bar |
| SR | 40 | mono, right |
| DATED | 88 | mono |
| RECEIVED | 88 | mono |
| PARTIES | 84 | Archivo caps, `CTR → AE` |
| LETTER REF | 150 | mono |
| SUBJECT | 440 flex | Noto Sans |
| CHAINAGE | 100 | mono |
| CLAUSE | 90 | mono |
| THREAD | 110 | mono |
| REPLY IN | 68 | mono |

- Row height 32px, growing in 16px steps when the subject wraps. Variable row height is honest; forced single-line truncation is not.
- **Nothing truncates with an ellipsis.** No extracted value is ever cut off. If the register is narrower than its columns, it scrolls horizontally with STATUS, SR, DATED and LETTER REF frozen. Horizontal scroll with frozen keys is what these users already do in Excel, done properly.
- Columns do not reorder and are not user-sortable into a different serial order. Sorting changes the view; the SR column always shows the immutable register serial, so the reader can always see that they are looking at a re-ordered view of a fixed instrument.
- The status gutter is a **column with a head**, not a decorative `border-left` on a row. It contains a 3px full-height bar at its left edge plus the status word. This distinction matters: the coloured-left-border callout is a category cliché; a status column is a register's spine.

### Thread (jobs 3, 4, 5) — chronology and evidence side by side

```
┌─ TITLE BLOCK ──────────────────────────────────────────┐
├──────────────── 55% ──────────┬────────── 45% ─────────┤
│ chronology, letters in serial │ document viewer        │
│ order, elapsed spans in the   │ full-bleed scan        │
│ left gutter between entries   │ corner-pinned chrome   │
└───────────────────────────────┴────────────────────────┘
```

Divider is 1px `--rule-major`, draggable, position persisted.

### Grouping and banding

Threads are blocks in one continuous register, separated by a 1px `--rule-major` block rule and a thread header row. **Band by thread block, not by row.** Zebra-striping alternate rows is a legibility crutch that fights the eye when what matters is which thread a letter belongs to. Alternate thread blocks take `--field-alt`. This is the concrete answer to "easy comparison of different threads": you compare by scanning one instrument, not by opening two.

### Spacing

4px base. `4 · 8 · 12 · 16 · 24 · 32 · 48`. Cell padding 10px horizontal, 7px vertical. Tight groups, generous separation between blocks.

---

## The document viewer — first-class

Priority 5. This is the surface that proves provenance, and it gets treated as the point of the product rather than as a preview.

- The scan runs **full-bleed** in its pane against `--ground`, with a 1px `--rule-major` outline. It is never inside a card, never rounded, never shadowed, never a thumbnail in our furniture.
- Viewer chrome — page `3 of 7`, source filename, zoom, rotate — is pinned to the pane's corners in 11px Archivo caps and 12px mono. It never floats over the centre of the page.
- **Click-through (job 5):** clicking any extracted value in the register or chronology loads the source page and strikes a 2px `--locate` outline around that value's bounding box on the scan. The page is **never dimmed** — dimming evidence to highlight part of it is exactly the wrong instinct for a tribunal-facing tool. The value and its field name are simultaneously echoed in the viewer's corner readout, so the reader can confirm the box is the thing they clicked.
- Zoom is real zoom on the source raster, not a CSS scale of a downsampled preview. A blurry scan at 200% undermines the whole product.
- Every scan carries its provenance in the corner readout: source filename, page number, and ingestion date.

---

## States

- **Empty:** `No documents match these filters.` 13px, `--ink-2`, left-aligned at the first row position inside the field. No illustration, no centred message, no suggested action, no "Clear filters" button styled as a CTA.
- **Loading:** the register renders its rules and column heads immediately and fills rows as data arrives. No skeleton shimmer, no spinner over data, no progress bar. A shimmer is a decorative animation pretending to be information.
- **Error:** names the problem and the recovery, in the product's voice. `Extraction failed on 2 documents. Open triage.` Not "Oops" and not "Something went wrong."
- **Needs review:** not a separate screen. It is the register filtered to `Status = Needs review` — same instrument, same columns, same serial. Job 6 costs one filter, not a new mental model.
- **Hover:** row ground shifts to `--field-alt` (or `--field` inside an alt block). Nothing else. No colour, no shadow, no scale, no icon reveal.
- **Selected:** the struck state. Full-ink row against every other row at reduced ink, per the one-struck-emphasis rule.
- **Disabled:** `--ink-3`, no opacity trick. Opacity on disabled text drops it below contrast floor.

---

## Motion

The author banned unnecessary animation, and this world has almost none. State changes are instant.

- **No** entrance animations, scroll reveals, staggered lists, layout transitions, skeleton shimmer, spinners, bouncing easing, or hover scaling.
- **The one authored moment** is the locate strike: clicking an extracted value settles the viewer on the page and the `--locate` outline appears over 120ms with an exponential ease-out from an already-visible page. It is the only motion that carries meaning — it says *this one, here*.
- The scan raster fades in over 120ms as it decodes, to avoid a hard flash.
- Honour `prefers-reduced-motion: reduce` by removing both, with no loss of information.

---

## Browser surfaces

The parts we do not draw still carry the design. All of these ship themed:

```css
::selection        { background: #CFE0F2; color: var(--ink); }
caret-color:       var(--locate);
:focus-visible     { outline: 2px solid var(--locate); outline-offset: 1px; }
scrollbar-color:   var(--rule-major) var(--ground);   /* square, 12px, no rounding */
```

Tabular figures are on everywhere numbers align. Underline offset on any inline link is set explicitly, never left to default.

---

## Keyboard

These users navigate Excel by keyboard all day and will judge the product by whether it lets them.

- The register is a grid. Arrow keys move the row cursor. `Home`/`End` jump to first/last row. `PageUp`/`PageDown` page.
- `Enter` opens the selected letter's source page in the viewer.
- `/` focuses the first filter field. `Esc` clears focus back to the grid without clearing filter values.
- Every action reachable by mouse is reachable by keyboard. Focus order follows visual order. No focus traps.

---

## Absolute bans

Each of these is disqualifying, drawn from what the author confirmed would make a polished result feel wrong.

**Startup / SaaS aesthetics**
- No cards. No `border-radius` above 2px. No shadows of any kind — this world has no elevation model and nothing floats.
- No chips, pills, badges or tags. Status is a gutter column with a bar and a word.
- No accent-coloured filled buttons. Actions are text with a 1px rule.
- No icon-only controls. Every control carries a word. No emoji, ever. Icons are drawn SVG at one consistent stroke weight, used only where an icon is a diagram (a direction arrow), always paired with its word.
- No gradient text, glass, blur, or coloured halos.

**Analytics-dashboard aesthetics**
- No KPI tiles, stat cards, or hero-metric templates (big number, small label, supporting stats, accent).
- No charts, sparklines, progress rings, donuts, gauges, heatmaps or trend arrows. Completeness is a stated fraction and a scannable gutter.
- No score, grade, index, or "health" metric. The tool reports; it does not appraise.

**Progressive disclosure**
- No drawers, no modals over data, no accordions, no "show more", no collapsed rows, no tooltips carrying data that exists nowhere else.
- A modal is permitted only for a destructive confirmation. Nothing else earns one.
- Any click required to reach data already retrieved is a defect.

**Ambiguity**
- No unlabelled count. No elapsed-days figure without both endpoints. No date in a format readable two ways. No unit-less number.
- No inferred or backfilled value presented at the same weight as an extracted one. Provenance is always visible.

**Nostalgia**
- No cream or parchment ground, no sepia, no rubber-stamp or paper texture, no faux-bound edges, no typewriter face, no serif set to signal officialdom. The register is the *logic*; the rendering is contemporary software.

---

## Open, to be resolved against the first built screen

Stated here rather than hidden, because this file was written before the build.

1. Whether SUBJECT at 440px holds real Indian EPC letter subjects without excessive row growth. If not, the fix is a two-line cap **with the full subject rendered in the thread header**, never an ellipsis.
2. Whether thread-block banding stays legible when a package has forty threads. If it does not, banding gives way to block rules alone.
3. Whether `--ground` at `#E8EBEE` reads as intended when projected. Meeting-room projectors crush low-contrast neutrals; the ground may need to go one step cooler or darker.
4. Whether Noto Sans at 13px holds up on Windows ClearType at 1366×768. Verify on the actual target before this is settled.
