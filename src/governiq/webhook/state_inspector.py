"""State Inspector — Verifies what the bot DID, not what it SAID.

The State Inspector checks what data actually ended up in the database.
This is entirely separate from what the bot SAID during the conversation.
Both matter. A bot can say all the right things and still fail to persist
data correctly.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from ..core.manifest import StateAssertion, TaskDefinition
from ..core.runtime_context import RuntimeContext, TaskRecord
from ..core.scoring import CheckResult, CheckStatus, EvidenceCard, EvidenceCardColor

logger = logging.getLogger(__name__)


class StateInspector:
    """Inspects the candidate's mock API to verify data persistence."""

    def __init__(self, timeout: float = 10.0, retry_count: int = 2):
        self.timeout = timeout
        self.retry_count = retry_count
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if not self._client:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def verify_task(
        self,
        task: TaskDefinition,
        context: RuntimeContext,
    ) -> tuple[list[CheckResult], list[EvidenceCard]]:
        """Verify a task's state assertions against the mock API.

        Returns (checks, evidence_cards).
        """
        checks: list[CheckResult] = []
        cards: list[EvidenceCard] = []

        assertion = task.state_assertion
        if not assertion or not assertion.enabled:
            return checks, cards

        # Get the record to verify from RuntimeContext
        record = context.get_record(task.record_alias or "")
        if not record:
            checks.append(CheckResult(
                check_id=f"state.{task.task_id}.no_record",
                task_id=task.task_id,
                pipeline="state_inspector",
                label="Record available for verification",
                status=CheckStatus.FAIL,
                details="No cached record found in RuntimeContext.",
                score=0.0,
            ))
            return checks, cards

        # Determine the filter value
        filter_value = record.get_field(assertion.filter_field)
        if not filter_value:
            checks.append(CheckResult(
                check_id=f"state.{task.task_id}.no_filter",
                task_id=task.task_id,
                pipeline="state_inspector",
                label=f"Filter field '{assertion.filter_field}' available",
                status=CheckStatus.FAIL,
                details=f"Field '{assertion.filter_field}' not found in cached record.",
                score=0.0,
            ))
            return checks, cards

        # Query the mock API
        api_record = await self._fetch_record(
            assertion.verify_endpoint, assertion.filter_field, filter_value
        )

        if assertion.expect_deletion:
            # DELETE pattern: expect record to be absent
            if api_record is None:
                checks.append(CheckResult(
                    check_id=f"state.{task.task_id}.deletion",
                    task_id=task.task_id,
                    pipeline="state_inspector",
                    label="Record deleted from API",
                    status=CheckStatus.PASS,
                    details=f"Record with {assertion.filter_field}='{filter_value}' not found — deletion confirmed.",
                    score=1.0,
                ))
                cards.append(EvidenceCard(
                    card_id=f"state.{task.task_id}.deleted",
                    task_id=task.task_id,
                    title=f"Cancellation Confirmed — record deleted from database",
                    content=f"Record with {assertion.filter_field}='{filter_value}' no longer exists.",
                    color=EvidenceCardColor.GREEN,
                    pipeline="state_inspector",
                ))
            else:
                checks.append(CheckResult(
                    check_id=f"state.{task.task_id}.deletion",
                    task_id=task.task_id,
                    pipeline="state_inspector",
                    label="Record deleted from API",
                    status=CheckStatus.FAIL,
                    details=f"Record still present — cancellation FAILED.",
                    score=0.0,
                ))
                cards.append(EvidenceCard(
                    card_id=f"state.{task.task_id}.not_deleted",
                    task_id=task.task_id,
                    title="Cancellation FAILED — record still present in database",
                    content=f"Record with {assertion.filter_field}='{filter_value}' still exists.",
                    color=EvidenceCardColor.RED,
                    pipeline="state_inspector",
                ))
        else:
            # Non-delete: verify record exists and fields match
            if api_record is None:
                checks.append(CheckResult(
                    check_id=f"state.{task.task_id}.exists",
                    task_id=task.task_id,
                    pipeline="state_inspector",
                    label="Record found in API",
                    status=CheckStatus.FAIL,
                    details=f"Record with {assertion.filter_field}='{filter_value}' not found in API.",
                    score=0.0,
                ))
                cards.append(EvidenceCard(
                    card_id=f"state.{task.task_id}.not_found",
                    task_id=task.task_id,
                    title="Record NOT Found in Database",
                    content=f"Expected record with {assertion.filter_field}='{filter_value}' not found.",
                    color=EvidenceCardColor.RED,
                    pipeline="state_inspector",
                ))
            else:
                # Verify field assertions
                field_results = self._verify_fields(
                    task.task_id, api_record, record, assertion
                )
                checks.extend(field_results)

                all_match = all(c.status == CheckStatus.PASS for c in field_results)
                detail_lines = []
                for k, v in record.fields.items():
                    api_path = assertion.field_assertions.get(k, k)
                    api_val = self._resolve_path(api_record, api_path)
                    match = str(api_val).lower() == str(v).lower() if api_val else False
                    status_icon = "PASS" if match else "FAIL"
                    detail_lines.append(f"  {k}: expected='{v}' actual='{api_val}' [{status_icon}]")

                cards.append(EvidenceCard(
                    card_id=f"state.{task.task_id}.verified",
                    task_id=task.task_id,
                    title=f"{'Confirmed in Database' if all_match else 'Data Mismatch'}",
                    content="\n".join(detail_lines),
                    color=EvidenceCardColor.GREEN if all_match else EvidenceCardColor.RED,
                    pipeline="state_inspector",
                    details={"api_record": api_record, "expected": record.fields},
                ))

        return checks, cards

    async def _fetch_record(
        self, endpoint: str, filter_field: str, filter_value: Any
    ) -> dict[str, Any] | None:
        """Fetch a record from the mock API."""
        client = await self._get_client()
        last_error = None

        for attempt in range(self.retry_count + 1):
            try:
                # Try GET with query parameter
                response = await client.get(endpoint)
                response.raise_for_status()
                data = response.json()

                # API may return an array — find matching record
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict):
                            if str(item.get(filter_field, "")).lower() == str(filter_value).lower():
                                return item
                    return None
                elif isinstance(data, dict):
                    if str(data.get(filter_field, "")).lower() == str(filter_value).lower():
                        return data
                    return None

            except Exception as e:
                last_error = e
                logger.warning("API fetch attempt %d failed: %s", attempt + 1, e)

        if last_error:
            logger.error("All API fetch attempts failed: %s", last_error)
        return None

    def _verify_fields(
        self,
        task_id: str,
        api_record: dict[str, Any],
        expected_record: TaskRecord,
        assertion: StateAssertion,
    ) -> list[CheckResult]:
        """Verify expected fields against the API record."""
        checks = []
        for entity_key, expected_value in expected_record.fields.items():
            api_path = assertion.field_assertions.get(entity_key, entity_key)
            actual_value = self._resolve_path(api_record, api_path)

            match = (
                actual_value is not None
                and str(actual_value).lower() == str(expected_value).lower()
            )
            checks.append(CheckResult(
                check_id=f"state.{task_id}.field.{entity_key}",
                task_id=task_id,
                pipeline="state_inspector",
                label=f"API field '{entity_key}' matches expected value",
                status=CheckStatus.PASS if match else CheckStatus.FAIL,
                details=(
                    f"Expected: '{expected_value}', Actual: '{actual_value}'"
                ),
                score=1.0 if match else 0.0,
            ))
        return checks

    @staticmethod
    def _resolve_path(data: dict[str, Any], path: str) -> Any:
        """Resolve a dot-path in a dict."""
        current = data
        for part in path.split("."):
            if isinstance(current, dict):
                current = current.get(part)
            else:
                return None
        return current

    async def seed_state(
        self,
        endpoint: str,
        record_fields: dict[str, Any],
    ) -> bool:
        """Seed state by POSTing a synthetic record to the mock API.

        Used when Task 2 fails to create records through conversation.
        """
        client = await self._get_client()
        try:
            response = await client.post(endpoint, json=record_fields)
            response.raise_for_status()
            return True
        except Exception as e:
            logger.error("State seeding failed: %s", e)
            return False

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
