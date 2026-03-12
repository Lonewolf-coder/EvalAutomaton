# Kore.ai Bot Export — Field Reference Guide

This document maps every field found in Kore.ai XO Platform bot exports (`appDefinition.json`).
It is the authoritative reference for the CBM parser and blueprint generator.
All paths are confirmed from real exports. Trust this over Kore.ai documentation — the actual export format differs from the docs in several critical places.

**Status:** Initial version based on sample export. Will be expanded when real candidate bot exports are added to `tests/bot_exports/`.

---

## Top-Level Keys

| Key | Type | Description |
|-----|------|-------------|
| `botInfo` | object | Bot metadata (name, description, language, version) |
| `dialogs` | array | All dialog task definitions |
| `knowledgeTasks` | array | FAQ / Knowledge tasks |
| `dialogGPTSettings` | array | LLM/DialogGPT configuration (**TRAP: array, not object**) |
| `componentMap` | object | Dialog ID → dialog name mapping |
| `channels` | array | Configured channel types (web, webhook, etc.) |
| `trainingData` | object | NLP training utterances |

### Fields confirmed missing in sample (will be present in real exports):

| Key | Type | Expected Contents |
|-----|------|-------------------|
| `entities` | array | Bot-level entity definitions (custom entity types) |
| `customVariables` | object or array | Custom context variables defined at bot level |
| `nlpSettings` | object | NLP model settings, confidence thresholds |
| `botVersion` | string or object | Bot version metadata |
| `importedPackages` | array | Shared components / packages imported |
| `sharedComponents` | array | Reusable dialog components |
| `dashboards` | array | Custom analytics dashboards |
| `environmentVariables` | object | Environment-specific configuration variables |
| `permissions` | object | Channel and feature permissions |

---

## `botInfo` Object

```json
{
  "botInfo": {
    "name": "Medical Appointment Bot",
    "description": "A chatbot for booking and managing medical appointments",
    "defaultLanguage": "en"
  }
}
```

| Field | Path | Type | Notes |
|-------|------|------|-------|
| Bot name | `botInfo.name` | string | |
| Description | `botInfo.description` | string | |
| Default language | `botInfo.defaultLanguage` | string | e.g. "en" |
| Version | `botInfo.version` | string | May not be present in all exports |

---

## `dialogs` Array

Each element is a dialog task definition.

```json
{
  "dialogs": [
    {
      "name": "Book Appointment",
      "_id": "dialog_book",
      "nodes": [ ... ]
    }
  ]
}
```

| Field | Path | Type | Notes |
|-------|------|------|-------|
| Dialog name | `dialogs[i].name` | string | User-defined name |
| Dialog ID | `dialogs[i]._id` | string | Internal identifier |
| Nodes array | `dialogs[i].nodes` | array | Ordered list of nodes |

### Fields expected in real exports (not in sample):

| Field | Path | Type | Notes |
|-------|------|------|-------|
| Description | `dialogs[i].description` | string | |
| Type | `dialogs[i].type` | string | e.g. "dialog", "action" |
| Enabled | `dialogs[i].enabled` | boolean | |
| Intent utterances | `dialogs[i].intents` | array | Training utterances for this dialog |
| Entry points | `dialogs[i].triggers` | array | What triggers this dialog |

---

## Node Structure

Each node inside a dialog has this base structure:

```json
{
  "nodeId": "node_post",
  "type": "service",
  "name": "CreateBooking",
  "component": { ... },
  "transitions": [{ "target": "node_confirm_msg" }]
}
```

| Field | Path | Type | Notes |
|-------|------|------|-------|
| Node ID | `nodes[i].nodeId` | string | Unique within dialog |
| Node type | `nodes[i].type` | string | See Node Types below |
| Node name | `nodes[i].name` | string | Developer-defined name |
| Component | `nodes[i].component` | object | Type-specific configuration |
| Transitions | `nodes[i].transitions` | array | Outgoing connections |

### Transition structure:

```json
{ "target": "node_next_id" }
```

In real exports, transitions may have additional condition fields:

```json
{ "target": "node_success", "condition": "response.status == 200" }
{ "target": "node_error", "condition": "response.status != 200" }
```

---

## Node Types (Confirmed)

