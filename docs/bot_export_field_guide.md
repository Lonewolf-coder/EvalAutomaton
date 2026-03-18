# Kore.ai Bot Export — Field Reference Guide

This document maps every field confirmed in real Kore.ai XO Platform bot exports (`appDefinition.json`).
All paths are verified from 9 real bot exports (2 Medical, 7 Travel). Trust this over Kore.ai documentation.

**Last updated:** Phase 1 — confirmed from real candidate exports in `tests/bot_exports/`.

---

## Critical Architecture: How Exports Are Structured

A Kore.ai export is **NOT** a simple nested JSON. There are two layers:

1. **`dialogs` array** — each dialog contains `nodes[]`, but nodes are **reference stubs only** (no content)
2. **`dialogComponents` array** — contains all actual node content, keyed by `_id`

Every node in a dialog has `type` and `componentId`. The parser **must** look up `componentId` in `dialogComponents` to get names, messages, service URLs, entity config, etc.

```python
# Build lookup once per parse
comp_lookup = {c['_id']: c for c in export_data['dialogComponents']}

# Resolve node content
for node in dialog['nodes']:
    component = comp_lookup[node['componentId']]  # actual content here
```

---

## Top-Level Keys (Confirmed Present in All Exports)

| Key | Type | Description |
|-----|------|-------------|
| `_id` | string | Bot ID (e.g. `"st-553e16f2-..."`) |
| `refId` | string | Reference ID |
| `type` | string | Always `"default"` |
| `appType` | string | Always `"unified"` |
| `purpose` | string | Always `"customer"` |
| `defaultLanguage` | string | e.g. `"en"` |
| `supportedLanguages` | array | e.g. `["en"]` or `["en", "es"]` |
| `localeData` | object | Multi-language data including bot name — **bot name lives here** |
| `environmentVersionInfo` | string | Bot version e.g. `"9.1.7"` |
| `isSmartAssist` | boolean | |
| `isAgentAssist` | boolean | |
| `isNLEnabled` | boolean | |
| `dialogs` | array | Dialog definitions (node stubs only) |
| `dialogComponents` | array | All node content (resolved via componentId) |
| `knowledgeTasks` | array | FAQ / Knowledge tasks |
| `dialogGPTSettings` | array | LLM/DialogGPT config (**TRAP: array, not object**) |
| `llmConfiguration` | array | LLM feature configuration |
| `customDashboards` | array | Custom analytics dashboards (may be empty) |
| `contentVariables` | array | Content/environment variables |
| `channels` | array | Configured channels (always empty in these exports) |
| `forms` | array | Form definitions (linked from form components via `resourceId`) |
| `botEvents` | object | Bot event handlers (14 event types) |
| `patterns` | array | NLP patterns |
| `advancedNLSettings` | array | NLP configuration |
| `mlParams` | array | ML training parameters |
| `smallTalk` | array | SmallTalk config |
| `strict_pii` | boolean | PII protection mode |
| `interruptsEnabled` | boolean | |
| `sessionInactiveTime` | number | Session timeout in ms (e.g. 900000) |

**NOT present in any export:**
- `botInfo` — **does not exist**. Bot name is at `localeData.en.name`
- `componentMap` — **does not exist**. Use `dialogComponents` array instead
- `trainingData` — not a top-level key. Training data is in `mlParams`

---

## Bot Metadata

Bot name and description are **NOT** in a `botInfo` object. They are in `localeData`.

```json
{
  "localeData": {
    "en": {
      "name": "Medi_Assistant",
      "description": "...",
      "invocationNames": [],
      "nlpVersion": "..."
    }
  },
  "environmentVersionInfo": "9.1.7",
  "supportedLanguages": ["en"],
  "defaultLanguage": "en"
}
```

| Field | Path | Notes |
|-------|------|-------|
| Bot name | `localeData.en.name` | Primary bot name |
| Bot description | `localeData.en.description` | May be empty |
| Bot version | `environmentVersionInfo` | String, e.g. `"9.1.7"` |
| Languages | `supportedLanguages` | List of language codes |
| Default language | `defaultLanguage` | e.g. `"en"` |

**Also available from `config.json`** (companion file in the export folder):
```json
{ "name": "Medi_Assistant", "envVariables": [...] }
```

---

## `dialogs` Array

Each dialog is a flow with ordered nodes. **Node content is NOT stored here** — only references.

