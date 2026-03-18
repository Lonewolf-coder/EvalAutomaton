"""CBM Field Map — Confirmed JSON paths from real Kore.ai bot exports.

All paths verified from 9 real bot exports (2 Medical, 7 Travel).
Trust these over Kore.ai documentation — the actual export format
differs from the docs in several critical places.

12 PARSER TRAPS — Read parser_traps.md before writing any parser code.
Key ones:
1. dialogGPTSettings is an ARRAY → access [0]
2. FAQ array is knowledgeTasks[0].faqs.faqs — NOT .faqs
3. aiassist type is 'aiassist' — not 'agent'
4. No 'botInfo' key → use localeData.en.name
5. No dialog 'name' key → use dialog.localeData.en.name
6. Dialog nodes are stubs → resolve componentId → dialogComponents
7. No 'componentMap' → build {_id: comp} from dialogComponents
8. Message text and scripts are URL-encoded → urllib.parse.unquote()
9. FAQ answer is a list → faq.answer[0].text
10. Form links via resourceId → forms[i].refId
11. Logic conditions on node.transitions, not on the component
12. aiassist systemContext: try 'systemContext' AND 'system_context' (both exist)
"""

# ---------------------------------------------------------------------------
# Bot metadata — top-level fields (NO botInfo object exists)
# ---------------------------------------------------------------------------

BOT_NAME_LOCALE = "localeData.en.name"          # Primary: appDefinition.json
BOT_NAME_CONFIG = "name"                         # Fallback: config.json
BOT_DESCRIPTION = "localeData.en.description"
BOT_DEFAULT_LANGUAGE = "defaultLanguage"
BOT_SUPPORTED_LANGUAGES = "supportedLanguages"
BOT_VERSION = "environmentVersionInfo"           # e.g. "9.1.7"
BOT_PURPOSE = "purpose"                          # always "customer"
BOT_IS_AGENT_ASSIST = "isAgentAssist"
BOT_IS_SMART_ASSIST = "isSmartAssist"
BOT_STRICT_PII = "strict_pii"

# ---------------------------------------------------------------------------
# Dialog paths
# ---------------------------------------------------------------------------

DIALOGS = "dialogs"

# TRAP 5: No 'name' key on dialogs — use localeData
DIALOG_NAME_LOCALE = "localeData.en.name"        # display name
DIALOG_NAME_LNAME = "lname"                      # lowercase internal name
DIALOG_SHORT_DESC = "localeData.en.shortDesc"
DIALOG_ID = "_id"
DIALOG_NODES = "nodes"
DIALOG_IS_HIDDEN = "isHidden"
DIALOG_IS_FOLLOW_UP = "isFollowUp"
DIALOG_IS_ABANDONMENT = "isAbandonment"

# ---------------------------------------------------------------------------
# Node reference fields (in dialogs[i].nodes — stubs only)
# ---------------------------------------------------------------------------

# TRAP 6: Nodes are reference stubs. Content is in dialogComponents.
NODE_TYPE = "type"
NODE_COMPONENT_ID = "componentId"                # key to look up in dialogComponents
NODE_ID = "nodeId"
NODE_TRANSITIONS = "transitions"
NODE_OPTIONS = "nodeOptions"
NODE_PRE_CONDITIONS = "preConditions"

# ---------------------------------------------------------------------------
# dialogComponents — the actual content store
# ---------------------------------------------------------------------------

# TRAP 7: No componentMap. Build lookup from dialogComponents.
DIALOG_COMPONENTS = "dialogComponents"
COMPONENT_ID_FIELD = "_id"                       # match against node.componentId
COMPONENT_NAME = "name"
COMPONENT_TYPE = "type"
COMPONENT_PII_ENABLED = "piiDataEnabled"
COMPONENT_LOCALE_DATA = "localeData"

# ---------------------------------------------------------------------------
# Node types (confirmed across all 9 exports)
# ---------------------------------------------------------------------------

NODE_TYPE_INTENT = "intent"
NODE_TYPE_MESSAGE = "message"
NODE_TYPE_ENTITY = "entity"
NODE_TYPE_SERVICE = "service"
NODE_TYPE_SCRIPT = "script"
NODE_TYPE_AGENT = "aiassist"                     # TRAP 3: not 'agent'
NODE_TYPE_GENERATIVE_AI = "generativeai"
NODE_TYPE_SEARCH_AI = "searchai"
NODE_TYPE_FORM = "form"
NODE_TYPE_LOGIC = "logic"
NODE_TYPE_DIALOG_ACT = "dialogAct"
NODE_TYPE_DYNAMIC_INTENT = "dynamicIntent"
NODE_TYPE_AGENT_TRANSFER = "agentTransfer"

# NOT FOUND in any of 9 exports (keep as constants for forward-compat):
NODE_TYPE_CONFIRMATION = "confirmation"          # not present in real exports
NODE_TYPE_WEBHOOK = "webhook"                    # not present in real exports
NODE_TYPE_PROMPT = "prompt"                      # not present in real exports

