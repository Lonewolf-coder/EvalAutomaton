"""Universal Manifest Schema — Pydantic models.

The manifest is configuration only. It never executes logic.
A manifest written for Travel can be adapted for Medical by changing values —
no code changes. The engine knows six patterns; the manifest tells it everything else.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class EnginePattern(str, Enum):
    """The six patterns the engine knows. Every task maps to exactly one."""
    CREATE = "CREATE"
    CREATE_WITH_AMENDMENT = "CREATE_WITH_AMENDMENT"
    RETRIEVE = "RETRIEVE"
    MODIFY = "MODIFY"
    DELETE = "DELETE"
    EDGE_CASE = "EDGE_CASE"


class DialogNamePolicy(str, Enum):
    """How dialog names are matched against the CBM."""
    EXACT = "exact"
    CONTAINS = "contains"
    SEMANTIC = "semantic"


class ComplianceRequiredState(str, Enum):
    ENABLED = "enabled"
    DISABLED = "disabled"
    PRESENT = "present"


# ---------------------------------------------------------------------------
# Sub-schemas
# ---------------------------------------------------------------------------

class EntityDefinition(BaseModel):
    """A single entity the bot must collect during a task."""
    entity_key: str = Field(..., description="Must match the bot's entity name exactly")
    semantic_hint: str = Field(..., description="Natural language description for LLM driver")
    value_pool: list[str] = Field(
        default_factory=list,
        description="Realistic test values the driver can inject. Empty for cross-task ref tasks."
    )
    validation_required: bool = Field(default=False)
    validation_description: str | None = Field(default=None)


class AmendmentConfig(BaseModel):
    """Configuration for CREATE_WITH_AMENDMENT pattern."""
    target_entity: str = Field(..., description="Entity key to amend mid-conversation")
    amendment_utterance_template: str = Field(
        ...,
        description="Template for the amendment message. Use {amended_value} placeholder."
    )
    amended_value_pool: list[str] = Field(..., min_length=1)


class CrossTaskReference(BaseModel):
    """Declares which entity from a previous task a later task should use."""
    source_task_id: str = Field(..., description="Task ID that produced the record")
    source_record_alias: str = Field(..., description="Record alias (e.g. 'Booking1')")
    source_field: str = Field(..., description="Field name in the source record")


class StateAssertion(BaseModel):
    """Defines how to verify bot actions against the mock API."""
    enabled: bool = True
    verify_endpoint: str = Field(..., description="GET endpoint URL for verification")
    filter_field: str = Field(..., description="Field used to locate the record")
    field_assertions: dict[str, str] = Field(
        default_factory=dict,
        description="Map entity_key -> JSON path in API response"
    )
    expect_deletion: bool = Field(
        default=False,
        description="For DELETE pattern: expect record to be absent"
    )


class NegativeTest(BaseModel):
    """Edge case / negative test configuration."""
    invalid_value_pool: list[str] = Field(..., min_length=1)
    expected_error_pattern: str = Field(
        ..., description="Regex or keyword the bot's error response must contain"
    )
    requires_re_entry_prompt: bool = Field(default=False)


class RequiredNode(BaseModel):
    """A node that must exist in the dialog's CBM structure."""
    node_type: str = Field(..., description="e.g. 'aiassist', 'service', 'message', 'entity', 'form'")
    label: str = Field(..., description="Human-readable label for dashboard display")
    service_method: str | None = Field(default=None, description="For service nodes: GET, POST, PUT, DELETE")
    required: bool = Field(default=True)


class FAQItem(BaseModel):
    """A single FAQ the candidate must implement."""
    primary_question: str
    ground_truth_answer: str
    required_keywords: list[str] = Field(default_factory=list)
    alternate_questions: list[str] = Field(default_factory=list)


class FAQConfig(BaseModel):
    """FAQ evaluation configuration."""
    required_faqs: list[FAQItem] = Field(default_factory=list)
    min_alternate_questions: int = Field(default=2)
    semantic_similarity_threshold: float = Field(default=0.80)


class ComplianceCheck(BaseModel):
    """A single compliance check against the CBM structure."""
    check_id: str
    label: str = Field(..., description="Human-readable label")
    cbm_field: str = Field(..., description="Dot-path into CBM object")
    required_state: ComplianceRequiredState
    critical: bool = Field(default=False, description="Critical checks auto-fail if violated")
    tooltip: str = Field(default="", description="Plain-English explanation for evaluator")


class StateSeedingConfig(BaseModel):
    """Configuration for state seeding when Task 2 fails to create records."""
    enabled: bool = True
    schema_validation: bool = True
    seed_endpoint: str = Field(default="", description="POST endpoint for seeding")