```json
{
  "dialogs": [
    {
      "_id": "dg-0d026223-55a1-5fe0-92e4-78a67bf8af4b",
      "refId": "...",
      "lname": "modify appointment details",
      "localeData": {
        "en": {
          "name": "Modify Appointment Details",
          "shortDesc": "When User needs to modify specific appointment"
        }
      },
      "nodes": [ ... reference stubs ... ],
      "isHidden": false,
      "isFollowUp": false,
      "isAbandonment": false,
      "contextLifeTime": {"options": "close"},
      "interruptOptions": {"priority": "bot"},
      "groups": [],
      "sequences": []
    }
  ]
}
```

| Field | Path | Notes |
|-------|------|-------|
| Dialog ID | `dialog._id` | Internal ID (e.g. `"dg-..."`) |
| Dialog name (display) | `dialog.localeData.en.name` | **Use this** — NOT `dialog.name` |
| Dialog name (lowercase) | `dialog.lname` | Lowercase internal name |
| Short description | `dialog.localeData.en.shortDesc` | |
| Nodes (reference stubs) | `dialog.nodes` | Each has `type` + `componentId` only |
| Hidden | `dialog.isHidden` | boolean |
| Follow-up dialog | `dialog.isFollowUp` | boolean |
| Abandonment handler | `dialog.isAbandonment` | boolean |

---

## Node Reference Structure (in `dialogs[i].nodes`)

Every node in a dialog is a **reference stub only**. All content is in `dialogComponents`.

```json
{
  "type": "service",
  "componentId": "dc-0eb2824d-9b31-5b7e-a461-d73d9806a2d1",
  "nodeId": "nd-srv-1382308b-0cef-49a1-a6f6-ac502c9a9fd4",
  "transitions": [
    {
      "default": "nd-scr-0ac319d3-c233-4eb1-8f93-b7666f833827",
      "metadata": {"color": "#D0D5DD", "connId": "..."}
    }
  ],
  "vNameSpace": [],
  "preConditions": [],
  "useTaskLevelNs": true,
  "nodeOptions": { ... }
}
```

| Field | Path | Notes |
|-------|------|-------|
| Node type | `node.type` | Same value as the resolved component's `type` |
| Component ID | `node.componentId` | Key to look up in `dialogComponents` |
| Node ID | `node.nodeId` | Unique within dialog (e.g. `"nd-srv-..."`) |
| Transitions | `node.transitions` | Array of outgoing connections (see Transitions) |
| Node options | `node.nodeOptions` | Canvas/runtime config |

---

## Transitions Structure

Four transition variants found across all exports:

### 1. Simple default
```json
{ "default": "nd-msg-abc123", "metadata": {"color": "#D0D5DD", "connId": "..."} }
```

### 2. Entity value condition
```json
{
  "if": {"field": "nd-ent-xyz789", "op": "eq", "value": "ChangeTheDate"},
  "then": "nd-ent-new_date",
  "metadata": {...}
}
```

### 3. Context path condition (logic nodes)
```json
{
  "if": {"context": "context.dialogGPTInfo.winning_intents[0]", "op": "eq", "value": "Repeat"},
  "then": "nd-gai-abc123",
  "metadata": {...}
}
```

### 4. DialogAct condition (yes/no)
```json
{ "if": {"dialogAct": "yes"}, "then": "nd-srv-abc123", "metadata": {...} }
{ "if": {"dialogAct": "no"}, "then": "nd-scr-abc123", "metadata": {...} }
```

**Note:** Logic node branch conditions are on the **node's** `transitions` array — NOT in the component.

---

## `dialogComponents` Array

The actual content store. All node content lives here. Look up by `_id`.

```json
{
  "dialogComponents": [
    {
      "_id": "dc-0eb2824d-9b31-5b7e-a461-d73d9806a2d1",
      "refId": "...",
      "name": "GetAppointmentDetails",
      "type": "service",
      "piiDataEnabled": false,
      "serviceNodeType": "custom",
      ...type-specific fields...
    }
  ]
}
```

**Common fields on ALL components:**

| Field | Path | Notes |
|-------|------|-------|
| Component ID | `component._id` | Match against node's `componentId` |
| Name | `component.name` | Developer-assigned node name |
| Type | `component.type` | Same as node `type` |
| PII enabled | `component.piiDataEnabled` | boolean |
| Locale data | `component.localeData` | Multi-language content |
| Parent ID | `component.parentId` | Parent component reference |

