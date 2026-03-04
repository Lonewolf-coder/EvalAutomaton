"""Engine Patterns — The six patterns the engine knows.

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
from ..core.manifest import EnginePattern


PATTERN_REGISTRY: dict[EnginePattern, type[PatternExecutor]] = {
    EnginePattern.CREATE: CreatePattern,
    EnginePattern.CREATE_WITH_AMENDMENT: CreateWithAmendmentPattern,
    EnginePattern.RETRIEVE: RetrievePattern,
    EnginePattern.MODIFY: ModifyPattern,
    EnginePattern.DELETE: DeletePattern,
    EnginePattern.EDGE_CASE: EdgeCasePattern,
}


def get_pattern_executor(pattern: EnginePattern) -> type[PatternExecutor]:
    """Get the executor class for a given engine pattern."""
    return PATTERN_REGISTRY[pattern]
