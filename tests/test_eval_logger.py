"""Tests for EvalLogger — per-evaluation structured JSONL logging."""

import json
from pathlib import Path

import pytest

from governiq.core.eval_logger import EvalLogger


def test_eval_logger_writes_jsonl(tmp_path):
    """EvalLogger writes one JSON object per line to eval_{session_id}.jsonl."""
    logger = EvalLogger(session_id="test-123", log_dir=tmp_path)
    logger.log(task_id="task1", level="info", event="task_start", detail="Starting task1")
    logger.log(
        task_id="task1",
        level="info",
        event="bot_message",
        detail="Hello",
        raw={"text": "Hello"},
    )

    log_file = tmp_path / "eval_test-123.jsonl"
    assert log_file.exists()
    lines = log_file.read_text().strip().split("\n")
    assert len(lines) == 2
    entry = json.loads(lines[0])
    assert entry["task_id"] == "task1"
    assert entry["event"] == "task_start"
    assert "ts" in entry
    assert entry["raw"] == {}

    entry2 = json.loads(lines[1])
    assert entry2["raw"] == {"text": "Hello"}


def test_eval_logger_none_is_noop(tmp_path):
    """When eval_logger is None, calling log() should not crash.

    This test confirms the EvalLogger constructor works with no writes if no events logged.
    Callers guard with 'if self._eval_logger'.
    """
    logger = EvalLogger(session_id="empty-456", log_dir=tmp_path)
    log_file = tmp_path / "eval_empty-456.jsonl"
    assert not log_file.exists()  # file not created until first write
