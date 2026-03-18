"""Engine Patterns — all patterns the engine knows.

Every task in every manifest is assigned one pattern. The manifest configures
how the pattern runs for that specific task. The pattern logic itself never changes.
"""

from .base import PatternExecutor, PatternResult
from .create import CreatePattern
from .create_with_amendment import CreateWithAmendmentPattern
from .retrieve import RetrievePattern
from .modify import ModifyPattern
from .delete import DeletePattern
from .edge_case import EdgeCasePattern
from .welcome import WelcomePattern
# Advanced-assessment patterns
from .interruption import InterruptionPattern
from .language import LanguagePattern
from .form import FormPattern
from .survey import SurveyPattern
from .cbm_only import CbmOnlyPattern
from ..core.manifest import EnginePattern


PATTERN_REGISTRY: dict[EnginePattern, type[PatternExecutor]] = {
    # Core patterns
    EnginePattern.CREATE: CreatePattern,
    EnginePattern.CREATE_WITH_AMENDMENT: CreateWithAmendmentPattern,
    EnginePattern.RETRIEVE: RetrievePattern,
    EnginePattern.MODIFY: ModifyPattern,
    EnginePattern.DELETE: DeletePattern,
    EnginePattern.EDGE_CASE: EdgeCasePattern,
    EnginePattern.WELCOME: WelcomePattern,
    # Advanced patterns
    EnginePattern.INTERRUPTION: InterruptionPattern,
    EnginePattern.LANGUAGE: LanguagePattern,
    EnginePattern.FORM: FormPattern,
    EnginePattern.SURVEY: SurveyPattern,
    EnginePattern.CBM_ONLY: CbmOnlyPattern,
}


def get_pattern_executor(pattern: EnginePattern) -> type[PatternExecutor]:
    """Get the executor class for a given engine pattern."""
    if pattern not in PATTERN_REGISTRY:
        raise KeyError(
            f"No executor registered for pattern '{pattern}'. "
            f"Registered patterns: {sorted(p.value for p in PATTERN_REGISTRY)}"
        )
    return PATTERN_REGISTRY[pattern]
