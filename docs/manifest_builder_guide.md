# GovernIQ — Manifest Builder Guide

## What is a Manifest?

A manifest is a single JSON file that completely defines an assessment. It has two logical parts:

1. **Assignment Brief** (public — shown to candidates): the scenario description, what to build, which entities to collect, which APIs to call, FAQ topics, and submission instructions.

2. **Evaluation Rubric** (private — evaluators only): the exact test scenarios, entity value pools, API verification rules, expected outputs, FAQ ground truth answers, compliance rules, and scoring weights.

One manifest = one complete assessment. You never write JSON directly — the manifest builder handles that for you.

---

## Accessing the Builder

- **Create a new manifest**: `Admin → Manifests → New Manifest` (`/admin/manifest/new`)
- **Edit an existing manifest**: `Admin → Manifests → Edit` next to the manifest (`/admin/manifest/edit/{id}`)

The builder has two tabs:
- **Form Builder** — the structured form (use this for all normal work)
- **JSON Editor** — raw JSON (for advanced edits or bulk import/export)

---

## Section-by-Section Walkthrough

### 1. Basic Information

| Field | What to Enter |
|-------|--------------|
| **Manifest ID** | Unique identifier, lowercase with hyphens. e.g. `medical-appointment-basic-v1` |
| **Assessment Name** | Human-readable name. e.g. "Medical Appointment Bot — Basic" |
| **Version** | Semantic version string. e.g. `1.0.0` |
| **Assessment Type** | Domain key. e.g. `medical`, `travel`, `banking`. Used for grouping submissions and plagiarism detection. |
| **Description** | Internal description for evaluators |
| **Notes** | Any additional context (not shown to candidates) |

---

### 2. Assignment Brief

This section is **shown to candidates**. It describes what they need to build.

| Field | What to Enter |
|-------|--------------|
| **Scenario Title** | The name candidates see at the top of their brief. e.g. "Medical Appointment Bot" |
| **Scenario Description** | 2–3 sentences describing the business scenario. e.g. "Build a bot for a medical centre that allows patients to book, retrieve, modify, and cancel appointments through a conversational interface." |
| **What to Build** | A bullet list of top-level requirements. Each item is one requirement. |
| **Entities to Collect** | The pieces of information the bot must collect from users. Add one row per entity: name (e.g. "patientName") and a plain-English description. |
| **API Endpoints** | The mock API endpoints the bot must call. Add one row per endpoint: name, HTTP method (GET/POST/PUT/DELETE), and description. |
| **Validation Rules** | Any specific validation requirements for entities. e.g. "contactNumber must be 10 digits". |
| **FAQ Topics** | A list of topic names the bot must be able to answer questions about. |
| **Mock API Setup Instructions** | How candidates should set up their mock API (what tool to use, base URL format, etc.) |
| **Submission Instructions** | Step-by-step instructions for how candidates should submit. |

---

### 3. Submission Config

Controls how many attempts candidates get and how feedback works.

| Field | Default | Description |
|-------|---------|-------------|
| **Max Attempts** | 6 | Maximum number of submission attempts allowed |
| **Require Evaluator Confirmation** | Yes | If checked, scores are not shown until evaluator confirms |
| **Allow Evaluator Exception** | Yes | If checked, evaluators can grant extra attempts beyond the limit |
| **Feedback Mode** | Immediate | When candidates can see their score: `immediate`, `after_all_attempts`, or `never` |

---

### 4. Scoring Config

Weights must sum to 1.0. The defaults are correct for all standard assessments — only change these if you have a specific reason.

| Field | Default | Description |
|-------|---------|-------------|
| **Webhook Functional Weight** | 0.80 | Weight for conversation + API verification tests |
| **FAQ Weight** | 0.10 | Weight for FAQ handling tests |
| **Compliance Weight** | 0.10 | Weight for structural compliance checks |
| **CBM Structural Weight** | 0.00 | Always 0 — CBM is informational only |

---

### 5. Tasks

This is the core of the manifest — the individual test scenarios the engine will run.

Click **Add Task** to create a task. Each task is a separate test scenario with its own conversation session.

#### Task Basic Fields

| Field | Description |
|-------|-------------|
| **Task ID** | Unique ID within this manifest. e.g. `task2_booking1`. Used in cross-task references. |
| **Task Name** | Display name for reports. e.g. "Book Appointment (Standard)" |
| **Weight** | Relative scoring weight for this task. Tasks with higher weight count more toward the final score. |
| **Pattern** | The engine pattern to use — see the Pattern Guide below. |
| **Dialog Name** | The exact name (or partial name) of the dialog in the candidate's bot that handles this scenario. |
| **Dialog Name Policy** | How to match the dialog name: `contains` (recommended), `exact`, or `semantic`. |
| **Record Alias** | A short name for the record created by this task. e.g. `Booking1`. Required for CREATE and CREATE_WITH_AMENDMENT tasks. Other tasks reference this alias to retrieve the record. |
| **Conversation Starter** | Optional: the first message the LLM driver sends to initiate the conversation. If empty, the engine generates one. |