# ---------------------------------------------------------------------------
# Transition condition types
# ---------------------------------------------------------------------------

# Transition variant 1: simple default
#   {"default": "nodeId", "metadata": {...}}
TRANSITION_DEFAULT = "default"

# Transition variant 2: entity value condition
#   {"if": {"field": "nd-ent-...", "op": "eq", "value": "SomeValue"}, "then": "nodeId"}
TRANSITION_IF = "if"
TRANSITION_THEN = "then"
TRANSITION_IF_FIELD = "field"
TRANSITION_IF_CONTEXT = "context"
TRANSITION_IF_DIALOG_ACT = "dialogAct"
TRANSITION_IF_OP = "op"
TRANSITION_IF_VALUE = "value"

# ---------------------------------------------------------------------------
# message node — content in dialogComponents
# ---------------------------------------------------------------------------

# TRAP 8: text is URL-encoded — apply urllib.parse.unquote()
MESSAGE_ARRAY = "message"
MESSAGE_LOCALE_TEXT = "message[0].localeData.en.text"    # URL-encoded
MESSAGE_LOCALE_TYPE = "message[0].localeData.en.type"    # "basic" or "uxmap"

# ---------------------------------------------------------------------------
# entity node — content in dialogComponents
# ---------------------------------------------------------------------------

ENTITY_TYPE = "entityType"                               # "label", "date", "time", etc.
ENTITY_LABEL = "localeData.en.label"                     # the question asked
ENTITY_ALLOWED_VALUES = "localeData.en.allowedValues.values"
ENTITY_IS_ARRAY = "isArray"
ENTITY_MESSAGE_TEXT = "message[0].localeData.en.text"    # URL-encoded
ENTITY_ERROR_MESSAGE = "errorMessage[0].localeData.en.text"  # URL-encoded

# ---------------------------------------------------------------------------
# service node — content in dialogComponents
# ---------------------------------------------------------------------------

# TRAP: No single 'url' field. Reconstruct from endPoint sub-fields.
SERVICE_ENDPOINT = "endPoint"
SERVICE_METHOD = "endPoint.method"                       # "get", "post", "patch", "delete"
SERVICE_HOST = "endPoint.host"
SERVICE_PATH = "endPoint.path"                           # may contain {{context.var}}
SERVICE_PROTOCOL = "endPoint.protocol"                   # "https" or "http"
SERVICE_AUTH_REQUIRED = "authRequired"
SERVICE_IDP = "idp"                                      # "none" or auth config
SERVICE_TIMEOUT = "serviceAPITimeout"                    # seconds
SERVICE_PAYLOAD = "payload"                              # {type: "raw", value: "..."}
SERVICE_HEADERS = "headers"                              # {type: "raw", value: "..."}

# ---------------------------------------------------------------------------
# script node — content in dialogComponents
# ---------------------------------------------------------------------------

# TRAP 8: script content is URL-encoded — apply urllib.parse.unquote()
SCRIPT_CONTENT = "script"

# ---------------------------------------------------------------------------
# aiassist node — content in dialogComponents
# ---------------------------------------------------------------------------

AIASSIST_GENERATIVE_AI = "generativeAI"
AIASSIST_DYNAMIC_ENTITY_CONFIG = "generativeAI.dynamicEntityConfig"

# TRAP 12: Two inconsistent key names — try BOTH
AIASSIST_SYSTEM_CONTEXT_CAMEL = "systemContext"          # most bots
AIASSIST_SYSTEM_CONTEXT_SNAKE = "system_context"         # Travel AI Agent (11)
# Usage: ai.get('systemContext') or ai.get('system_context')

AIASSIST_INTEGRATION = "integrationName"                 # e.g. "koreopenai"
AIASSIST_MODEL = "model"                                 # e.g. "GPT-4o"
AIASSIST_TEMPERATURE = "temperature"
AIASSIST_MAX_TOKENS = "max_tokens"
AIASSIST_DYNAMIC_ENTITIES = "dynamicEntities"            # [{name, type}]
AIASSIST_RULES = "rules"                                 # [str]
AIASSIST_EXIT_SCENARIOS = "exitScenarios"                # [str]

# ---------------------------------------------------------------------------
# generativeai node — content in dialogComponents
# ---------------------------------------------------------------------------

GENERATIVE_AI_SETTINGS = "generativeAI.settings"
GENERATIVE_AI_MODEL = "generativeAI.settings.model"
GENERATIVE_AI_TEMPERATURE = "generativeAI.settings.temperature"
GENERATIVE_AI_SYSTEM_CONTEXT = "generativeAI.settings.system_context"
GENERATIVE_AI_PROMPT_FILTER = "generativeAI.promptFilterBasedOnModel"

# ---------------------------------------------------------------------------
# searchai node — content in dialogComponents
# ---------------------------------------------------------------------------