| Type value | Constant | Description |
|-----------|----------|-------------|
| `"message"` | `NODE_TYPE_MESSAGE` | Displays text to the user |
| `"entity"` | `NODE_TYPE_ENTITY` | Collects a specific entity from user |
| `"service"` | `NODE_TYPE_SERVICE` | Makes an API call (GET, POST, PUT, DELETE) |
| `"aiassist"` | `NODE_TYPE_AGENT` | AI Assist / Agent Node (**TRAP: not "agent"**) |
| `"confirmation"` | `NODE_TYPE_CONFIRMATION` | Asks user to confirm before proceeding |
| `"prompt"` | `NODE_TYPE_PROMPT` | Displays a prompt (similar to message) |
| `"script"` | `NODE_TYPE_SCRIPT` | Executes JavaScript code |
| `"logic"` | `NODE_TYPE_LOGIC` | Conditional branching |
| `"form"` | `NODE_TYPE_FORM` | Form-based multi-entity collection |
| `"webhook"` | `NODE_TYPE_WEBHOOK` | Outbound webhook call |

---

## Component Fields by Node Type

### `message` node

```json
"component": {
  "message": "Welcome to the bot! ..."
}
```

| Field | Path | Notes |
|-------|------|-------|
| Message text | `component.message` | May also be at `.text`, `.prompt`, `.msg` |

### `entity` node

```json
"component": {
  "entityType": "phone",
  "message": "Please provide your contact number."
}
```

| Field | Path | Notes |
|-------|------|-------|
| Entity type | `component.entityType` | "string", "phone", "date", "time", "list", etc. |
| Prompt text | `component.message` | May also be at `.prompt`, `.question` |
| Validation rules | `component.validationRules` | Array; format varies by entity type |

**Expected in real exports:**
| Field | Path | Notes |
|-------|------|-------|
| Entity name/key | `component.entityName` or `name` at node level | Variable name stored in context |
| List values | `component.listValues` | For list-type entities |
| Required | `component.required` | boolean |
| Error message | `component.invalidEntityError` | Message shown on invalid input |
| Re-prompt count | `component.maxPromptCount` | How many times bot re-asks |

### `service` node

```json
"component": {
  "serviceType": "rest",
  "method": "POST",
  "url": "https://mockapi.io/appointments"
}
```

| Field | Path | Notes |
|-------|------|-------|
| Service type | `component.serviceType` | "rest", "soap" |
| HTTP method | `component.method` | GET, POST, PUT, PATCH, DELETE |
| URL | `component.url` | May contain `{{context.var}}` placeholders |

**Expected in real exports:**
| Field | Path | Notes |
|-------|------|-------|
| Request headers | `component.headers` | Array of `{key, value}` pairs |
| Request body | `component.requestBody` or `component.payload` | JSON template string |
| Auth config | `component.auth` | Auth type and credentials ref |
| Response path | `component.responsePath` | Where to store response in context |
| Timeout | `component.timeout` | Milliseconds |

### `aiassist` node (AI Assist / Agent Node)

```json
"component": {
  "instructions": "Help the user book an appointment with the provided details.",
  "exitScenario": {
    "enabled": true
  }
}
```

| Field | Path | Notes |
|-------|------|-------|
| System instructions | `component.instructions` | System context / prompt given to LLM |
| Exit scenario | `component.exitScenario` | When AI Assist hands back to dialog |
| Exit enabled | `component.exitScenario.enabled` | boolean |

**Expected in real exports (critical gaps to fill with real data):**
| Field | Path | Notes |
|-------|------|-------|
| Entity collection rules | `component.entityCollection` or `component.entities` | Which entities to collect, in what order |
| Tools / Actions | `component.tools` or `component.actions` | List of callable tools/actions |
| Exit conditions | `component.exitScenario.conditions` | Array of condition objects |
| Exit utterances | `component.exitScenario.utterances` | Trigger phrases for handback |
| Temperature | `component.llmConfig.temperature` | LLM settings override |
| Model override | `component.llmConfig.model` | Per-node model override |
| Max turns | `component.maxTurns` | Maximum AI Assist conversation turns |

### `confirmation` node

```json
"component": {
  "message": "You entered {{contactNumber}}. Is that correct?"
}
```

| Field | Path | Notes |
|-------|------|-------|
| Confirmation prompt | `component.message` | Text shown; may contain `{{variable}}` |

**Expected in real exports:**
| Field | Path | Notes |
|-------|------|-------|
| Yes target | `transitions[0]` where condition = "yes" | |
| No target | `transitions[1]` where condition = "no" | |

### `script` node

**Not in sample — expected fields based on Kore.ai platform:**
| Field | Path | Notes |
|-------|------|-------|
| Script code | `component.script` | JavaScript code string |
| Script name | `name` at node level | Developer-assigned name |

### `logic` node

**Not in sample — expected fields:**
| Field | Path | Notes |
|-------|------|-------|
| Conditions | `component.conditions` | Array of condition objects |
| Branches | `transitions` | Each with a `condition` field |
| Default branch | last `transitions` entry | No condition = default |

