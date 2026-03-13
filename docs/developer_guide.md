# GovernIQ — Developer Guide

## Overview

GovernIQ is a domain-agnostic automated evaluation platform for Kore.ai XO bot certification. It evaluates candidate-built bots against a **manifest** — a JSON configuration that describes what to test, in what order, and against which APIs. The evaluation engine has no knowledge of any domain (medical, travel, banking, etc.). All domain knowledge lives exclusively in the manifest.

---

## Prerequisites

- Python 3.11+
- pip

---

## Local Setup

```bash
# 1. Clone the repository
git clone <repo-url>
cd EvalAutomaton

# 2. Install dependencies
pip install -r requirements.txt

# 3. Create data directories
mkdir -p data/submissions data/snapshots data/blueprints data/manifests data/fingerprints

# 4. Set environment variables (copy and edit)
cp .env.example .env

# 5. Start the development server
PYTHONPATH=src uvicorn governiq.main:app --reload --port 8000
```

The app is accessible at `http://localhost:8000`.

- Admin portal: `http://localhost:8000/admin`
- Candidate portal: `http://localhost:8000/candidate`
- API docs: `http://localhost:8000/docs`

---

## Running Tests

```bash
# All tests
PYTHONPATH=src python3 -m pytest tests/ -q

# Specific test file
PYTHONPATH=src python3 -m pytest tests/test_manifest.py -v

# With coverage
PYTHONPATH=src python3 -m pytest tests/ --cov=governiq --cov-report=term-missing
```

Expected baseline: **88 passed, 5 skipped** (the 5 skipped tests are pending the manifest co-authoring session).

---

## Project Structure

```
EvalAutomaton/
├── src/governiq/
│   ├── main.py                  # FastAPI app entry point, route registration
│   ├── core/
│   │   ├── manifest.py          # Pydantic manifest schema (Manifest, TaskDefinition, etc.)
│   │   ├── manifest_validator.py # MD-01–MD-12 defect detection rules
│   │   ├── engine.py            # Evaluation engine orchestrator
│   │   ├── scoring.py           # Score computation (webhook 80%, FAQ 10%, compliance 10%)
│   │   ├── runtime_context.py   # Cross-task entity storage (RuntimeContext)
│   │   └── llm_config.py        # LLM provider config (Claude / LM Studio)
│   ├── cbm/
│   │   ├── parser.py            # Kore.ai bot export parser → CBMObject
│   │   ├── field_map.py         # Confirmed JSON field paths from real bot exports
│   │   ├── evaluator.py         # CBM compliance checks (structural audit, no scoring)
│   │   └── blueprint.py         # Human-readable bot structure summary
│   ├── patterns/                # Six evaluation patterns (one file each)
│   │   ├── create.py            # CREATE — POST + entity collection
│   │   ├── create_with_amendment.py  # CREATE_WITH_AMENDMENT
│   │   ├── retrieve.py          # RETRIEVE — GET via cross-task ref
│   │   ├── modify.py            # MODIFY — PUT/PATCH
│   │   ├── delete.py            # DELETE
│   │   └── edge_case.py         # EDGE_CASE — negative input validation
│   ├── webhook/
│   │   └── state_inspector.py   # Mock API caller, CRUD snapshot capture
│   ├── plagiarism/
│   │   ├── fingerprint.py       # SHA-256 fingerprint from raw bot export JSON
│   │   └── detector.py          # Risk comparison against prior submissions
│   ├── admin/
│   │   └── routes.py            # Admin portal routes (manifest CRUD, submission review)
│   ├── candidate/
│   │   └── routes.py            # Candidate portal routes (submit, history, comms)
│   ├── api/
│   │   └── routes.py            # REST API routes (/api/v1/)
│   └── templates/               # Jinja2 HTML templates
├── manifests/                   # Active assessment manifests (JSON)
│   ├── archived/                # Archived old manifests
│   └── schema/                  # JSON Schema reference file
├── tests/                       # pytest test suite
├── docs/                        # Documentation (you are here)
├── data/                        # Runtime data (gitignored)
│   ├── submissions/             # Submission tree JSON per submission_id
│   ├── snapshots/               # CRUD evidence per session
│   ├── blueprints/              # CBM blueprints per session
│   ├── manifests/               # Dual-saved manifest copies
│   └── fingerprints/            # Plagiarism fingerprints per assessment_type
└── requirements.txt
```

---

## Architecture

### Core Principle: Engine as Pattern Executor

The evaluation engine knows exactly **six patterns**. The manifest configures everything else. This means:
- Adding a new assessment type (Medical, Travel, Banking, HR…) costs zero engine code
- Domain knowledge belongs exclusively in the manifest
- The engine never contains the words "flight", "appointment", "loan", or any other domain concept

### Dual-Pipeline Evaluation

Every bot submission runs two completely independent pipelines:

```
Bot Export (.zip)
├── Pipeline A: CBM Audit
│   ├── CBM Parser → CBMObject (dialogs, nodes, FAQs)
│   ├── Compliance checks against manifest rules
│   └── Output: cbm_result (weight = 0.0 — informational only)
│
└── Pipeline B: Webhook Journey
    ├── Conversation Driver (LLM-powered)
    ├── Intent-Reactive Injection of entities
    ├── State Inspector: mock API calls after each task
    └── Output: webhook_result (weight = 0.80)

Final Score = (webhook × 0.80) + (faq × 0.10) + (compliance × 0.10)
```

CBM weight is 0.0 — it is purely informational and never affects the score.

### The Six Engine Patterns

