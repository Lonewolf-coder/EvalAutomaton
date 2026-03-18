# Kore.ai Bot Export — Parser Traps

All 12 traps confirmed from real candidate bot exports (9 bots: 2 Medical, 7 Travel).
Each entry shows the wrong assumption, the correct approach, and verified evidence.

---

## Trap 1 — `dialogGPTSettings` is an ARRAY (known)

**Wrong:**
```python
settings = export_data.get("dialogGPTSettings", {})
enabled = settings.get("dialogGPTLLMConfig", {}).get("enable")
```

**Correct:**
```python
settings = export_data.get("dialogGPTSettings", [])
if isinstance(settings, list) and settings:
    enabled = settings[0].get("dialogGPTLLMConfig", {}).get("enable")
```

**Evidence:** `"dialogGPTSettings": [{...}]` — always a list with one item in all 9 exports.

---

## Trap 2 — FAQ array is double-nested at `.faqs.faqs` (known)

**Wrong:**
```python
faq_array = knowledge_task.get("faqs", [])
```

**Correct:**
```python
faqs_container = knowledge_task.get("faqs", {})
faq_array = faqs_container.get("faqs", []) if isinstance(faqs_container, dict) else []
```

**Evidence:**
```json
{
  "knowledgeTasks": [
    {
      "faqs": {
        "faqs": [...],   ← actual FAQ array (same key name, nested inside)
        "nodes": [...],
        "synonyms": {...}
      }
    }
  ]
}
```

---

## Trap 3 — AI Assist node type is `"aiassist"` (known)

**Wrong:** Looking for type `"agent"`, `"agentNode"`, or `"ai_assist"`

**Correct:**
```python
if node.get("type") == "aiassist":
    ...
```

**Evidence:** All AI Assist nodes across all 9 exports use exactly `"aiassist"`.

---

## Trap 4 — No `botInfo` key exists

**Wrong:**
```python
bot_info = export_data.get("botInfo", {})
bot_name = bot_info.get("name", "")
```
This always returns `""` — `botInfo` key does not exist in any export.

**Correct:**
```python
bot_name = export_data.get("localeData", {}).get("en", {}).get("name", "")
```

**Fallback** (from `config.json` companion file):
```python
import json
config = json.load(open("config.json"))
bot_name = config.get("name", "")
```

**Evidence:** 9/9 exports: no `botInfo` key. Bot name confirmed at `localeData.en.name` in all exports.

---

## Trap 5 — Dialog `name` field doesn't exist

**Wrong:**
```python
dialog_name = raw_dialog.get("name", "")
```
This always returns `""` — dialogs have no `name` key at the top level.

**Correct:**
```python
dialog_name = (
    raw_dialog.get("localeData", {})
    .get("en", {})
    .get("name", raw_dialog.get("lname", ""))
)
```

**Evidence:**
```json
{
  "lname": "modify appointment details",
  "localeData": {
    "en": {
      "name": "Modify Appointment Details",
      "shortDesc": "When User needs to modify specific appointment"
    }
  }
}
```
Dialog object has `lname` (lowercase) and `localeData.en.name` (display name). No `name` key.

---

## Trap 6 — Dialog nodes are reference stubs only (no content)

**Wrong:**
```python
for node in dialog["nodes"]:
    name = node.get("name", "")          # always ""
    component = node.get("component", {}) # always {}
    message = node.get("message", "")    # always ""
```

**Correct:**
```python
# Build lookup once:
comp_lookup = {c["_id"]: c for c in export_data["dialogComponents"]}

# Then for each node:
for node in dialog["nodes"]:
    comp = comp_lookup.get(node.get("componentId"), {})
    name = comp.get("name", "")
    # all node content is in comp
```

**Evidence:** Every dialog node has ONLY these fields:
```
type, componentId, nodeId, transitions, vNameSpace, preConditions, useTaskLevelNs, nodeOptions
```
No `name`, no `component`, no content fields. All content is in `dialogComponents` keyed by `_id`.

---

## Trap 7 — No `componentMap` key; use `dialogComponents` array

**Wrong:**
```python
component_map = export_data.get("componentMap", {})
```
Always returns `{}` — key doesn't exist.

**Correct:**
```python
comp_lookup = {c["_id"]: c for c in export_data.get("dialogComponents", [])}
```

**Evidence:** 9/9 exports: no `componentMap` key. `dialogComponents` array contains all node content with `_id` as the key.

---

## Trap 8 — Message text and script content are URL-encoded

**Wrong:**
```python
text = component["message"][0]["localeData"]["en"]["text"]
# Returns: "Welcome%20to%20the%20bot%21%20How%20can%20I%20help%3F"
```

