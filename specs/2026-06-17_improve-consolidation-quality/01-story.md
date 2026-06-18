# Improve Consolidation Quality

## User Story
As an AI agent browsing the kapsula memory layer, I want consolidation to produce clean, deduplicated, well-bounded topic cards with meaningful importance scores — and structural library cards (H1/H2/H3) whose previews actually describe their section's content — so that I can decide whether to query a document without reading it first, like a real library card catalog.

## Context

Consolidation currently works (it produces topic cards) but the output has quality issues that undermine its value as a navigation aid. Two layers of cards need attention: **synthesized topic cards** (from consolidation) and **extractive structural cards** (from document chunking).

### Layer 1: Synthesized topic cards — 4 problems

#### Problem A: Duplicate / near-duplicate topics
The clustering runs fresh each time with no memory of existing topic labels. The LLM independently invents similar labels for overlapping card groups. Observed duplicates:

| Collection | Duplicate pair |
|---|---|
| climate | "Global Environmental Monitoring Infrastructure" vs "Global Environmental Monitoring Systems" |
| climate | "Historical Political Strategy" vs "Historical Political Strategy and Deception" |
| climate | "International Frameworks and Governance" vs "International Governance and Policy Frameworks" |
| climate | "Land and Resource Management" vs "Land, Resources, and Energy Security" |
| tech | "Financial & Digital Control Infrastructure" vs "Financial Surveillance & Control Infrastructure" |
| tech | "Marxist-Leninist-Bogdanovist Control Architecture" vs "Marxist/Leninist/Bogdan Control Architecture" |

**Root cause:** `_cluster_topics` has no dedup step. Each run invents labels independently; similar clusters produce near-duplicate cards that both persist (upsert matches on exact title only).

**NOTE on dedup approach:** I initially proposed `difflib.SequenceMatcher` at a 0.85 threshold. **Tested and it fails** — it catches only 1 of 6 real duplicate pairs. Word-level Jaccard catches 4 of 6 but misses 2. The duplicates are *semantically* similar but *lexically* different; string metrics can't bridge that gap. The correct approach is **prompt-based**: pass existing topic labels into the clustering prompt so the LLM reuses them (leveraging semantic understanding instead of brittle string matching).

#### Problem B: "Miscellaneous" bucket overloaded
Every one of 7 collections has a "Miscellaneous" topic. The prompt explicitly invites it: *"If a card doesn't fit any group, put it in a 'Miscellaneous' topic."* The LLM uses this as an escape hatch, and the resulting card mashes unrelated content:

> *"The source presents a 'Health Chronology' that parallels a previous 'Climate Chronology'..."* (in the **philosophical** collection — a health article mis-clustered)

**Root cause:** The prompt defaults to Miscellaneous too eagerly. There's no penalty for using it, and no minimum cluster specificity.

#### Problem C: Importance scores are broken (the scale is meaningless)

**Problem C1: Negative values appear and HIDE the most substantive cards.**

Two cards have negative importance (`-1.00`, `-0.90`):
- "The Meta-Constitution & Rule-Based Enforcement" (-1.00) — this is the **author's central thesis**
- "Critiques of Marxist & Centralized Systems" (-0.90) — core analytical argument

These aren't trivia — they're the most substantive cards. Yet `importance` is consumed in `search.py:64`, which orders topic cards by `importance DESC` and surfaces the top 5 as **search context**. Negative cards sink to the bottom and **never appear**. The most important analytical content is being actively hidden from search.

**Problem C2: The importance prompt is vague and unanchored.**

The current prompt:
```
importance: 0.0-1.0. Use 0.9+ for critical facts, 0.5 for background, 0.3 for trivia.
```

- "critical facts" / "background" / "trivia" are undefined and subjective
- The LLM used negatives as an **escape hatch** for cards that are analytical frameworks (not discrete "facts")
- "The Meta-Constitution" is a framework, not a "fact" — the LLM signaled "doesn't fit the fact-scale" with -1.0
- What's "critical"? To whom? For what purpose? There's no anchor

**Problem C3: The distribution is bimodal and broken — the field barely discriminates.**

Verified against all 58 topic cards:
```
  <0:    2  (the two escape-hatch cards)
  0.3-0.5:  2
  0.5-0.7:  3
  0.7-0.9: 36  (62%)
  0.9-1.0: 15  (26%)
```