---

## Node Types — Confirmed Across All 9 Exports

| Type value | Description | Present in |
|-----------|-------------|------------|
| `intent` | Dialog entry / intent node | All bots |
| `message` | Displays text to user | All bots |
| `entity` | Collects entity from user | All bots |
| `service` | API call (GET/POST/PATCH/DELETE) | All bots |
| `script` | Executes JavaScript | All bots |
| `aiassist` | AI Assist / Agent Node | Some bots |
| `generativeai` | LLM generative prompt node | Some bots |
| `searchai` | SearchAI knowledge base query | Some bots |
| `form` | Form-based input collection | All bots |
| `logic` | Conditional branching | Most bots |
| `dialogAct` | Yes/No confirmation prompt | Most bots |
| `dynamicIntent` | Dynamic intent resolution | Some bots |
| `agentTransfer` | Transfer to human agent | Some bots |

**NOT found in any export:** `confirmation`, `webhook`, `prompt`

---

## Component Fields by Node Type

### `message` component

```json
{
  "_id": "dc-051ac62c-...",
  "name": "WelcomeMessage",
  "type": "message",
  "message": [
    {
      "channel": "default",
      "localeData": {
        "en": {
          "text": "Welcome%20to%20the%20bot%21",
          "type": "basic"
        }
      }
    }
  ]
}
```

| Field | Path | Notes |
|-------|------|-------|
| Message text | `component.message[0].localeData.en.text` | **URL-encoded** — call `urllib.parse.unquote()` |
| Message type | `component.message[0].localeData.en.type` | `"basic"` (plain text) or `"uxmap"` (template/JS) |

---

### `entity` component

```json
{
  "_id": "dc-6f677ed3-...",
  "name": "preferredDate",
  "type": "entity",
  "entityType": "date",
  "localeData": {
    "en": {
      "label": "What is your preferred date? (DD-MM-YYYY)",
      "allowedValues": {
        "values": [
          {"title": "Monday", "value": "Monday", "synonyms": ["Mon", "monday"]}
        ]
      }
    }
  },
  "message": [
    {
      "channel": "default",
      "localeData": {
        "en": {"text": "What%20is%20your%20preferred%20date%3F", "type": "basic"}
      }
    }
  ],
  "errorMessage": [
    {
      "channel": "default",
      "localeData": {
        "en": {"text": "Invalid%20date%20format.", "type": "basic"}
      }
    }
  ]
}
```

| Field | Path | Notes |
|-------|------|-------|
| Entity type | `component.entityType` | `"label"`, `"date"`, `"time"`, `"phone_number"`, `"list_of_values"`, etc. |
| Entity prompt (label) | `component.localeData.en.label` | The question the bot asks |
| Bot message (spoken prompt) | `component.message[0].localeData.en.text` | URL-encoded |
| Error message | `component.errorMessage[0].localeData.en.text` | URL-encoded; shown on invalid input |
| Allowed values | `component.localeData.en.allowedValues.values` | List of `{title, value, synonyms}` |
| Array entity | `component.isArray` | boolean; entity accepts multiple values |

---

### `service` component

```json
{
  "_id": "dc-0eb2824d-...",
  "name": "GetAppointmentDetails",
  "type": "service",
  "endPoint": {
    "host": "697b49380e6ff62c3c5b94c6.mockapi.io",
    "port": "",
    "path": "/api/appointments/patients?contactNumber={{context.contactNumber}}",
    "protocol": "https",
    "method": "get",
    "connectorEnabled": false,
    "piiDataEnabled": false
  },
  "authRequired": false,
  "idp": "none",
  "serviceAPITimeout": 20,
  "payload": {"type": "raw", "value": "undefined"},
  "headers": {"type": "raw", "value": "{\"Content-Type\":\"application/json\"}"},
  "isClientCertEnabled": false
}
```

| Field | Path | Notes |
|-------|------|-------|
| HTTP method | `component.endPoint.method` | `"get"`, `"post"`, `"patch"`, `"delete"`, `"put"` |
| Host | `component.endPoint.host` | Domain (e.g. `"mockapi.io"`) |
| Path | `component.endPoint.path` | May contain `{{context.var}}` |
| Protocol | `component.endPoint.protocol` | `"https"` or `"http"` |
| Full URL | `f"{protocol}://{host}{path}"` | Reconstruct — no single `url` field |
| Auth required | `component.authRequired` | boolean |
| Auth provider | `component.idp` | `"none"` or auth config |
| Timeout (seconds) | `component.serviceAPITimeout` | Integer |
| Request body | `component.payload` | `{type: "raw", value: "...JSON string..."}` |
| Request headers | `component.headers` | `{type: "raw", value: "...JSON string..."}` |

