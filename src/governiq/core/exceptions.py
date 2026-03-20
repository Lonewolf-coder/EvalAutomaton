"""Domain exceptions for the EvalAutomaton engine."""


class EvaluationHaltedError(Exception):
    """Raised when an evaluation must stop due to an unrecoverable external error.

    Attributes:
        reason: Human-readable description of why the evaluation halted.
        task_id: The task that was running when the error occurred.
        retriable: True if retrying after fixing the issue may succeed (e.g. rate limit).
                   False if the error requires a config fix (e.g. invalid API key).
    """

    def __init__(self, reason: str, task_id: str, retriable: bool = True) -> None:
        super().__init__(reason)
        self.reason = reason
        self.task_id = task_id
        self.retriable = retriable