88% of cards score 0.7+. If almost everything is "important," the field doesn't help an agent prioritize. The scale collapses to "high for everything except when the LLM is confused."

**Problem C4: What is "important" anyway?**

The corpus is a set of analytical essays by one author making a single interconnected argument. There is no "trivia" and almost no pure "background" — everything connects to the central thesis. The relevant axis for THIS kind of corpus is closer to:

- **Centrality**: how foundational is this concept to the collection's argument? (Would removing it break the narrative?)
- **Information density**: how many specific facts/figures/names/institutions does this card name?
- **Cross-reference count**: how many other cards link to or depend on this one?

Rather than the vague "critical facts / background / trivia" framing, importance should be grounded in something measurable and useful for surfacing context during search.

#### Problem D: Cross-domain leakage
Cards from one domain appear in another's topics (e.g., a Health Chronology article in the philosophical collection). This is an upload-time classification issue, but consolidation faithfully synthesizes whatever is in the collection, amplifying the mistake.

**Root cause:** Filename-based classification at upload time. Out of scope for this spec (see separate reclassification work), but consolidation could flag suspicious clusters.

### Layer 2: Extractive structural cards — they don't fulfill the library card role

This is the bigger issue for agent navigation. The H1/H2/H3 cards are meant to be a **table of contents** — like browsing a library catalog to decide which book to open. Currently they fail at this for two reasons:

#### Problem E: Card previews are dominated by image markdown, not content
Many H2 cards start with Substack image embeds instead of text:

```
[H2] 'It's the central banks, stupid' — "![esc's avatar](https://substackcdn.com/image/fetch/$s_!p68X!,w_36,h_36,c_fill..." (its-the-central-banks-stupid.md)
[H2] Clare Sullivan — "![Clare Sullivan](https://substackcdn.com/image/fetch/$s_!g7VS!,w_1300..." (the-bank-for-international-settlements.md)
[H2] Basel 3.1 — "#### The Weaponisation of Risk ![esc's avatar](https://substackcdn.com/..."
```

An agent browsing these sees a wall of image URLs and learns **nothing** about what the section covers. The first 200 chars (the preview) are wasted on `![...](https://...)` noise. The actual content — what the section argues — is buried past the images.

**Verified:** 2338 of 4427 structural cards (53%) contain image URLs. Cards are created at `tasks.py:915` via `parent_card = LibraryCard(content=section_data["content"])`, where `section_data["content"]` is the raw section text including image embeds.

**IMPORTANT (corrected from earlier draft):** The search index is NOT polluted. The chunker already strips images — 0 of 10398 chunks contain image URLs. The fix is purely about card content/display, not the search pipeline. The earlier draft's "Option B: strip during chunking" is moot.

#### Problem F: Titles alone don't convey enough to decide whether to query
Some titles are opaque without context:

- `[H2] Architecture` — architecture of *what*? (it's SWIFT's message architecture)
- `[H2] Clare Sullivan` — who? (a legal scholar discussing digital identity)
- `[H2] The Apex Relationship` — between whom? (central bank and government)
- `[H1] Corporate Level` / `[H1] Individual Level` — of what system? (CBDC conditionality tiers)

A human librarian's card would say "SWIFT message architecture and how payment instructions flow" — not just "Architecture".

**Root cause:** Titles come verbatim from document headings. The author's headings are often terse or context-dependent. There's no enrichment step that adds a one-line description of what the section is about.

### What "fulfilling the library card role" means

A good library card lets an agent answer, **without reading the document**:
1. **What is this section about?** (topic + scope)
2. **Is it relevant to my query?** (specificity vs. my question)
3. **Where does it sit in the knowledge structure?** (parent/child relationships)

Currently the cards answer (3) well (the H1/H2/H3 hierarchy is preserved), but fail at (1) and (2) because previews are image-noise and titles are too terse.

## Non-Goals
- Fixing upload-time classification (separate work — reclassify the ~9 misfiled articles)
- Changing the document chunking strategy (chunking already strips images for search; this is a card-content concern)
- Re-running consolidation on all collections automatically (the fixes improve future runs; existing cards can be regenerated on demand)
- Generating full section summaries (too expensive per-card; previews + titles are enough)
- Removing importance entirely (it's consumed for search context; fix the semantics instead)
