# Implementation Guide — YAML LLM Output Format

---

### Step 1: Create `_parse_yaml_safely` utility
**File:** `kapsula/core/application/use_cases/planning/query_planner.py` (alongside `_parse_json_safely`)

Mirror the structure of `_parse_json_safely` but use `yaml.safe_load`:

```python
import yaml

def _parse_yaml_safely(text: str) -> dict:
    """Robust YAML parsing from LLM output — handles code fences and prose."""
    if not text:
        return {}
    s = text.strip()

    # Strip code fences
    m = re.search(r"```(?:yaml)?\s*([\s\S]*?)\s*```", s, re.IGNORECASE)
    if m:
        s = m.group(1).strip()
    else:
        s = s.removeprefix("```yaml").removeprefix("```").removesuffix("```").strip()

    # Normalize smart quotes
    s = s.replace("\u201c", '"').replace("\u201d", '"')
    s = s.replace("\u2018", "'").replace("\u2019", "'")

    try:
        result = yaml.safe_load(s)
        if isinstance(result, dict):
            return result
        return {}
    except yaml.YAMLError:
        logger.warning("Failed to parse YAML from LLM output (length=%d): %.200s", len(s), s)
        return {}
```

**Design note:** Unlike JSON, YAML doesn't need brace-finding or trailing-comma fixing — those failure classes don't exist in YAML. The function is simpler than its JSON counterpart.

**Verify:** Run the scenario tests (code fences, smart quotes, bare YAML, garbage).

---

### Step 2: Rewrite the four LLM prompts to request YAML
**File:** `consolidation_runner.py` and `query_planning_prompts.py`

For each prompt, replace the JSON instruction + example with YAML equivalents.

**Example — `_TOPIC_CLUSTERING_SYSTEM` (before):**
```
Output ONLY valid JSON with this structure:
{
  "topics": [
    {
      "label": "Topic Name",
      "card_ids": [1, 2, 3],
      "rationale": "These cards all discuss..."
    }
  ]
}
```

**After:**
```
Output ONLY valid YAML with this structure:
topics:
  - label: "Topic Name"
    card_ids: [1, 2, 3]
    rationale: "These cards all discuss..."
```

Apply the same transformation to:
- `_TOPIC_CARD_SYSTEM` (summary, key_facts, importance, contradictions)
- `_GAP_CARD_SYSTEM` (gaps with topic, search_count, suggestion)
- `SYSTEM_PROMPT_DOCUMENT` in `query_planning_prompts.py`

**Verify:** Each prompt contains "YAML" and a YAML example; no "JSON" remains.

---

### Step 3: Replace `_parse_json_safely` calls with `_parse_yaml_safely`
**Files:** `consolidation_runner.py`, `query_planner.py`

| File | Method | Change |
|---|---|---|
| `consolidation_runner.py` | `_cluster_topics` | `_parse_json_safely(response)` → `_parse_yaml_safely(response)` |
| `consolidation_runner.py` | `_generate_topic_card` | same |
| `consolidation_runner.py` | `_generate_gap_cards` | same |
| `query_planner.py` | `plan_document_search` | same |

**Keep `_parse_json_safely`** — don't delete it. It remains useful for any future JSON inputs or as a fallback. Both utilities live in `query_planner.py`.

**Verify:** `grep -rn "_parse_json_safely" kapsula/` — should show only the definition and no calls from the four converted methods.

---

### Step 4: Declare `pyyaml` in requirements.txt
**File:** `requirements.txt`

Add an explicit dependency:
```
pyyaml>=6.0
```

Currently `pyyaml` (v6.0.3) is installed transitively. Making it explicit prevents breakage if the transitive chain changes.

**Verify:** Fresh `pip install -r requirements.txt` in a clean venv, then `python -c "import yaml"` succeeds.

---

### Step 5: Test consolidation end-to-end
**Verify:** Run `run_collection_maintenance` on a collection (e.g., technology-surveillance). Confirm:
- Topic cards are created (not zero)
- `get_consolidation_status` shows non-zero topic count
- No YAML parse warnings in logs

**Migration note:** Existing topic cards created from JSON output remain valid — they're stored as text content, not parsed on read. Only future consolidation runs use YAML.