#### Pattern Guide

Choose the pattern that matches what this task tests:

| Pattern | Use When | What the Engine Does |
|---------|----------|---------------------|
| **CREATE** | Testing that the bot can collect entities and create a record | Driver initiates conversation → injects entity values → bot calls POST API → engine verifies record exists |
| **CREATE_WITH_AMENDMENT** | Testing that the bot can handle mid-conversation entity corrections | Same as CREATE, but driver changes one entity value mid-conversation before confirmation |
| **RETRIEVE** | Testing that the bot can look up an existing record | Driver provides an identifier from a previous task → bot calls GET API → engine verifies bot's response contains correct data |
| **MODIFY** | Testing that the bot can update an existing record | Driver provides identifier → bot retrieves record → driver requests a change → bot calls PUT/PATCH API → engine verifies change persisted |
| **DELETE** | Testing that the bot can cancel or delete a record | Driver provides identifier → bot confirms deletion → bot calls DELETE API → engine verifies record is gone (404 or not in list) |
| **EDGE_CASE** | Testing that the bot handles invalid input gracefully | Driver injects an invalid value → engine checks that bot's response contains the expected error message |

#### Required Entities

Add one row per entity the engine should inject during this conversation:

| Field | Description |
|-------|-------------|
| **Entity Key** | The entity name as it appears in the bot. Must match exactly. e.g. `patientName` |
| **Semantic Hint** | Plain-English description for the LLM driver. e.g. "the patient's full name" |
| **Value Pool** | Comma-separated list of realistic test values. e.g. `John Smith, Mary Johnson, Ahmed Ali`. The engine picks randomly from this list. |
| **Validation Required** | Check if this entity has validation that could cause the bot to reject certain values. |
| **Validation Description** | If validation required: describe what values are valid. |

> For RETRIEVE, MODIFY, and DELETE tasks: leave Value Pool empty. The engine reads the identifier from a previous task's record via the cross-task reference.

#### Required Nodes (CBM Check)

Add one row per node type that must exist in the bot's dialog structure for this scenario. This is used for the CBM structural audit (informational, does not affect score).

| Field | Description |
|-------|-------------|
| **Node Type** | e.g. `aiassist`, `service`, `entity`, `message`, `form` |
| **Label** | Display name for the blueprint panel |
| **Service Method** | For service nodes: `GET`, `POST`, `PUT`, `PATCH`, or `DELETE` |
| **Required** | Whether this node is required (checked) or optional (unchecked) |

#### State Assertion (API Verification)

Defines how the engine verifies the API after the conversation completes.

| Field | Description |
|-------|-------------|
| **Enabled** | Check to activate API verification for this task |
| **Verify Endpoint** | The GET endpoint URL to call for verification. e.g. `http://localhost:3978/appointments` |
| **Filter Field** | The field used to find the specific record. e.g. `contactNumber` |
| **Field Assertions** | Key-value pairs: `entity_key: json_path`. e.g. `patientName: name` means "check that the value of `name` in the API response matches the `patientName` entity that was collected". Enter one assertion per line in `key: value` format. |
| **Expect Deletion** | For DELETE tasks only: check this to verify the record is gone (404 or not found in list) |

#### Expected Output

Defines the pass criteria for this task. Used in Phase 5 automated validation.

| Field | Description |
|-------|-------------|
| **Score Min** | Minimum score (0.0–1.0) this task must achieve to pass. e.g. `0.80` |
| **Must Pass Checks** | Comma-separated check IDs that must all pass. e.g. `entity_collection, api_call_verified` |
| **Evidence Required** | Comma-separated evidence types. e.g. `post_create_snapshot, webhook_transcript` |
| **Notes** | Evaluator notes about this task's expectations |

---

#### Pattern-Specific Fields

These sections appear automatically when you select the relevant pattern.

**CREATE_WITH_AMENDMENT only — Amendment Config:**

| Field | Description |
|-------|-------------|
| **Target Entity** | The entity key that will be changed mid-conversation |
| **Amendment Utterance Template** | The message the driver sends to trigger the amendment. Use `{amended_value}` as a placeholder. e.g. "Actually, change the appointment date to {amended_value}" |
| **Amended Value Pool** | Comma-separated list of values to use as the amended value. e.g. `2024-03-15, 2024-03-20, 2024-03-22` |

**RETRIEVE, MODIFY, DELETE — Cross-Task Reference:**

| Field | Description |
|-------|-------------|
| **Source Task ID** | The task ID that created the record to retrieve |
| **Source Record Alias** | The record alias from that task. e.g. `Booking1` |
| **Source Field** | The field in that record to inject as the identifier. e.g. `contactNumber` |

**MODIFY only — Modifiable Fields:**

| Field | Description |
|-------|-------------|
| **Modifiable Fields** | Comma-separated field names the driver can choose to modify |
| **Modified Value Pool** | One `field: value` pair per line. e.g. `appointmentDate: 2024-04-01` |