---

### `script` component

```json
{
  "_id": "dc-4be0e58b-...",
  "name": "SAT_setSessionData",
  "type": "script",
  "script": "var%20l%3D%20koreUtil._%3B%0Avar%20refNumber%20%3D%20l.random(100000%2C999999)%3B..."
}
```

| Field | Path | Notes |
|-------|------|-------|
| Script content | `component.script` | **URL-encoded** — call `urllib.parse.unquote()` |

Decoded example:
```javascript
var l= koreUtil._;
var refNumber = l.random(100000,999999);
BotUserSession.put('phoneNumber', context.entities.SAT_phoneNumber);
```

---

### `aiassist` component (AI Assist / Agent Node)

**TRAP: The system context field has two inconsistent key names depending on bot version:**
- `systemContext` (camelCase) — found in Medical bots + most Travel bots
- `system_context` (snake_case) — found in Travel AI Agent (11)
- Some bots have **both** keys simultaneously

**Always try:** `ai.get('systemContext') or ai.get('system_context')`

```json
{
  "_id": "dc-129037a0-...",
  "name": "BookAppointmentAgent",
  "type": "aiassist",
  "generativeAI": {
    "dynamicEntityConfig": {
      "displayName": "Azure OpenAI by Kore.ai",
      "integrationName": "koreopenai",
      "model": "GPT-4o",
      "temperature": 0.7,
      "max_tokens": 1068,
      "systemContext": "You are a medical appointment scheduling assistant...",
      "dynamicEntities": [
        {"name": "doctorType", "type": "label"},
        {"name": "patientName", "type": "label"},
        {"name": "contactNumber", "type": "phone_number"},
        {"name": "preferredDate", "type": "date"},
        {"name": "preferredTime", "type": "time"},
        {"name": "reasonForVisit", "type": "label"}
      ],
      "rules": [
        "Ask only missing info.",
        "Validate each input and politely request corrections.",
        "Maintain a professional, calm, and friendly tone"
      ],
      "exitScenarios": [
        "Only when all entities are captured and valid."
      ]
    }
  }
}
```

| Field | Path | Notes |
|-------|------|-------|
| System context | `comp.generativeAI.dynamicEntityConfig` → `ai.get('systemContext') or ai.get('system_context')` | LLM system prompt — **two key variants** |
| Integration | `comp.generativeAI.dynamicEntityConfig.integrationName` | e.g. `"koreopenai"` |
| Model | `comp.generativeAI.dynamicEntityConfig.model` | e.g. `"GPT-4o"` |
| Temperature | `comp.generativeAI.dynamicEntityConfig.temperature` | float |
| Max tokens | `comp.generativeAI.dynamicEntityConfig.max_tokens` | integer |
| Dynamic entities | `comp.generativeAI.dynamicEntityConfig.dynamicEntities` | List of `{name, type}` — entities to collect |
| Collection rules | `comp.generativeAI.dynamicEntityConfig.rules` | List of string rules |
| Exit scenarios | `comp.generativeAI.dynamicEntityConfig.exitScenarios` | List of string conditions for handing back |

**NOT found:** `toolActions` — not present in any of the 9 exports analyzed.

---

### `generativeai` component (LLM Prompt Node)

```json
{
  "_id": "dc-2a7457bc-...",
  "name": "RefuseEvent",
  "type": "generativeai",
  "generativeAI": {
    "settings": {
      "model": "GPT-4o",
      "integrationName": "openai",
      "temperature": 0.5,
      "max_tokens": 2500,
      "system_context": ""
    },
    "promptFilterBasedOnModel": [
      {
        "name": "Default",
        "featureKey": "generativeai",
        "configuration": {
          "endPoint": {"protocol": "https:", "host": "api.openai.com", ...},
          "payloadFields": {
            "model": "gpt-4o",
            "messages": [{"role": "system", "content": "{{prompt}}"}]
          }
        }
      }
    ]
  }
}
```

