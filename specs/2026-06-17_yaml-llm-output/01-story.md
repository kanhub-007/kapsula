# YAML LLM Output Format

## User Story
As a kapsula maintainer, I want consolidation LLM prompts to request YAML instead of JSON, so that the most common LLM output malformations (trailing commas, unclosed braces, brace mismatches) are eliminated and parse reliability improves.

## Context

Kapsula's consolidation engine (`ConsolidationRunner`) and query planner (`QueryPlanner`) ask the LLM to output structured data. Currently they request **JSON**. LLMs frequently produce malformed JSON:

- **Trailing commas** — `{"a": 1,}` (JSON invalid, YAML valid)
- **Unclosed braces** — `{"topics": [{"label": "X"` (JSON invalid)
- **Brace mismatches** — wrong nesting depth
- **Extra text after closing brace** — prose wrapping the JSON

`_parse_json_safely` (already hardened with trailing-comma fix, smart-quote replacement, and `raw_decode` fallback) handles most of these gracefully — but it's defensive code patching over a format mismatch. YAML eliminates several of these failure classes at the source.

### Why YAML is better for LLM output (honestly assessed)

**Real benefits:**
- **No trailing comma issues** — YAML doesn't use commas as structural delimiters in block style
- **No brace/bracket matching** — indentation-based scoping means a missing `}` or `]` can't break parsing
- **More token-efficient** — fewer structural characters (`{`, `}`, `[`, `]`, `"`) for the same data
- **Human-readable** — easier to debug in logs

**NOT a benefit (corrected from earlier analysis):**
- ❌ *"YAML allows partial truncation recovery"* — **FALSE**. Tested all three truncation scenarios (mid-array, mid-string, mid-rationale); `yaml.safe_load` fails just as hard as `json.loads`. Truncation must be solved by `max_tokens` limits and batching (see `fix-consolidation-resilience` spec), not format choice.

### Where YAML output is used today

| Component | Prompt | Current format | Parses with |
|---|---|---|---|
| `ConsolidationRunner._cluster_topics` | Topic clustering | JSON | `_parse_json_safely` |
| `ConsolidationRunner._generate_topic_card` | Topic synthesis | JSON | `_parse_json_safely` |
| `ConsolidationRunner._generate_gap_cards` | Gap analysis | JSON | `_parse_json_safely` |
| `QueryPlanner` | Search planning | JSON | `_parse_json_safely` |

All four should switch to YAML together for consistency.

## Non-Goals
- Fixing truncation (that's the `fix-consolidation-resilience` spec — solved via `max_tokens` + batching)
- Removing `_parse_json_safely` (keep it as a fallback for any remaining JSON prompts or external inputs)
- Changing the consolidation logic itself (same prompts, same topics, just different output format)
- Supporting YAML input from users (only LLM output format changes)