**Correct:**
```python
import urllib.parse

raw_text = component["message"][0]["localeData"]["en"]["text"]
text = urllib.parse.unquote(raw_text)
# Returns: "Welcome to the bot! How can I help?"
```

**Also applies to:**
- `component["script"]` — JavaScript code in script nodes
- `component["errorMessage"][0]["localeData"]["en"]["text"]`
- `component["message"][0]["localeData"]["en"]["text"]` on all node types

**Evidence:** Raw text: `"Welcome%20to%20the%20bot%21"`. After unquote: `"Welcome to the bot!"`.
Script raw: `"var%20l%3D%20koreUtil._%3B%0Avar%20refNumber%20%3D%20l.random(100000%2C999999)%3B"`
Script decoded: `"var l= koreUtil._;\nvar refNumber = l.random(100000,999999);"`

---

## Trap 9 — FAQ `answer` is a list, not a string

**Wrong:**
```python
answer = faq.get("answer", "")
# Returns: [{"text": "Bring a valid ID...", "type": "basic", "channel": "default"}]
# Causes: downstream code expecting string gets a list
```

**Correct:**
```python
raw_answer = faq.get("answer", "")
if isinstance(raw_answer, list) and raw_answer:
    answer = raw_answer[0].get("text", "")
else:
    answer = str(raw_answer)
```

**Evidence:**
```json
{
  "answer": [
    {
      "text": "Bring a valid ID, insurance card, previous medical records...",
      "type": "basic",
      "channel": "default"
    }
  ]
}
```
Answer is always a list of channel-specific response objects. Access `[0].text` for the default response.

---

## Trap 10 — Form component links to `forms` array via `resourceId`, not component `refId`

**Wrong:**
```python
# Assuming form component's refId matches forms array
forms_by_ref = {f["refId"]: f for f in export_data.get("forms", [])}
form_def = forms_by_ref.get(component["refId"])  # always None
```

**Wrong (also):**
```python
form_id = component.get("formId")  # always None — field doesn't exist
```

**Correct:**
```python
forms_by_ref = {f["refId"]: f for f in export_data.get("forms", [])}
form_def = forms_by_ref.get(component.get("resourceId"))
```

**Evidence:**
- Form component `_id`: `"dc-2ac9a974-ca2e-5c4c-828f-2e5c7e1e1976"`
- Form component `refId`: `"0dd52f37-ea05-5a32-bc46-b2e1bede7608"`
- Form component `resourceId`: `"d3e64963-1e8f-5ddd-8c58-044ec1427261"` ← **this one**
- `forms[0].refId`: `"d3e64963-1e8f-5ddd-8c58-044ec1427261"` ← matches `resourceId`

`formId` field does NOT exist in any of the 9 exports.

---

## Trap 11 — Logic node branch conditions are on the NODE's `transitions`, not the component

**Wrong:**
```python
comp = comp_lookup[node["componentId"]]
conditions = comp.get("conditions", [])  # always []
branches = comp.get("branches", [])      # always []
```

Logic components are completely bare — they store no condition data.

**Correct:**
```python
# Conditions are on the DIALOG NODE's transitions array
conditions = [
    t for t in node.get("transitions", [])
    if "if" in t
]
default_target = next(
    (t.get("default") for t in node.get("transitions", []) if "default" in t),
    None
)
```

**Evidence:**
```json
{
  "type": "logic",
  "componentId": "dc-8b248710-...",
  "transitions": [
    {
      "if": {"context": "context.dialogGPTInfo.winning_intents[0]", "op": "eq", "value": "Repeat"},
      "then": "nd-gai-abc123"
    },
    {"default": "nd-gai-xyz789"}
  ]
}
```
Logic component when resolved: `{"_id": "dc-8b248710-...", "name": "LogicNode", "type": "logic", "localeData": {...}}`
— no conditions, no branches.

---

## Trap 12 — AI Assist `systemContext` has two inconsistent key names

**Wrong:**
```python
ai = comp["generativeAI"]["dynamicEntityConfig"]
context = ai["systemContext"]  # KeyError on some bots
# OR
context = ai["system_context"]  # KeyError on other bots
```

**Correct:**
```python
ai = comp.get("generativeAI", {}).get("dynamicEntityConfig", {})
context = ai.get("systemContext") or ai.get("system_context") or ""
```

**Evidence across 9 exports:**

| Bot | Key used |
|-----|----------|
| Medi_Assistant V1 | `systemContext` |
| Medi_Assistant V2 | `systemContext` |
| Travel AI Agent (11) | `system_context` |
| Travel AI Agent32 | `systemContext` |
| Travel Agent AI | **both** `systemContext` AND `system_context` |
| Travel Ai Agent N Basic | `systemContext` |

No single key is consistent across all bots. Always try both.