| Field | Path | Notes |
|-------|------|-------|
| Model | `comp.generativeAI.settings.model` | e.g. `"GPT-4o"` |
| Temperature | `comp.generativeAI.settings.temperature` | float |
| System context | `comp.generativeAI.settings.system_context` | May be empty string |
| Integration | `comp.generativeAI.settings.integrationName` | |
| Prompt config | `comp.generativeAI.promptFilterBasedOnModel` | Array of model-specific prompt configs |

---

### `searchai` component

```json
{
  "_id": "dc-86c7f947-...",
  "name": "SearchAI_MultiIntent",
  "type": "searchai",
  "generativeAI": {
    "settings": {"isSysIntAndCustomPrompt": false},
    "searchConfig": {
      "type": "custom",
      "query": "{{context.userInputs.originalInput.sentence}}"
    },
    "searchFilters": {"type": "basic", "metaFilters": []},
    "resultConfig": {
      "answerSearch": true,
      "includeChunksInResponse": false
    }
  }
}
```

| Field | Path | Notes |
|-------|------|-------|
| Search query | `comp.generativeAI.searchConfig.query` | Usually `{{context.userInputs.originalInput.sentence}}` |
| Search type | `comp.generativeAI.searchConfig.type` | `"custom"` |
| Answer search | `comp.generativeAI.resultConfig.answerSearch` | boolean |

---

### `form` component

```json
{
  "_id": "dc-2ac9a974-...",
  "name": "CSAT5Options0001",
  "type": "form",
  "resourceId": "d3e64963-1e8f-5ddd-8c58-044ec1427261",
  "message": [
    {"channel": "default", "localeData": {"en": {"text": "Please click below...", "type": "basic"}}}
  ],
  "errorMessage": [...],
  "submitMessage": [...]
}
```

| Field | Path | Notes |
|-------|------|-------|
| Resource ID | `component.resourceId` | Links to `forms[i]['refId']` |
| Intro message | `comp.message[0].localeData.en.text` | URL-encoded |
| Error message | `comp.errorMessage[0].localeData.en.text` | URL-encoded |
| Submit message | `comp.submitMessage[0].localeData.en.text` | URL-encoded |

**Form definition in `forms` array** (linked via `resourceId`):
```json
{
  "name": "CSAT5Options",
  "displayName": "Feedback",
  "type": "regular",
  "refId": "d3e64963-1e8f-5ddd-8c58-044ec1427261",
  "components": [
    {
      "name": "Score",
      "type": "radio",
      "metaData": {"displayName": "How was your previous interaction?", ...}
    }
  ]
}
```

Link: `form_component['resourceId']` == `forms[i]['refId']`

---

### `dialogAct` component (Yes/No Confirmation)

```json
{
  "_id": "dc-30478dd1-...",
  "name": "SAT_ConfirmPhoneNumber",
  "type": "dialogAct",
  "message": [
    {
      "channel": "default",
      "localeData": {
        "en": {"type": "uxmap", "text": "var%20phoneNumber%20%3D%20..."}
      }
    }
  ]
}
```

| Field | Path | Notes |
|-------|------|-------|
| Confirmation prompt | `comp.message[0].localeData.en.text` | **URL-encoded**. Type may be `"uxmap"` (JS template) |
| Message type | `comp.message[0].localeData.en.type` | `"basic"` or `"uxmap"` |

Transitions on the dialogAct **node** determine the yes/no routing:
```json
{"if": {"dialogAct": "yes"}, "then": "nd-srv-abc123"}
{"if": {"dialogAct": "no"}, "then": "nd-scr-abc123"}
```

---

### `logic` component

Logic components are **bare** — no condition data stored in the component itself.

```json
{
  "_id": "dc-8b248710-...",
  "name": "LogicNode",
  "type": "logic",
  "localeData": {...}
}
```

**All branch conditions are on the dialog NODE's `transitions` array:**
```json
{
  "type": "logic",
  "componentId": "dc-8b248710-...",
  "transitions": [
    {
      "if": {"context": "context.dialogGPTInfo.winning_intents[0]", "op": "eq", "value": "Repeat"},
      "then": "nd-gai-abc123",
      "metadata": {...}
    },
    {"default": "nd-gai-xyz789", "metadata": {...}}
  ]
}
```

---

### `agentTransfer` component

```json
{
  "_id": "dc-835a9fc7-...",
  "name": "AgentTransferEvent",
  "type": "agentTransfer",
  "containmentType": "agenttransfer",
  "localeData": {"en": {"label": "AgentTransferEvent"}}
}
```

