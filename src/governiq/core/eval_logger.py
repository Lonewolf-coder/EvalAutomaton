"""Per-evaluation structured JSONL logger.

Writes one JSON object per line to data/logs/eval_{session_id}.jsonl.
Each entry: {"ts", "task_id", "level", "event", "detail", "raw"}

Used by the evaluation engine to write real-time structured logs of each
evaluation session for later UI display and audit trails.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_MAX_LINES = 10_000


class EvalLogger:
    """Per-evaluation JSONL logger.

    Attributes:
        session_id: Unique identifier for the evaluation session.
        _log_file: Path to the JSONL log file.
        _line_count: Current number of lines written (capped at _MAX_LINES).
    """

    def __init__(self, session_id: str, log_dir: Path) -> None:
        """Initialize the logger.

        Args:
            session_id: Unique identifier for this evaluation session.
            log_dir: Directory where the log file will be written.
        """
        self.session_id = session_id
        self._log_file = log_dir / f"eval_{session_id}.jsonl"
        log_dir.mkdir(parents=True, exist_ok=True)
        self._line_count = 0

    def log(
        self,
        task_id: str,
        level: str,
        event: str,
        detail: str = "",
        raw: dict | None = None,
    ) -> None:
        """Log a single event to the JSONL file.

        Args:
            task_id: The task that produced this event.
            level: Log level (e.g. "info", "warning", "error").
            event: Event type (e.g. "task_start", "bot_message", "error").
            detail: Human-readable description of the event.
            raw: Optional dictionary of raw data (e.g. full API response).

        If _MAX_LINES has been reached, this is a no-op.
        """
        if self._line_count >= _MAX_LINES:
            return
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "task_id": task_id,
            "level": level,
            "event": event,
            "detail": detail,
            "raw": raw or {},
        }
        try:
            with self._log_file.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry) + "\n")
            self._line_count += 1
        except Exception as exc:
            logger.warning("EvalLogger write failed: %s", exc)
