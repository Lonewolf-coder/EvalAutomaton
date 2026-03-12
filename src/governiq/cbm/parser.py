"""CBM Parser — Parses Kore.ai bot exports into a structured CBM object.

ALL 12 PARSER TRAPS ARE HANDLED. See docs/parser_traps.md for details.

Key architectural facts confirmed from real exports:
- No 'botInfo' key — bot name is at localeData.en.name
- Dialog nodes are reference stubs — resolve componentId → dialogComponents
- No 'componentMap' — build {_id: comp} from dialogComponents
- Message text and scripts are URL-encoded — urllib.parse.unquote()
- FAQ answer is a list — access answer[0].text
- Logic conditions are on node.transitions, not the component
- aiassist systemContext: try 'systemContext' AND 'system_context'
"""

from __future__ import annotations

import json
import re
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import field_map as fm


# ---------------------------------------------------------------------------
# Data structures the parser produces
# ---------------------------------------------------------------------------

@dataclass
class CBMNode:
    """A single node in a dialog flow, with content resolved from dialogComponents."""
    node_id: str
    node_type: str
    name: str
    component: dict[str, Any] = field(default_factory=dict)
    transitions: list[dict[str, Any]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    # Type-specific content fields (populated during parse)
    script_content: str | None = None
    service_url: str | None = None
    service_method: str | None = None
    service_request_body: dict[str, Any] | None = None
    ai_assist_context: str | None = None
    ai_assist_entity_rules: list[str] | None = None
    ai_assist_tools: list[dict[str, Any]] | None = None
    ai_assist_exit_scenarios: list[str] | None = None
    logic_conditions: list[dict[str, Any]] | None = None
    confirmation_prompt: str | None = None

    @property
    def is_agent_node(self) -> bool:
        return self.node_type == fm.NODE_TYPE_AGENT

    @property
    def is_service_node(self) -> bool:
        return self.node_type == fm.NODE_TYPE_SERVICE

    @property
    def is_entity_node(self) -> bool:
        return self.node_type == fm.NODE_TYPE_ENTITY

    @property
    def is_message_node(self) -> bool:
        return self.node_type == fm.NODE_TYPE_MESSAGE

    @property
    def is_form_node(self) -> bool:
        return self.node_type == fm.NODE_TYPE_FORM

    @property
    def is_logic_node(self) -> bool:
        return self.node_type == fm.NODE_TYPE_LOGIC

    @property
    def is_generative_ai_node(self) -> bool:
        return self.node_type == fm.NODE_TYPE_GENERATIVE_AI

    @property
    def is_search_ai_node(self) -> bool:
        return self.node_type == fm.NODE_TYPE_SEARCH_AI

    @property
    def is_agent_transfer_node(self) -> bool:
        return self.node_type == fm.NODE_TYPE_AGENT_TRANSFER

    @property
    def entity_type(self) -> str | None:
        if self.is_entity_node:
            return self.component.get("entityType")
        return None

    @property
    def entity_prompt(self) -> str:
        """The question label for entity nodes."""
        if self.is_entity_node:
            return (
                self.component.get("localeData", {})
                .get("en", {})
                .get("label", "")
            )
        return ""

    @property
    def message_text(self) -> str:
        """Extract message text, handling URL-encoding and multiple formats."""
        comp = self.component
        msg = comp.get("message", [])
        if isinstance(msg, list) and msg:
            raw = msg[0].get("localeData", {}).get("en", {}).get("text", "")
            if raw:
                return urllib.parse.unquote(raw)
        return ""

    @property
    def user_label(self) -> str:
        """The user-visible label for this node."""
        for key in ("title", "displayName", "label"):
            val = self.component.get(key)
            if val:
                return str(val)
        return self.name

    @property
    def content_summary(self) -> str:
        """Human-readable content summary for the blueprint."""
        if self.is_message_node:
            text = self.message_text
            return text[:200] if text else ""

        if self.is_entity_node:
            entity_t = self.entity_type or "unknown"
            prompt = self.entity_prompt
            return f"[{entity_t}] {prompt[:150]}" if prompt else f"[{entity_t}]"

        if self.is_service_node:
            method = (self.service_method or "").upper()
            url = self.service_url or ""
            return f"{method} {url[:120]}" if url else method

        if self.node_type == fm.NODE_TYPE_SCRIPT:
            code = self.script_content or ""
            if code.strip():
                lines = [l.strip() for l in code.strip().split("\n") if l.strip()]
                return lines[0][:150] if lines else ""
            return ""

        if self.is_agent_node:
            context = self.ai_assist_context or ""
            if context:
                return f"AI Assist: {context[:150]}"
            entities = self.ai_assist_tools or []
            names = [e.get("name", "") for e in entities]
            return f"AI Assist — collects: {', '.join(names)}" if names else "AI Assist"

        if self.is_generative_ai_node:
            genai = self.component.get("generativeAI", {})
            model = genai.get("settings", {}).get("model", "")
            return f"GenerativeAI: {model}" if model else "GenerativeAI"

        if self.is_search_ai_node:
            query = (
                self.component.get("generativeAI", {})
                .get("searchConfig", {})
                .get("query", "")
            )
            return f"SearchAI: {query[:100]}" if query else "SearchAI"

        if self.is_logic_node:
            conditions = self.logic_conditions or []
            return f"Logic: {len(conditions)} branch(es)"

        if self.node_type == fm.NODE_TYPE_DIALOG_ACT:
            prompt = self.confirmation_prompt or self.message_text
            return f"DialogAct: {prompt[:120]}" if prompt else "DialogAct (yes/no)"

        if self.is_agent_transfer_node:
            return "Agent Transfer — handoff to human agent"

        if self.is_form_node:
            return f"Form: {self.name}"

        return ""

    @property
    def validation_rules(self) -> list[dict[str, Any]]:
        if self.is_entity_node:
            rules = self.component.get("validationRules") or self.raw.get("validationRules")
            return rules if isinstance(rules, list) else []
        return []


@dataclass
class CBMDialog:
    """A parsed dialog with its resolved node sequence."""
    name: str
    dialog_id: str
    short_desc: str = ""
    nodes: list[CBMNode] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    def get_nodes_by_type(self, node_type: str) -> list[CBMNode]:
        return [n for n in self.nodes if n.node_type == node_type]

    def has_node_type(self, node_type: str) -> bool:
        return any(n.node_type == node_type for n in self.nodes)

    def get_entity_nodes(self) -> list[CBMNode]:
        return self.get_nodes_by_type(fm.NODE_TYPE_ENTITY)

    def get_service_nodes(self) -> list[CBMNode]:
        return self.get_nodes_by_type(fm.NODE_TYPE_SERVICE)

    def has_agent_node(self) -> bool:
        return self.has_node_type(fm.NODE_TYPE_AGENT)

    @property
    def connection_graph(self) -> list[tuple[str, str, str]]:
        """Returns (from_node_id, to_node_id, condition_label) triples."""
        edges = []
        for node in self.nodes:
            for t in node.transitions:
                if "default" in t:
                    edges.append((node.node_id, t["default"], "default"))
                elif "if" in t and "then" in t:
                    cond = t["if"]
                    if "dialogAct" in cond:
                        label = cond["dialogAct"]
                    elif "value" in cond:
                        label = f"{cond.get('op','==')} {cond['value']}"
                    else:
                        label = str(cond)[:40]
                    edges.append((node.node_id, t["then"], label))
        return edges


@dataclass
class CBMFAQ:
    """A single FAQ entry from the knowledge task."""
    question: str
    answer: str
    alternate_questions: list[str] = field(default_factory=list)
    response_type: str = "message"
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class CBMObject:
    """The complete structured CBM object produced by the parser."""
    bot_name: str = ""
    bot_description: str = ""
    bot_version: str = ""
    default_language: str = ""
    languages: list[str] = field(default_factory=list)
    dialogs: list[CBMDialog] = field(default_factory=list)
    faqs: list[CBMFAQ] = field(default_factory=list)
    dialog_gpt_enabled: bool | None = None
    dialog_gpt_model: str = ""
    llm_features: list[dict[str, Any]] = field(default_factory=list)
    custom_dashboards: list[dict[str, Any]] = field(default_factory=list)
    custom_variables: list[dict[str, Any]] = field(default_factory=list)
    channels: list[dict[str, Any]] = field(default_factory=list)
    bot_events: dict[str, Any] = field(default_factory=dict)
    raw_export: dict[str, Any] = field(default_factory=dict)

    def find_dialog(self, name: str, policy: str = "contains") -> CBMDialog | None:
        """Find a dialog by name using the specified matching policy."""
        name_lower = name.lower()
        for dialog in self.dialogs:
            dialog_lower = dialog.name.lower()
            if policy == "exact" and dialog_lower == name_lower:
                return dialog
            elif policy == "contains" and (name_lower in dialog_lower or dialog_lower in name_lower):
                return dialog
        return None

    @property
    def component_map(self) -> dict[str, "CBMDialog"]:
        """Map of dialog_id → CBMDialog for all parsed dialogs."""
        return {d.dialog_id: d for d in self.dialogs}

    def find_dialog_fuzzy(self, name: str) -> tuple[CBMDialog | None, float]:
        """Fuzzy match a dialog name. Returns (dialog, similarity_score)."""
        if not self.dialogs:
            return None, 0.0

        name_lower = name.lower()
        best_match = None
        best_score = 0.0

        for dialog in self.dialogs:
            dialog_lower = dialog.name.lower()
            name_tokens = set(re.split(r'\W+', name_lower))
            dialog_tokens = set(re.split(r'\W+', dialog_lower))
            if not name_tokens or not dialog_tokens:
                continue
            overlap = len(name_tokens & dialog_tokens)
            score = overlap / max(len(name_tokens), len(dialog_tokens))
            if score > best_score:
                best_score = score
                best_match = dialog

        return best_match, best_score


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_component_lookup(raw_export: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Build {_id: component} lookup from dialogComponents array.

    TRAP 7: There is no 'componentMap'. Use dialogComponents array.
    """
    return {
        c["_id"]: c
        for c in raw_export.get("dialogComponents", [])
        if "_id" in c
    }


def _decode(value: Any) -> str:
    """URL-decode a string value. TRAP 8: messages and scripts are URL-encoded."""
    if not isinstance(value, str):
        return ""
    return urllib.parse.unquote(value)


def _get_message_text(component: dict[str, Any]) -> str:
    """Extract display text from a component's message array.

    TRAP 8: text is URL-encoded.
    Path: component.message[0].localeData.en.text
    """
    msg = component.get("message", [])
    if isinstance(msg, list) and msg:
        raw = msg[0].get("localeData", {}).get("en", {}).get("text", "")
        return _decode(raw)
    return ""


def _get_aiassist_context(ai_config: dict[str, Any]) -> str:
    """Extract system context from aiassist dynamicEntityConfig.

    TRAP 12: Two inconsistent key names — try both.
    """
    return ai_config.get("systemContext") or ai_config.get("system_context") or ""


def _parse_node_content(node_stub: dict[str, Any], component: dict[str, Any]) -> dict[str, Any]:
    """Extract type-specific content fields from a resolved component."""
    result: dict[str, Any] = {}
    node_type = node_stub.get("type", "")

    if node_type == fm.NODE_TYPE_SERVICE:
        ep = component.get("endPoint", {})
        protocol = ep.get("protocol", "https")
        host = ep.get("host", "")
        path = ep.get("path", "")
        result["service_url"] = f"{protocol}://{host}{path}" if host else None
        result["service_method"] = ep.get("method")
        result["service_request_body"] = component.get("payload")

    elif node_type == fm.NODE_TYPE_SCRIPT:
        raw_script = component.get("script", "")
        result["script_content"] = _decode(raw_script) if raw_script else None

    elif node_type == fm.NODE_TYPE_AGENT:
        ai = component.get("generativeAI", {}).get("dynamicEntityConfig", {})
        result["ai_assist_context"] = _get_aiassist_context(ai) or None
        result["ai_assist_entity_rules"] = ai.get("rules") or None
        result["ai_assist_tools"] = ai.get("dynamicEntities") or None
        result["ai_assist_exit_scenarios"] = ai.get("exitScenarios") or None

    elif node_type == fm.NODE_TYPE_LOGIC:
        # TRAP 11: conditions are on the NODE's transitions, not the component
        conditions = [
            t for t in node_stub.get("transitions", [])
            if "if" in t
        ]
        result["logic_conditions"] = conditions or None

    elif node_type == fm.NODE_TYPE_DIALOG_ACT:
        result["confirmation_prompt"] = _get_message_text(component) or None

    return result


def _parse_nodes(
    raw_nodes: list[dict[str, Any]],
    comp_lookup: dict[str, dict[str, Any]],
) -> list[CBMNode]:
    """Parse dialog nodes, resolving componentId → component content.

    TRAP 6: nodes are stubs — must resolve componentId.
    TRAP 7: use comp_lookup (built from dialogComponents), not componentMap.
    """
    nodes = []
    for stub in raw_nodes:
        comp_id = stub.get("componentId", "")
        component = comp_lookup.get(comp_id, {})

        # Extract type-specific content
        content = _parse_node_content(stub, component)

        node = CBMNode(
            node_id=stub.get("nodeId", stub.get("_id", "")),
            node_type=stub.get("type", "unknown"),
            name=component.get("name", ""),   # TRAP 6: name is in component, not stub
            component=component,
            transitions=stub.get("transitions", []),
            raw=stub,
            script_content=content.get("script_content"),
            service_url=content.get("service_url"),
            service_method=content.get("service_method"),
            service_request_body=content.get("service_request_body"),
            ai_assist_context=content.get("ai_assist_context"),
            ai_assist_entity_rules=content.get("ai_assist_entity_rules"),
            ai_assist_tools=content.get("ai_assist_tools"),
            ai_assist_exit_scenarios=content.get("ai_assist_exit_scenarios"),
            logic_conditions=content.get("logic_conditions"),
            confirmation_prompt=content.get("confirmation_prompt"),
        )
        nodes.append(node)
    return nodes


def _parse_dialogs(
    raw_dialogs: list[dict[str, Any]],
    comp_lookup: dict[str, dict[str, Any]],
) -> list[CBMDialog]:
    """Parse raw dialog array into CBMDialog objects.

    TRAP 5: dialog names are in localeData.en.name, not dialog.name.
    """
    dialogs = []
    for raw in raw_dialogs:
        locale_en = raw.get("localeData", {}).get("en", {})
        # TRAP 5: use localeData.en.name, fallback to lname
        name = locale_en.get("name") or raw.get("lname", "")
        short_desc = locale_en.get("shortDesc", "")

        raw_nodes = raw.get("nodes", [])
        dialog = CBMDialog(
            name=name,
            dialog_id=raw.get("_id", raw.get("dialogId", "")),
            short_desc=short_desc,
            nodes=_parse_nodes(raw_nodes, comp_lookup),
            raw=raw,
        )
        dialogs.append(dialog)
    return dialogs


def _parse_faqs(raw_export: dict[str, Any]) -> list[CBMFAQ]:
    """Parse FAQs.

    TRAP 2: FAQ array is at knowledgeTasks[0].faqs.faqs (double-nested).
    TRAP 9: FAQ answer is a list of {text, type, channel} — not a string.
    """
    knowledge_tasks = raw_export.get("knowledgeTasks", [])
    if not knowledge_tasks:
        return []

    parsed = []
    for kt in knowledge_tasks:
        faqs_container = kt.get("faqs", {})
        faq_array = (
            faqs_container.get("faqs", [])
            if isinstance(faqs_container, dict)
            else []
        )

        for raw in faq_array:
            # TRAP 9: answer is a list
            raw_answer = raw.get("answer", "")
            if isinstance(raw_answer, list) and raw_answer:
                answer_text = raw_answer[0].get("text", "")
            else:
                answer_text = str(raw_answer) if raw_answer else ""

            alt_questions = [
                aq.get("question", "")
                for aq in raw.get("alternateQuestions", [])
                if isinstance(aq, dict)
            ]

            faq = CBMFAQ(
                question=raw.get("question", ""),
                answer=answer_text,
                alternate_questions=alt_questions,
                response_type=raw.get("responseType", "message"),
                raw=raw,
            )
            parsed.append(faq)

    return parsed


def _parse_dialog_gpt(raw_export: dict[str, Any]) -> tuple[bool | None, str]:
    """Parse DialogGPT setting.

    TRAP 1: dialogGPTSettings is an ARRAY.
    Returns (enabled, model_name).
    """
    settings = raw_export.get("dialogGPTSettings", [])
    if not isinstance(settings, list) or not settings:
        return None, ""

    first = settings[0]
    llm_config = first.get("dialogGPTLLMConfig", {})
    enable = llm_config.get("enable")
    model = llm_config.get("defaultModel", "")

    if isinstance(enable, bool):
        return enable, model
    if isinstance(enable, str):
        return enable.lower() == "true", model
    return None, model


def _parse_llm_features(raw_export: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse LLM feature configuration."""
    llm_config = raw_export.get("llmConfiguration", [])
    if isinstance(llm_config, list) and llm_config:
        return llm_config[0].get("featureList", [])
    return []


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_bot_export(export_data: dict[str, Any]) -> CBMObject:
    """Parse a Kore.ai bot export JSON into a structured CBM object.

    Handles all 12 parser traps. See docs/parser_traps.md for details.

    Args:
        export_data: The raw bot export JSON (appDefinition.json content)

    Returns:
        CBMObject with all structural information extracted.
    """
    # TRAP 4: No botInfo key — bot name is at localeData.en.name
    locale_en = export_data.get("localeData", {}).get("en", {})
    bot_name = locale_en.get("name", "")
    bot_description = locale_en.get("description", "")
    bot_version = export_data.get("environmentVersionInfo", "")
    default_lang = export_data.get("defaultLanguage", "en")
    languages = export_data.get("supportedLanguages", [default_lang])

    # TRAP 7: No componentMap — build lookup from dialogComponents
    comp_lookup = _build_component_lookup(export_data)

    # Dialogs (TRAP 5, 6)
    raw_dialogs = export_data.get("dialogs", [])
    dialogs = _parse_dialogs(raw_dialogs, comp_lookup)

    # FAQs (TRAP 2, 9)
    faqs = _parse_faqs(export_data)

    # DialogGPT (TRAP 1)
    dialog_gpt_enabled, dialog_gpt_model = _parse_dialog_gpt(export_data)

    # LLM features
    llm_features = _parse_llm_features(export_data)

    # Bot-wide sections
    custom_dashboards = export_data.get("customDashboards", [])
    custom_variables = export_data.get("contentVariables", [])
    channels = export_data.get("channels", [])
    bot_events = export_data.get("botEvents", {})

    return CBMObject(
        bot_name=bot_name,
        bot_description=bot_description,
        bot_version=bot_version,
        default_language=default_lang,
        languages=languages if isinstance(languages, list) else [default_lang],
        dialogs=dialogs,
        faqs=faqs,
        dialog_gpt_enabled=dialog_gpt_enabled,
        dialog_gpt_model=dialog_gpt_model,
        llm_features=llm_features if isinstance(llm_features, list) else [],
        custom_dashboards=custom_dashboards if isinstance(custom_dashboards, list) else [],
        custom_variables=custom_variables if isinstance(custom_variables, list) else [],
        channels=channels if isinstance(channels, list) else [],
        bot_events=bot_events if isinstance(bot_events, dict) else {},
        raw_export=export_data,
    )


def parse_bot_export_file(file_path: str | Path) -> CBMObject:
    """Convenience: parse a bot export from a JSON file path."""
    path = Path(file_path)
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return parse_bot_export(data)