| Field | Path | Notes |
|-------|------|-------|
| Containment type | `component.containmentType` | Always `"agenttransfer"` |
| Label | `component.localeData.en.label` | Display name |

---

### `dynamicIntent` component

Minimal component — no additional content beyond standard fields.
Used for dynamic intent resolution at runtime.

---

### `intent` component

The entry/trigger node for a dialog. Contains intent training data in `localeData`.

---

## `dialogGPTSettings` (TRAP: Array)

```json
"dialogGPTSettings": [
  {
    "conversationTypes": [
      {"label": "Dialogs", "id": "dialogs"},
      {"label": "FAQs", "id": "faqs"}
    ],
    "searchIndexId": "sixd-85eede49-...",
    "dialogGPTLLMConfig": {
      "name": "dialogGPT",
      "defaultModel": "XO GPT - DialogGPT Model",
      "integration": "korexo",
      "enable": true,
      "temperature": 0.5,
      "maxTokens": 2000,
      "conversationHistoryLength": 25,
      "promptName": "System prompt"
    },
    "embeddingModelConfig": {
      "modelName": [
        {
          "label": "XO GPT - BGE M3 Embeddings Model",
          "id": "bge-m3",
          "maxNumOfChunks": 5,
          "similarityThreshold": 20
        }
      ]
    },
    "language": "en"
  }
]
```

**TRAP:** This is an **array**, not an object. Always access `[0]`.

| Field | Path | Notes |
|-------|------|-------|
| Enabled | `dialogGPTSettings[0].dialogGPTLLMConfig.enable` | boolean |
| Model | `dialogGPTSettings[0].dialogGPTLLMConfig.defaultModel` | e.g. `"XO GPT - DialogGPT Model"` |
| Temperature | `dialogGPTSettings[0].dialogGPTLLMConfig.temperature` | float |
| Max tokens | `dialogGPTSettings[0].dialogGPTLLMConfig.maxTokens` | integer |
| History length | `dialogGPTSettings[0].dialogGPTLLMConfig.conversationHistoryLength` | integer |
| Search index | `dialogGPTSettings[0].searchIndexId` | Used for SearchAI integration |

---

## `knowledgeTasks` / FAQs (TRAP: Double-Nested)

```json
"knowledgeTasks": [
  {
    "name": "Medi_Assistant",
    "language": "en",
    "isGraph": false,
    "faqs": {
      "faqs": [
        {
          "question": "What should I bring to my appointment?",
          "label": "What should I bring to my appointment?",
          "responseType": "message",
          "answer": [
            {
              "text": "Bring a valid ID, insurance card, previous medical records...",
              "type": "basic",
              "channel": "default"
            }
          ],
          "alternateQuestions": [
            {"question": "What items do I need to bring?", "terms": [...], "tags": []}
          ],
          "alternateAnswers": [],
          "faqStatus": true,
          "conditionalResp": false
        }
      ],
      "nodes": [...],
      "synonyms": {...}
    }
  }
]
```

**TRAP:** FAQ array is at `.faqs.faqs` (double-nested) — NOT `.faqs`.
**TRAP:** `answer` is a **list**, not a string. Access `answer[0]['text']`.

| Field | Path | Notes |
|-------|------|-------|
| FAQ array | `knowledgeTasks[0].faqs.faqs` | **Double-nested** |
| Question | `faq.question` | Primary question |
| Answer text | `faq.answer[0].text` | **List** — access `[0].text` for default channel |
| Response type | `faq.responseType` | Usually `"message"` |
| Alternate questions | `faq.alternateQuestions` | List of `{question, terms, tags}` |
| Alternate answers | `faq.alternateAnswers` | List (usually empty) |
| FAQ active | `faq.faqStatus` | boolean |

---

## `llmConfiguration` Array

```json
"llmConfiguration": [
  {
    "featureList": [
      {
        "name": "conversation",
        "defaultModel": "GPT-4o",
        "integration": "koreopenai",
        "displayName": "Azure OpenAI by Kore.ai",
        "params": {"temperature": 0.5, "max_tokens": 2500},
        "enable": true
      },
      {
        "name": "dialogGPT",
        "defaultModel": "XO GPT - DialogGPT Model",
        "integration": "korexo",
        "enable": true
      },
      {"name": "vectorGeneration", "defaultModel": "bge-m3", "enable": true},
      {"name": "generativeai", "defaultModel": "GPT-4o", "enable": true}
    ]
  }
]
```

