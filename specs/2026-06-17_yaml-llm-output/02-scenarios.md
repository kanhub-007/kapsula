# Scenarios — YAML LLM Output Format

---

### Scenario: Topic clustering prompt requests YAML output
**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given the `_TOPIC_CLUSTERING_SYSTEM` prompt
  When  the consolidation runner builds the LLM message
  Then  the prompt instructs the LLM to output YAML
  And   shows a YAML example (not JSON)
  And   the response is parsed with `yaml.safe_load` (via `_parse_yaml_safely`)

**Verify:**
```python
assert "YAML" in _TOPIC_CLUSTERING_SYSTEM
assert "topics:" in _TOPIC_CLUSTERING_SYSTEM
# Response parsed as YAML
response = chat_client.send(messages=[...])
result = _parse_yaml_safely(response)
assert "topics" in result
```

---

### Scenario: `_parse_yaml_safely` handles code fences and smart quotes
**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given an LLM response wrapped in ` ```yaml ... ``` ` fences
  Or    a response with smart quotes (\u201c \u201d)
  When  `_parse_yaml_safely` processes it
  Then  the fences are stripped and quotes normalized before parsing
  And   valid YAML is returned as a dict

**Verify:**
```python
# Code fence
fenced = "```yaml\ntopics:\n  - label: A\n    card_ids: [1]\n```"
assert _parse_yaml_safely(fenced) == {"topics": [{"label": "A", "card_ids": [1]}]}

# Smart quotes
smart = 'topics:\n  - label: \u201cA\u201d\n    card_ids: [1]'
result = _parse_yaml_safely(smart)
assert result["topics"][0]["label"] == '"A"'  # normalized to straight quotes

# Bare YAML (no fence)
bare = "topics:\n  - label: A\n    card_ids: [1]"
assert _parse_yaml_safely(bare)["topics"][0]["label"] == "A"
```

---

### Scenario: Malformed YAML returns empty dict (no crash)
**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given completely unparseable LLM output (e.g., prose, garbage)
  When  `_parse_yaml_safely` processes it
  Then  it returns `{}` and logs a warning
  And   no exception propagates to the caller

**Verify:**
```python
assert _parse_yaml_safely("this is not yaml at all") == {}
assert _parse_yaml_safely("") == {}
assert _parse_yaml_safely(None) == {}
```

---

### Scenario: All four LLM-calling components use YAML
**Priority:** Must
**Slice:** 1

**Gherkin:**
  Given the consolidation runner and query planner
  When  any of them calls the LLM
  Then  the system prompt requests YAML
  And   the response is parsed with `_parse_yaml_safely`

**Input table:**
| Component | Prompt constant | Method |
|---|---|---|
| ConsolidationRunner | `_TOPIC_CLUSTERING_SYSTEM` | `_cluster_topics` |
| ConsolidationRunner | `_TOPIC_CARD_SYSTEM` | `_generate_topic_card` |
| ConsolidationRunner | `_GAP_CARD_SYSTEM` | `_generate_gap_cards` |
| QueryPlanner | `SYSTEM_PROMPT_DOCUMENT` | `plan_document_search` |

**Verify:**
```python
for prompt in [_TOPIC_CLUSTERING_SYSTEM, _TOPIC_CARD_SYSTEM, _GAP_CARD_SYSTEM, SYSTEM_PROMPT_DOCUMENT]:
    assert "YAML" in prompt, f"{prompt[:40]}... does not request YAML"
```

---

### Scenario: pyyaml is an explicit dependency
**Priority:** Should
**Slice:** 1

**Gherkin:**
  Given the project relies on `yaml.safe_load`
  When  a fresh install runs
  Then  `pyyaml` is listed in `requirements.txt`
  And   `import yaml` succeeds without other packages installed

**Verify:**
```bash
grep -i pyyaml requirements.txt  # should be present
pip install -r requirements.txt
python -c "import yaml"  # succeeds
```

**Note:** Currently `pyyaml` (v6.0.3) is installed transitively but not declared in `requirements.txt`. Making it explicit prevents breakage if the transitive dependency changes.