SEARCH_AI_CONFIG = "generativeAI.searchConfig"
SEARCH_AI_QUERY = "generativeAI.searchConfig.query"
SEARCH_AI_RESULT_CONFIG = "generativeAI.resultConfig"
SEARCH_AI_ANSWER_SEARCH = "generativeAI.resultConfig.answerSearch"

# ---------------------------------------------------------------------------
# form node — content in dialogComponents
# ---------------------------------------------------------------------------

# TRAP 10: Link via resourceId (NOT formId — formId doesn't exist)
FORM_RESOURCE_ID = "resourceId"                          # matches forms[i].refId
FORM_MESSAGE = "message"
FORM_ERROR_MESSAGE = "errorMessage"
FORM_SUBMIT_MESSAGE = "submitMessage"

# In the top-level 'forms' array:
FORMS_ARRAY = "forms"
FORM_DEF_NAME = "name"
FORM_DEF_DISPLAY_NAME = "displayName"
FORM_DEF_REF_ID = "refId"                               # matches form component's resourceId
FORM_DEF_COMPONENTS = "components"

# ---------------------------------------------------------------------------
# dialogAct node — content in dialogComponents
# ---------------------------------------------------------------------------

DIALOG_ACT_MESSAGE = "message[0].localeData.en.text"    # URL-encoded confirmation prompt
DIALOG_ACT_MESSAGE_TYPE = "message[0].localeData.en.type"

# ---------------------------------------------------------------------------
# agentTransfer node — content in dialogComponents
# ---------------------------------------------------------------------------

AGENT_TRANSFER_CONTAINMENT_TYPE = "containmentType"     # always "agenttransfer"

# ---------------------------------------------------------------------------
# logic node — TRAP 11: conditions on node.transitions, NOT the component
# ---------------------------------------------------------------------------

# Logic components store no conditions. Parse from node['transitions']:
#   conditional: {"if": {"context": "...", "op": "eq", "value": "..."}, "then": "nodeId"}
#   default: {"default": "nodeId"}

# ---------------------------------------------------------------------------
# DialogGPT / LLM Configuration
# ---------------------------------------------------------------------------

# TRAP 1: dialogGPTSettings is an ARRAY
DIALOG_GPT_SETTINGS = "dialogGPTSettings"
DIALOG_GPT_ENABLED = "dialogGPTSettings[0].dialogGPTLLMConfig.enable"
DIALOG_GPT_MODEL = "dialogGPTSettings[0].dialogGPTLLMConfig.defaultModel"
DIALOG_GPT_TEMPERATURE = "dialogGPTSettings[0].dialogGPTLLMConfig.temperature"
DIALOG_GPT_MAX_TOKENS = "dialogGPTSettings[0].dialogGPTLLMConfig.maxTokens"
DIALOG_GPT_HISTORY_LENGTH = "dialogGPTSettings[0].dialogGPTLLMConfig.conversationHistoryLength"

LLM_CONFIGURATION = "llmConfiguration"
LLM_FEATURE_LIST = "llmConfiguration[0].featureList"

# ---------------------------------------------------------------------------
# FAQ / Knowledge Tasks
# ---------------------------------------------------------------------------

# TRAP 2: FAQ array is faqs.faqs, NOT just .faqs
KNOWLEDGE_TASKS = "knowledgeTasks"
FAQ_ARRAY = "knowledgeTasks[0].faqs.faqs"
FAQ_QUESTION = "question"
FAQ_LABEL = "label"
FAQ_RESPONSE_TYPE = "responseType"
FAQ_STATUS = "faqStatus"

# TRAP 9: answer is a LIST of {text, type, channel} — NOT a string
FAQ_ANSWER_LIST = "answer"                               # the list
FAQ_ANSWER_TEXT = "answer[0].text"                       # the actual text
FAQ_ALTERNATE_QUESTIONS = "alternateQuestions"
FAQ_ALTERNATE_ANSWERS = "alternateAnswers"

# ---------------------------------------------------------------------------
# Bot-wide sections
# ---------------------------------------------------------------------------

CUSTOM_DASHBOARDS = "customDashboards"
DASHBOARD_NAME = "name"
DASHBOARD_WIDGETS = "widgets"
WIDGET_NAME = "name"
WIDGET_TYPE = "type"
WIDGET_DIMENSIONS = "dimensions"

CONTENT_VARIABLES = "contentVariables"
CONTENT_VAR_KEY = "key"
CONTENT_VAR_TYPE = "variableType"
CONTENT_VAR_VALUE = "value"

CHANNELS = "channels"                                    # always empty in real exports

BOT_EVENTS = "botEvents"                                 # dict of 14 event handlers

ADVANCED_NL_SETTINGS = "advancedNLSettings"
ML_PARAMS = "mlParams"

# ---------------------------------------------------------------------------
# Kore.ai Platform API endpoints (unchanged)
# ---------------------------------------------------------------------------

KORE_EXPORT_API = "/api/public/bot/{botId}/export"
KORE_ANALYTICS_API = "/api/public/bot/{botId}/analytics"
KORE_BATCH_TEST_API = "/api/public/bot/{botId}/ml/batchtesting"
