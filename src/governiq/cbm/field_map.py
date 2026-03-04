"""CBM Field Map — Confirmed JSON paths from real Kore.ai bot exports.

Every path confirmed by parsing a real candidate bot export (appDefinition.json,
Bernado Basic). Trust these paths over Kore.ai documentation — the actual
export format differs from the docs in several critical places.

THREE PARSER TRAPS — Read Before Writing Any Parser Code:
1. dialogGPTSettings is an ARRAY, not an object. Access [0].dialogGPTLLMConfig.enable
2. The FAQ array is at knowledgeTasks[0].faqs.faqs — NOT .faqs directly
3. Agent Node type is 'aiassist' — not 'agent' or 'agentNode'
"""

# ---------------------------------------------------------------------------
# Top-level export paths
# ---------------------------------------------------------------------------

# Bot metadata
BOT_NAME = "botInfo.name"
BOT_DESCRIPTION = "botInfo.description"
BOT_DEFAULT_LANGUAGE = "botInfo.defaultLanguage"

# ---------------------------------------------------------------------------
# Dialog paths
# ---------------------------------------------------------------------------

# All dialogs are in the top-level 'dialogs' array
DIALOGS = "dialogs"
DIALOG_NAME = "name"
DIALOG_NODES = "nodes"

# Node fields
NODE_TYPE = "type"
NODE_NAME = "name"
NODE_ID = "nodeId"
NODE_TRANSITIONS = "transitions"
NODE_COMPONENT = "component"

# ---------------------------------------------------------------------------
# Node types (confirmed from real export)
# ---------------------------------------------------------------------------

NODE_TYPE_MESSAGE = "message"
NODE_TYPE_ENTITY = "entity"
NODE_TYPE_SERVICE = "service"
NODE_TYPE_SCRIPT = "script"
NODE_TYPE_AGENT = "aiassist"        # TRAP 3: Not 'agent' or 'agentNode'
NODE_TYPE_CONFIRMATION = "confirmation"
NODE_TYPE_FORM = "form"
NODE_TYPE_LOGIC = "logic"
NODE_TYPE_WEBHOOK = "webhook"
NODE_TYPE_PROMPT = "prompt"

# ---------------------------------------------------------------------------
# DialogGPT / LLM Configuration
# ---------------------------------------------------------------------------

# TRAP 1: dialogGPTSettings is an ARRAY
DIALOG_GPT_SETTINGS = "dialogGPTSettings"
DIALOG_GPT_ENABLE = "dialogGPTSettings[0].dialogGPTLLMConfig.enable"

# ---------------------------------------------------------------------------
# FAQ / Knowledge Tasks
# ---------------------------------------------------------------------------

# TRAP 2: FAQ array is faqs.faqs, not just .faqs
KNOWLEDGE_TASKS = "knowledgeTasks"
FAQ_ARRAY = "knowledgeTasks[0].faqs.faqs"
FAQ_QUESTION = "question"
FAQ_ANSWER = "answer"
FAQ_ALTERNATES = "alternateQuestions"

# ---------------------------------------------------------------------------
# Component Map — for dialog name resolution
# ---------------------------------------------------------------------------

COMPONENT_MAP = "componentMap"

# ---------------------------------------------------------------------------
# Service node details
# ---------------------------------------------------------------------------

SERVICE_TYPE = "serviceType"
SERVICE_METHOD = "method"
SERVICE_URL = "url"

# ---------------------------------------------------------------------------
# Entity node details
# ---------------------------------------------------------------------------

ENTITY_TYPE = "entityType"
ENTITY_VALIDATION = "validationRules"

# ---------------------------------------------------------------------------
# Training utterances
# ---------------------------------------------------------------------------

TRAINING_DATA = "trainingData"
UTTERANCES = "utterances"

# ---------------------------------------------------------------------------
# Channels
# ---------------------------------------------------------------------------

CHANNELS = "channels"

# ---------------------------------------------------------------------------
# API Endpoints (confirmed from real platform)
# ---------------------------------------------------------------------------

KORE_EXPORT_API = "/api/public/bot/{botId}/export"
KORE_ANALYTICS_API = "/api/public/bot/{botId}/analytics"
KORE_BATCH_TEST_API = "/api/public/bot/{botId}/ml/batchtesting"