| Field | Path | Notes |
|-------|------|-------|
| Feature list | `llmConfiguration[0].featureList` | List of enabled LLM features |
| Feature name | `feature.name` | `"conversation"`, `"dialogGPT"`, `"generativeai"`, `"vectorGeneration"`, etc. |
| Default model | `feature.defaultModel` | e.g. `"GPT-4o"`, `"bge-m3"` |
| Integration | `feature.integration` | e.g. `"koreopenai"`, `"korexo"` |
| Enabled | `feature.enable` | boolean (may be absent if false) |

---

## `customDashboards` Array

Present in feature-rich bots (e.g. Travel VA New). Empty in Medical bots.

```json
"customDashboards": [
  {
    "name": "CustomAnalytics",
    "properties": {
      "0": {"ind": 0, "id": "wg-9d72ff12-...", "meta": 100, "metaHeight": 300}
    },
    "widgets": [
      {
        "_id": "wg-9d72ff12-...",
        "name": "Message Count",
        "type": "table",
        "mode": "advanced",
        "dimensions": [
          {"fieldName": "Message Type", "displayName": "Message Type", "type": "string"},
          {"fieldName": "Count", "displayName": "Count", "type": "number"}
        ]
      }
    ]
  }
]
```

| Field | Path | Notes |
|-------|------|-------|
| Dashboard name | `dashboard.name` | |
| Widgets | `dashboard.widgets` | List of widget definitions |
| Widget name | `widget.name` | |
| Widget type | `widget.type` | `"table"`, `"chart"`, etc. |
| Dimensions | `widget.dimensions` | List of `{fieldName, displayName, type}` |

---

## `contentVariables` Array

```json
"contentVariables": [
  {
    "key": "some_var",
    "variableType": "env",
    "value": "some_value",
    "scope": "prePopulated"
  }
]
```

| Field | Path | Notes |
|-------|------|-------|
| Variable key | `var.key` | Variable name |
| Type | `var.variableType` | `"env"`, `"content"`, etc. |
| Value | `var.value` | Variable value |

---

## `botEvents` Object

14 event handlers for system events.

```json
"botEvents": {
  "AGENT_TRANSFER_EVENT": [...handlers...],
  "AMBIGUOUS_INTENTS": [...],
  "ANSWER_GENERATION_EVENT": [...],
  "CONVERSATION_END": [...],
  "INTENT_UNIDENTIFIED": [...],
  "INTERACTION_INTENTS": [...],
  "MULTI_INTENT_EVENT": [...],
  "ON_CONNECT_EVENT": [...],
  "REPEAT_RESPONSE_EVENT": [...],
  "RESTART_CONVERSATION_EVENT": [...],
  "TASK_END_EVENT": [...],
  "TASK_FAILURE_EVENT": [...],
  "TELEPHONY_WELCOME_EVENT": [...],
  "WELCOME_MESSAGE_EVENT": [...]
}
```

---

## `channels` Array

Always empty in all 9 exports analyzed. Channel configurations are managed in the Kore.ai platform, not exported in the appDefinition.json.

```json
"channels": []
```

---

## Parser Traps Summary

See `docs/parser_traps.md` for the full list with wrong code vs. correct code.

| # | Trap | Quick Fix |
|---|------|-----------|
| 1 | `dialogGPTSettings` is an array | Access `[0].dialogGPTLLMConfig.enable` |
| 2 | FAQ double-nesting | `knowledgeTasks[0].faqs.faqs` not `.faqs` |
| 3 | `aiassist` type name | `"aiassist"` not `"agent"` or `"agentNode"` |
| 4 | No `botInfo` key | Use `localeData.en.name` |
| 5 | No `dialog.name` field | Use `dialog.localeData.en.name` |
| 6 | Nodes are reference stubs | Resolve `componentId` → `dialogComponents` |
| 7 | No `componentMap` key | Build `{comp._id: comp}` from `dialogComponents` |
| 8 | Message/script URL-encoded | `urllib.parse.unquote(text)` |
| 9 | FAQ `answer` is a list | `faq['answer'][0]['text']` |
| 10 | Form links via `resourceId` | `forms_lookup[comp['resourceId']]` where key is `forms[i]['refId']` |
| 11 | Logic conditions on node | `node['transitions'][i]['if']` not on component |
| 12 | aiassist context key varies | `ai.get('systemContext') or ai.get('system_context')` |