| Pattern | What It Tests |
|---------|--------------|
| `CREATE` | Collect entities via conversation → POST to API → verify record exists |
| `CREATE_WITH_AMENDMENT` | Same as CREATE but mid-conversation driver changes one entity value |
| `RETRIEVE` | Inject an identifier from a prior task → GET API → verify bot returns correct data |
| `MODIFY` | Retrieve existing record → change one field → PUT API → verify change persisted |
| `DELETE` | Cancel/delete a record by ID → DELETE API → verify 404 or removal from list |
| `EDGE_CASE` | Inject invalid input → verify bot's error message matches expected pattern |

### RuntimeContext: Cross-Task Entity Sharing

Each task runs in its own isolated conversation session. State is shared between tasks only through RuntimeContext — written to disk and read explicitly by tasks that declare a `cross_task_reference`.

```
Task 1 (CREATE) → stores → RuntimeContext.records["Booking1"]
Task 3 (RETRIEVE) → reads → RuntimeContext.records["Booking1"]["contactNumber"]
```

---

## Adding a New Assessment Type

No engine code changes required. Just create a new manifest:

1. Navigate to `http://localhost:8000/admin/manifest/new`
2. Fill in the manifest builder form (see `docs/manifest_builder_guide.md`)
3. Add tasks using the appropriate patterns
4. Add FAQs and compliance checks
5. Save → manifest file created in `manifests/`

The engine auto-discovers manifests in the `manifests/` directory.

---

## Adding a New Engine Pattern

This is rare — it requires an engine code change. Only do this if the six existing patterns genuinely cannot cover the scenario.

1. Create `src/governiq/patterns/<pattern_name>.py`
2. Add the pattern to `EnginePattern` enum in `src/governiq/core/manifest.py`
3. Register the pattern in the engine dispatcher (`src/governiq/core/engine.py`)
4. Add pattern-specific config model in `manifest.py` if needed
5. Add to JSON Schema in `manifests/schema/manifest_schema.json`
6. Update `admin_manifest_editor.html` pattern dropdown
7. Write tests

---

## CBM Parser

The parser reads Kore.ai XO bot export files (`appDefinition.json`) and produces a `CBMObject`.

Key confirmed field paths (see `docs/bot_export_field_guide.md` for full reference):

```python
# Bot name
export_data["localeData"]["en"]["name"]

# Dialog name (NOT dialog["name"] — that field is always empty)
dialog["localeData"]["en"]["name"]

# Node content — nodes contain ONLY references; resolve via componentId
component = component_lookup[node["componentId"]]

# FAQ answer — it's a LIST, not a string
faq["answer"][0]["text"]

# AI Assist system context — TWO possible key names
ai.get("systemContext") or ai.get("system_context")
```

See `docs/parser_traps.md` for the full list of 12 traps.

---

## LLM Configuration

GovernIQ uses the OpenAI-compatible API. Two providers are supported:

| Provider | Configuration |
|----------|-------------|
| Anthropic Claude (default) | Set `ANTHROPIC_API_KEY` in `.env`. Uses `claude-sonnet-4-6` by default. |
| LM Studio (local, no cost) | Set `LLM_PROVIDER=lm_studio` in `.env`. Runs at `http://localhost:1234/v1`. |

Configuration is in `src/governiq/core/llm_config.py`.

---

## Manifest Validation Rules (MD-01–MD-12)

The validator in `src/governiq/core/manifest_validator.py` runs automatically when saving a manifest via the admin UI. Run it programmatically:

```python
from governiq.core.manifest import Manifest
from governiq.core.manifest_validator import validate_manifest

manifest = Manifest(**data)
result = validate_manifest(manifest)
print(result.valid, result.errors, result.warnings)
```

| Rule | Severity | Description |
|------|----------|-------------|
| MD-01 | WARNING | Exact dialog name policy (contains is safer) |
| MD-03 | ERROR | CREATE_WITH_AMENDMENT task missing amendment_config |
| MD-10 | ERROR | Duplicate task IDs |
| MD-11 | WARNING | Scoring weights don't sum to 1.0 |
| MD-12 | WARNING | Empty verify_endpoint on tasks with state assertion enabled |
| (others) | various | Cross-task reference validation, entity consistency |

---

## Storage Layout

All runtime data goes to `./data/` (gitignored):

```
data/
├── submissions/{submission_id}.json      # Root submission record
├── snapshots/{session_id}/
│   └── task_{task_id}_{type}.json       # CRUD API evidence
├── blueprints/{session_id}.json          # CBM structure blueprint
├── manifests/{manifest_id}.json          # Dual-saved manifest copies
└── fingerprints/{assessment_type}.json   # Plagiarism fingerprint store
```

---

## Environment Variables

Copy `.env.example` to `.env` and edit:

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_PROVIDER` | `claude` | `claude` or `lm_studio` |
| `ANTHROPIC_API_KEY` | — | Required if using Claude |
| `LM_STUDIO_URL` | `http://localhost:1234/v1` | Required if using LM Studio |
| `DATA_DIR` | `./data` | Root path for all runtime data |
| `MANIFESTS_DIR` | `./manifests` | Path to manifest JSON files |

---

## Key Design Constraints

1. **Engine is domain-free.** No domain words in engine code. Domain config in manifests only.
2. **CBM weight is always 0.0.** CBM audit is informational. Scores come from webhook results.
3. **Plagiarism runs independently.** The plagiarism module reads raw JSON directly — it never depends on CBM parser output.
4. **Each task is a fresh conversation session.** No state bleeds between tasks. Cross-task data passes via RuntimeContext only.
5. **Storage is local JSON now, PostgreSQL-migration-ready by design.** All models use explicit typed fields and clear primary keys.
