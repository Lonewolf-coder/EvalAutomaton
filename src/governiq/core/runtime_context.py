"""RuntimeContext — Cross-task state management.

Tasks share data through RuntimeContext only. Entity values from Task 2 are
reused in Tasks 3 and 4. This mirrors how a human QA tester walks through
the system and prevents unfair cascade failures.

RuntimeContext is written to disk and read explicitly by tasks that declare
a cross-task entity reference.
"""

from __future__ import annotations

import json
import os
import random
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class TaskRecord:
    """A record produced by a task and cached for later tasks."""
    record_alias: str              # e.g. 'Booking1', 'Booking2'
    task_id: str                   # Task that produced this record
    fields: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    seeded: bool = False           # True if record was state-seeded, not created through conversation

    def get_field(self, field_name: str) -> Any:
        return self.fields.get(field_name)


@dataclass
class ConversationTranscript:
    """Full transcript of a webhook conversation for a task."""
    task_id: str
    turns: list[dict[str, str]] = field(default_factory=list)
    started_at: str = ""
    completed_at: str = ""

    def add_turn(self, role: str, content: str) -> None:
        self.turns.append({"role": role, "content": content, "timestamp": _now()})

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "turns": self.turns,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }


@dataclass
class RuntimeContext:
    """Central state shared across tasks during an evaluation session.

    This is the ONLY cross-task data channel. Components communicate through
    this object and result JSON files only.
    """
    session_id: str
    candidate_id: str = ""
    manifest_id: str = ""
    started_at: str = ""

    # Cached task records (keyed by record_alias)
    records: dict[str, TaskRecord] = field(default_factory=dict)

    # Conversation transcripts (keyed by task_id)
    transcripts: dict[str, ConversationTranscript] = field(default_factory=dict)

    # Entity value selections (keyed by task_id.entity_key)
    selected_values: dict[str, str] = field(default_factory=dict)

    # Task results (keyed by task_id)
    task_results: dict[str, dict[str, Any]] = field(default_factory=dict)

    # ---------------------------------------------------------------------------
    # Record management
    # ---------------------------------------------------------------------------

    def cache_record(self, record: TaskRecord) -> None:
        """Cache a task record for later cross-task reference."""
        self.records[record.record_alias] = record

    def get_record(self, record_alias: str) -> TaskRecord | None:
        """Retrieve a cached record by alias."""
        return self.records.get(record_alias)

    def get_cross_task_value(
        self, source_task_id: str, record_alias: str, field_name: str
    ) -> Any | None:
        """Resolve a cross-task entity reference."""
        record = self.records.get(record_alias)
        if record and record.task_id == source_task_id:
            return record.get_field(field_name)
        return None

    # ---------------------------------------------------------------------------
    # Entity value selection
    # ---------------------------------------------------------------------------

    def select_value(self, task_id: str, entity_key: str, value_pool: list[str]) -> str:
        """Select a value from the pool for this entity. Cache the selection."""
        key = f"{task_id}.{entity_key}"
        if key in self.selected_values:
            return self.selected_values[key]
        value = random.choice(value_pool)
        self.selected_values[key] = value
        return value

    def get_selected_value(self, task_id: str, entity_key: str) -> str | None:
        """Get a previously selected value."""
        return self.selected_values.get(f"{task_id}.{entity_key}")

    # ---------------------------------------------------------------------------
    # Transcript management
    # ---------------------------------------------------------------------------

    def start_transcript(self, task_id: str) -> ConversationTranscript:
        """Start a new conversation transcript for a task."""
        transcript = ConversationTranscript(task_id=task_id, started_at=_now())
        self.transcripts[task_id] = transcript
        return transcript

    def get_transcript(self, task_id: str) -> ConversationTranscript | None:
        return self.transcripts.get(task_id)

    # ---------------------------------------------------------------------------
    # Task results
    # ---------------------------------------------------------------------------

    def set_task_result(self, task_id: str, result: dict[str, Any]) -> None:
        self.task_results[task_id] = result

    def get_task_result(self, task_id: str) -> dict[str, Any] | None:
        return self.task_results.get(task_id)

    # ---------------------------------------------------------------------------
    # Persistence
    # ---------------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "candidate_id": self.candidate_id,
            "manifest_id": self.manifest_id,
            "started_at": self.started_at,
            "records": {
                alias: {
                    "record_alias": r.record_alias,
                    "task_id": r.task_id,
                    "fields": r.fields,
                    "created_at": r.created_at,
                    "seeded": r.seeded,
                }
                for alias, r in self.records.items()
            },
            "selected_values": self.selected_values,
            "task_results": self.task_results,
            "transcripts": {
                tid: t.to_dict() for tid, t in self.transcripts.items()
            },
        }

    def save(self, directory: str | Path) -> Path:
        """Persist RuntimeContext to disk as JSON."""
        dir_path = Path(directory)
        dir_path.mkdir(parents=True, exist_ok=True)
        file_path = dir_path / f"context_{self.session_id}.json"
        with file_path.open("w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)
        return file_path

    @classmethod
    def load(cls, file_path: str | Path) -> RuntimeContext:
        """Load a RuntimeContext from a persisted JSON file."""
        path = Path(file_path)
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        ctx = cls(
            session_id=data["session_id"],
            candidate_id=data.get("candidate_id", ""),
            manifest_id=data.get("manifest_id", ""),
            started_at=data.get("started_at", ""),
        )
        ctx.selected_values = data.get("selected_values", {})
        ctx.task_results = data.get("task_results", {})

        for alias, rec_data in data.get("records", {}).items():
            ctx.records[alias] = TaskRecord(
                record_alias=rec_data["record_alias"],
                task_id=rec_data["task_id"],
                fields=rec_data.get("fields", {}),
                created_at=rec_data.get("created_at", ""),
                seeded=rec_data.get("seeded", False),
            )

        return ctx


def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"