class ScoringConfig(BaseModel):
    """Scoring weights and thresholds."""
    cbm_structural_weight: float = Field(default=0.40)
    webhook_functional_weight: float = Field(default=0.40)
    compliance_weight: float = Field(default=0.10)
    faq_weight: float = Field(default=0.10)
    pass_threshold: float = Field(default=0.70, description="Minimum overall score to pass")


class Tooltip(BaseModel):
    """Dashboard tooltip for a node type — declared in manifest, not engine."""
    node_type: str
    text: str


# ---------------------------------------------------------------------------
# Task Schema
# ---------------------------------------------------------------------------

class TaskDefinition(BaseModel):
    """Complete task definition. Every task maps to one engine pattern."""
    task_id: str = Field(..., description="Unique task identifier (e.g. 'task1', 'task2')")
    task_name: str = Field(..., description="Human-readable task name")
    pattern: EnginePattern
    dialog_name: str = Field(..., description="Expected dialog name in CBM")
    dialog_name_policy: DialogNamePolicy = Field(default=DialogNamePolicy.CONTAINS)

    # Entity collection (CREATE, CREATE_WITH_AMENDMENT, RETRIEVE, MODIFY)
    required_entities: list[EntityDefinition] = Field(default_factory=list)

    # Required nodes in the dialog's CBM structure
    required_nodes: list[RequiredNode] = Field(default_factory=list)

    # Amendment config (CREATE_WITH_AMENDMENT only)
    amendment_config: AmendmentConfig | None = None

    # Cross-task references (RETRIEVE, MODIFY, DELETE)
    cross_task_refs: dict[str, CrossTaskReference] = Field(default_factory=dict)

    # State assertion / API verification
    state_assertion: StateAssertion | None = None

    # Record alias for RuntimeContext caching
    record_alias: str | None = Field(default=None, description="e.g. 'Booking1', 'Booking2'")

    # Negative / edge case tests
    negative_tests: list[NegativeTest] = Field(default_factory=list)

    # Welcome-specific fields
    required_greeting_text: str | None = None
    required_menu_items: list[str] = Field(default_factory=list)

    # Conversation starter override
    conversation_starter: str | None = None

    # Co-referencing test: provide two entities in one utterance
    co_reference_test: bool = Field(default=False)

    # Modifiable fields for MODIFY pattern
    modifiable_fields: list[str] = Field(default_factory=list)
    modified_value_pool: dict[str, list[str]] = Field(default_factory=dict)

    # Scoring weight override for this task
    weight: float = Field(default=1.0)


# ---------------------------------------------------------------------------
# Top-Level Manifest
# ---------------------------------------------------------------------------

class Manifest(BaseModel):
    """GovernIQ Universal Manifest — complete assessment configuration.

    This is configuration only. It never executes logic. The engine reads
    this to know what patterns to run, against which entities, through which
    API, with which assertions.
    """
    manifest_id: str
    manifest_version: str = Field(default="1.0")
    assessment_name: str = Field(..., description="e.g. 'Medical Appointment Bot - Basic'")
    assessment_type: str = Field(..., description="e.g. 'medical', 'travel', 'hr'")
    description: str = Field(default="")

    # Bot connection
    webhook_url: str = Field(default="", description="Candidate's bot webhook URL")
    mock_api_base_url: str = Field(default="", description="Candidate's mockapi.io base URL")

    # Conversation initiation
    conversation_starter: str = Field(
        default="Hi",
        description="Fallback if LLM cannot generate an opening. LLM is primary."
    )

    # Tasks — ordered list
    tasks: list[TaskDefinition] = Field(..., min_length=1)

    # FAQ configuration
    faq_config: FAQConfig = Field(default_factory=FAQConfig)

    # Compliance checks
    compliance_checks: list[ComplianceCheck] = Field(default_factory=list)

    # Scoring
    scoring_config: ScoringConfig = Field(default_factory=ScoringConfig)

    # State seeding
    state_seeding_config: StateSeedingConfig = Field(default_factory=StateSeedingConfig)

    # Tooltips for CBM Map (declared here, not in engine code)
    tooltips: list[Tooltip] = Field(default_factory=list)

    # Metadata
    created_by: str = Field(default="")
    notes: str = Field(default="")

    def get_task(self, task_id: str) -> TaskDefinition | None:
        """Look up a task by its ID."""
        for task in self.tasks:
            if task.task_id == task_id:
                return task
        return None

    def get_tasks_by_pattern(self, pattern: EnginePattern) -> list[TaskDefinition]:
        """Return all tasks using a given pattern."""
        return [t for t in self.tasks if t.pattern == pattern]