**EDGE_CASE only — Negative Tests:**

Add one row per negative test:

| Field | Description |
|-------|-------------|
| **Invalid Value Pool** | Comma-separated list of invalid values to inject. e.g. `abc, 123, !@#$` |
| **Expected Error Pattern** | A keyword or regex that must appear in the bot's error response. e.g. `invalid date` |
| **Requires Re-Entry Prompt** | Check if the bot should ask the user to try again (rather than just failing) |

---

### 6. FAQs

Defines the FAQ questions candidates must implement and how they are evaluated.

**Global FAQ Settings:**

| Field | Default | Description |
|-------|---------|-------------|
| **Min Alternate Questions** | 2 | Each FAQ must have at least this many alternate phrasings in the bot |
| **Semantic Similarity Threshold** | 0.80 | How similar a candidate's answer must be to the ground truth (0.0–1.0) |

Click **Add FAQ** to add a question. For each FAQ:

| Field | Description |
|-------|-------------|
| **Primary Question** | The canonical form of the question. e.g. "What are your working hours?" |
| **Ground Truth Answer** | The correct answer the bot must give. This is the reference for scoring. |
| **Required Keywords** | Comma-separated keywords that must appear in the bot's answer. e.g. `Monday, Friday, 9am, 5pm` |
| **Alternate Questions** | Other ways a user might ask the same question. Add at least 2. e.g. "When are you open?", "What time do you close?" |

---

### 7. Compliance Checks

Defines structural rules the bot must meet. These go into the CBM audit and count toward the compliance score (10%).

Click **Add Check** to add a rule. For each check:

| Field | Description |
|-------|-------------|
| **Check ID** | Unique ID. e.g. `dialogGPT` |
| **Label** | Human-readable name for the evaluator. e.g. "DialogGPT Enabled" |
| **CBM Field** | Dot-path to the field in the CBM object. e.g. `dialog_gpt_enabled` |
| **Required State** | What value the field must have: `enabled`, `disabled`, or `present` |
| **Critical** | If checked, failing this check auto-fails the entire compliance section |
| **Tooltip** | Plain-English explanation shown to evaluators in the blueprint panel |

**Standard compliance check (add to all manifests):**

```
Check ID: dialogGPT
Label: DialogGPT Enabled
CBM Field: dialog_gpt_enabled
Required State: enabled
Critical: checked
Tooltip: DialogGPT must be enabled in the bot's settings. This confirms the candidate is using the AI-powered dialog management feature.
```

---

### 8. Validation Panel

Click **Validate** at any time to check your manifest against the MD-01–MD-12 rules.

| Rule | Severity | Description |
|------|----------|-------------|
| MD-01 | Warning | A task uses `exact` dialog name policy — `contains` is safer and less brittle |
| MD-03 | Error | A CREATE_WITH_AMENDMENT task is missing its amendment_config |
| MD-10 | Error | Two or more tasks have the same Task ID |
| MD-11 | Warning | Scoring weights don't add up to 1.0 |
| MD-12 | Warning | A task has state assertion enabled but no verify_endpoint |

**Errors** must be fixed before saving. **Warnings** are advisory — you can save with warnings but should review them.

---

## Saving and Publishing

Click **Save** to save the manifest. It is immediately available for candidate submissions.

The manifest is saved to two locations:
- `manifests/{manifest_id}.json` — the authoritative copy in version control
- `data/manifests/{manifest_id}.json` — a runtime copy for the server

---

## Using the JSON Editor

The **JSON Editor** tab shows the raw JSON for the manifest. Use it when:
- Importing a manifest from another environment (paste JSON and save)
- Exporting a manifest to share with another instance (copy the JSON)
- Making bulk changes that would be tedious in the form

After editing JSON, click **Update Form** to sync changes back to the form builder.

The JSON editor also validates your JSON against the manifest schema in real time — red highlights indicate schema violations.

---

## Archiving and Restoring

**To archive**: `Admin → Manifests → Archive` — moves the manifest to `manifests/archived/`. Archived manifests cannot be used for new submissions but historical data is preserved.

**To restore**: `Admin → Manifests → Archived → Restore` — moves the manifest back to `manifests/` and makes it available again.

---

## Tips

1. **Use `contains` for dialog name policy** — it's more resilient. If the bot's dialog is named "Book Appointment v2", `contains` will match "Book Appointment" but `exact` won't.

2. **Always add at least 3 values to each Value Pool** — the engine picks randomly, so multiple values ensure the test isn't always the same input.

3. **Test your verify_endpoint manually first** — paste it into a browser or Postman to confirm it returns the expected JSON structure before adding it to the manifest.

4. **Keep Task IDs consistent** — use a naming convention like `task{number}_{action}` (e.g. `task2_booking1`, `task2_booking2`). You'll reference them in cross-task configurations.

5. **Validate before saving** — fix all errors and review all warnings before your first live use of the manifest.
