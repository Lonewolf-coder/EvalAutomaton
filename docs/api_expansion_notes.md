# Kore.ai API Expansion — Dev Team Research Notes

These notes document findings from the analytics API research sprint. They serve as
the canonical reference for anyone extending or debugging the analytics pipeline.

---

## 1. Auth Header Discrepancy

Two authentication header styles exist depending on the API tier:

| Tier | Header | Used by |
|---|---|---|
| Webhook / Bot APIs | `Authorization: Bearer {token}` | `_api_get`, `_api_post` (existing) |
| Analytics / Public APIs | `auth: {token}` | `_api_post_kore`, `_api_get_kore` (new) |

The bearer token itself is the same JWT — only the header name differs. The analytics-tier
APIs silently reject `Authorization: Bearer` requests (often HTTP 401 or empty response).
**Always use `_api_post_kore` / `_api_get_kore` for analytics endpoints.**

---

## 2. Analytics Types (`getAnalytics`)

**Endpoint:** `POST /api/public/bot/{bot_id}/getAnalytics`
**Auth:** `auth: {token}`

| `type` value | Description |
|---|---|
| `successintent` | Utterances that matched an intent successfully |
| `failintent` | Utterances that failed to match any intent |
| `unhandledutterance` | Utterances outside any known dialog context |
| `tasksuccess` | Tasks that completed successfully end-to-end |
| `taskfailure` | Tasks that failed or were abandoned |

**Important:** Type values are singular (`unhandledutterance`, not `unhandledutterances`).

### Request shape:
```json
{
  "type": "failintent",
  "filters": {
    "from": "2026-01-01T00:00:00.000Z",
    "to":   "2026-03-31T23:59:59.000Z",
    "sessionId": "optional-session-id"
  },
  "sort": {"order": "desc", "by": "timestamp"},
  "limit": 50
}
```

### Response item fields:
`_id`, `messageId`, `sessionId`, `utterance`, `intent`, `taskName`, `taskId`,
`userId`, `channelUId`, `language`, `timestamp`, `channel`, `isAmbiguous`,
`ambiguousIntents`, `winningIntent`, `flow`

### Pagination:
Response includes `moreAvailable: bool`. Current implementation ignores pagination
(retrieves first page only). Future work: implement cursor-based pagination for large datasets.

---

## 3. Conversation Messages (`getMessages`)

**Endpoint:** `POST /api/public/bot/{bot_id}/getMessages`
**Auth:** `auth: {token}`

```json
{
  "sessionId": ["session-id-here"],
  "userId": "eval-req-post-{uuid}",
  "limit": 100,
  "includeTraceId": "true"
}
```

Both `sessionId` (array) and `userId` are required for session-level filtering.

### Session ID correlation:
- `_kore_session_id` — Kore's internal session ID, pinned from the first webhook response
  (`response.get("sessionId")` in `KoreWebhookClient`). Resets on `start_session()`.
- `_from_id` — The userId used during evaluation: `eval-req-post-{uuid}`. Set at session
  start in `KoreWebhookClient.__init__`.

Both values are captured per-task in `_run_webhook_pipeline` → `task_sessions` dict.

---

## 4. Find Intent (`findIntent`)

**Endpoint:** `POST /api/v1.1/rest/bot/{bot_id}/findIntent?fetchConfiguredTasks=false`
**Auth:** `auth: {token}`
**Note:** Uses v1.1 (not v1), and requires `fetchConfiguredTasks=false` as a query param.

```json
{"input": "I want to book a flight", "streamName": "MyBotName"}
```

### Response fields:
- `result`: `"successintent"` | `"failintent"` | `"ambiguousintent"`
- `intent.name`: matched intent name
- `ambiguousIntents`: list of candidates when result is `ambiguousintent`
- `nlProcessing`: detailed NLP processing trace

Used by `_run_nlp_preflight` in the engine — runs before the webhook pipeline.
Results are appended as `weight=0.0` CBM checks (informational, do not affect scoring).

---

## 5. Batch Testing API

**List suites:** `GET /api/public/bot/{bot_id}/testsuite` — `auth:` header
**Run suite:** `POST /api/public/bot/{bot_id}/testsuite/{suiteName}/run`
  Body: `{"streamId": stream_id}`
**Get results:** `GET /api/public/bot/{bot_id}/testsuite/{suiteName}/run/{runId}/results`
  Params: `{"streamId": stream_id}`

### Potential future integration:
Batch test suites could be auto-generated from manifest `entity value_pools`. Each
unique combination of entity values could become a test case, enabling fully automated
regression testing. Currently, batch testing methods are implemented but not wired into
the evaluation pipeline — they are available for manual use via `KoreAPIClient`.

---

## 6. Known Gaps and Future Work

| Gap | Notes |
|---|---|
| Pagination | `moreAvailable` flag not handled — only first page of results is retrieved |
| Rate limiting | HTTP 429 handling not implemented; add retry with backoff on 429 |
| `create_with_amendment.py` / `delete.py` / `edge_case.py` | These pattern executors do not currently receive `kore_api` (only CREATE, RETRIEVE, MODIFY do). Extend in a future iteration. |
| Conversation Testing assertions | No direct API found for asserting conversation outcomes. Batch Testing is the closest equivalent. |
| `asyncio.gather` result ordering | Analytics pipeline assumes result order matches input order — valid for `asyncio.gather` but document explicitly for maintainers. |
| `bot_name` for `find_intent` | Engine extracts `bot_name` via `getattr(cbm, "bot_name", "")`. Verify `CBMObject` exposes this attribute; fallback to empty string currently. |

---

## 7. Implementation Notes

- All new analytics methods are **non-fatal**: every method wraps calls in `try/except`
  and returns `{"error": str(e)}` rather than raising.
- Analytics `CheckResult` entries use `weight=0.0` — they **never contribute to scoring**.
- The analytics pipeline runs **after** the webhook pipeline completes, using the session IDs
  captured during webhook execution.
- `_ANALYTICS_TYPES` is defined as a class-level attribute on `KoreAPIClient` to avoid
  duplication between `get_all_analytics_for_session` and any future iteration logic.