---

## `dialogGPTSettings` (TRAP 1)

```json
"dialogGPTSettings": [
  {
    "dialogGPTLLMConfig": {
      "enable": true,
      "model": "gpt-4",
      "temperature": 0.3
    }
  }
]
```

**TRAP:** This is an **array**, not an object. Access via `[0]`.

| Field | Path | Notes |
|-------|------|-------|
| Enabled | `dialogGPTSettings[0].dialogGPTLLMConfig.enable` | boolean |
| Model | `dialogGPTSettings[0].dialogGPTLLMConfig.model` | |
| Temperature | `dialogGPTSettings[0].dialogGPTLLMConfig.temperature` | |

---

## `knowledgeTasks` / FAQs (TRAP 2)

```json
"knowledgeTasks": [
  {
    "name": "Medical FAQ",
    "faqs": {
      "faqs": [
        {
          "question": "What are your working hours?",
          "answer": "...",
          "alternateQuestions": ["When is the clinic open?", ...]
        }
      ]
    }
  }
]
```

**TRAP:** The FAQ array is at `.faqs.faqs` (double-nested), **NOT** `.faqs`.

| Field | Path | Notes |
|-------|------|-------|
| FAQ array | `knowledgeTasks[0].faqs.faqs` | Double-nested |
| Question | `faqs[i].question` | Primary question |
| Answer | `faqs[i].answer` | Ground truth answer |
| Alternate questions | `faqs[i].alternateQuestions` | Array of alternate phrasings |

---

## `channels` Array

```json
"channels": [
  { "type": "web", "enabled": true },
  { "type": "webhook", "enabled": true }
]
```

| Field | Path | Notes |
|-------|------|-------|
| Channel type | `channels[i].type` | "web", "webhook", "slack", "teams", etc. |
| Enabled | `channels[i].enabled` | boolean |

---

## `trainingData` Object

```json
"trainingData": {
  "utterances": [
    { "intent": "Book Appointment", "utterance": "I want to book an appointment" }
  ]
}
```

| Field | Path | Notes |
|-------|------|-------|
| Utterances array | `trainingData.utterances` | |
| Intent name | `trainingData.utterances[i].intent` | Maps to a dialog name |
| Utterance text | `trainingData.utterances[i].utterance` | Training phrase |

---

## `componentMap` Object

Maps dialog IDs to dialog names.

```json
"componentMap": {
  "dialog_welcome": "Welcome",
  "dialog_book": "Book Appointment"
}
```

Used for dialog name resolution when the dialog `_id` is known but the display name needs to be looked up.

---

## Fields NOT Yet Confirmed (Need Real Exports)

The following sections are expected based on Kore.ai platform knowledge but **have not been confirmed from a real candidate export**. These are the highest-priority items to map when real exports are uploaded.

### AI Assist Entity Rules
The most critical gap. Real AI Assist nodes likely have structured entity collection rules rather than just free-form instructions.

**Likely paths to check:**
- `component.entityCollection`
- `component.entities` (array of entity config objects)
- `component.slots`

### Custom Dashboards
```json
"dashboards": [
  {
    "name": "Appointment Dashboard",
    "widgets": [ ... ],
    "dataSource": "...",
    "filters": [ ... ]
  }
]
```

### Custom Variables
```json
"customVariables": [
  { "name": "appointmentId", "type": "string", "scope": "session" }
]
```

### Bot-Level Entity Definitions
```json
"entities": [
  { "name": "doctorType", "type": "list", "values": ["GP", "Specialist"] }
]
```

### Version / Metadata
```json
"botVersion": "2.1.0",
"lastModified": "2026-01-15T10:00:00Z",
"createdBy": "admin@company.com"
```

### Imported Packages / Shared Components
```json
"importedPackages": [
  { "packageId": "pkg_123", "name": "Common Utilities", "version": "1.0" }
]
```

---

## Parser Traps Summary

See `docs/parser_traps.md` for the full list.

| # | Trap | Description |
|---|------|-------------|
| 1 | dialogGPTSettings is an array | Access `[0].dialogGPTLLMConfig.enable`, not `.dialogGPTLLMConfig.enable` |
| 2 | FAQ double-nesting | Access `knowledgeTasks[0].faqs.faqs`, not `knowledgeTasks[0].faqs` |
| 3 | AI Assist node type | Type value is `"aiassist"`, not `"agent"` or `"agentNode"` |

---

*Last updated: Phase 1 initial analysis. Update this document when real bot exports are analyzed.*
