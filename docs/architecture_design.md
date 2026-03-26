# GovernIQ Evaluation Engine — Architecture & Design

> **Status:** Living document. All design decisions are final unless a section is marked `[OPEN]`.
> **Audience:** Evaluators, developers, and stakeholders. Stakeholders read Parts 1–2. Developers read all parts.

---

## Table of Contents

| Part | Sections | Audience |
|------|----------|----------|
| **Part 1 — Context** | 1. Problem Statement, 2. Candidate Journey, 3. Evaluator Journey | All |
| **Part 2 — Core Artifacts & Schemas** | 4. Assignment Use Case, 5. Evaluation Manifest | All |
| **Part 3 — Platform Capabilities** | 6. Kore.ai APIs & Webhooks | Developers |
| **Part 4 — Evaluation Pipeline** | 7–12. Gates 0–4, State Machine | All |
| **Part 5 — Scoring Model** | 13. Scoring Architecture | All |
| **Part 6 — LLM Mechanism** | 14. Actor, Judge, Feedback Writer | Developers |
| **Part 7 — Real-World Challenges** | 15. Challenges 1–25 | Developers |
| **Part 8 — Data & Operations** | 16–19. Persistence, Queue, Retention, Monitoring | Developers |
| **Part 9 — Quality & Trust** | 20–23. Manual Review, Calibration, Manifest Lifecycle, Plagiarism | All |
| **Part 10 — Workflows** | 24–27. Candidate Comms, Resubmission, Evaluator Dashboard, Test Submissions | All |
| **Part 11 — Pre-Build Validation** | 28–29. API Test Strategy, Build Inventory | Developers |
| **Part 12 — Design Decisions** | 30. Resolved Open Questions | All |

---

# Part 1 — Context

## 1. Problem Statement

### The goal

GovernIQ automates the evaluation of conversational bots built by learners on the Kore.ai XO Platform. Given any bot — in any domain — the system must test it, grade it, and produce actionable feedback for the learner, replicating the judgment of a skilled human evaluator.

### Why this is hard

A human evaluator succeeds because they carry three layers of understanding:

**Layer 1 — Domain understanding.** "This is a medical appointment bot." This comes from the **Assignment Use Case** — shared with both candidate and evaluator.

**Layer 2 — Evaluation methodology.** "To test booking, I'll play a patient, provide details, check the API, and read the debug log to understand failures." This comes from the **Evaluation Manifest** — the evaluator's playbook.

**Layer 3 — Diagnostic reasoning.** "The bot said 'booked' but the debug log shows ServiceNode returned 400 because doctorType was missing from the payload." This requires combining evidence from multiple sources.

An automated system has none of this by default. Every bit must be captured in structured documents. And the system must detect when information is missing.

---

## 2. Candidate Journey

```
STEP 1: RECEIVE ASSIGNMENT
  ├── Evaluator shares a submission link (e.g. https://governiq.app/submit/ASSIGN-MEDI-001)
  ├── Link opens the Assignment page showing:
  │     Assignment Use Case document
  │     Task list with user stories and data field specs
  │     FAQ topics to implement
  │     Scoring overview (max points per task, passing threshold)
  └── No login required to view the assignment

STEP 2: BUILD THE BOT (on Kore.ai XO Platform)
  ├── Create dialog tasks per the assignment task list
  ├── Define entity nodes with types, prompts, validations
  ├── Wire service nodes to the provided backend API
  ├── Configure FAQs in knowledge graph
  ├── Train NLP with utterances and synonyms
  ├── Enable webhook channel (V2 preferred)
  └── Test manually using Talk to Bot

STEP 3: SUBMIT (via the same submission link)
  ├── Upload bot export (.zip containing appDefinition.json)
  ├── Provide webhook URL
  ├── Provide app-scope credentials (clientId + clientSecret)
  ├── Provide admin-scope credentials (for debug log access)
  └── Provide backend API URL

STEP 4: TRACK PROGRESS (Candidate Portal)
  ├── Real-time status: Structure analysis → Live testing → Gathering data → Computing results
  └── Results held until evaluator approves

STEP 5: RECEIVE FEEDBACK REPORT
  ├── Overall score and pass/fail
  ├── Per-task score with specific evidence
  ├── Diagnostic feedback with root causes from debug logs
  ├── Configuration recommendations from structural analysis
  └── Specific suggestions for improvement
```

---

## 3. Evaluator Journey

```
STEP 1: CREATE ASSIGNMENT USE CASE
  ├── Define domain, tasks, data fields, FAQ topics, scoring overview
  └── System generates a submission link to share with candidates

STEP 2: CREATE EVALUATION MANIFEST
  ├── Define value pools (anti-gaming: random selection per evaluation)
  ├── For each task: trigger, actor behavior, entity collection with semantic hints,
  │   behavior checks with lookFor and scoring, API verification config,
  │   cross-task dependency config, captureFromConversation patterns,
  │   negative tests, feedback templates
  ├── Define FAQ evaluation questions and expected answers (evaluated via multilingual semantic similarity)
  └── Define execution config (turn limits, timeouts, LLM settings)

STEP 3: MANIFEST READINESS CHECK (system-assisted)
  ├── System validates completeness, asks specific questions for gaps:
  │   "T2 depends on T1 — what data from T1 does T2 need?"
  │   "Entity 'doctorType' has no semanticHints — what words does the bot use when asking?"
  ├── When bot export available, system auto-enriches:
  │   "CBM entity 'specialization' → manifest 'doctorType'?"
  └── Evaluator confirms until manifest is marked 'evaluation-ready'

STEP 4: CONTROL MANIFEST LIFECYCLE
  ├── DRAFT → CALIBRATING (test with known bots)
  ├── CALIBRATING → SHADOW (real submissions, held for review)
  ├── SHADOW → PRODUCTION (auto-release, light review)
  └── PRODUCTION → ARCHIVED (assignment closed)

STEP 5: REVIEW RESULTS
  ├── Evidence for every check (transcript, API snapshot, debug log)
  ├── Auto-generated feedback (evaluator can edit)
  └── Approve/override grades → release to candidate
```

---

# Part 2 — Core Artifacts & Schemas

## 4. Assignment Use Case

### What it is

Defines the **problem**. Shared with candidates and evaluators. Use-case agnostic — contains zero implementation details, only what the candidate must build and what it must do.

### Task taxonomy

| Category | How it's verified |
|----------|------------------|
| `greeting` | Transcript: greeting + options shown |
| `data_collection` | Transcript + API (record created) + Debug (entities extracted, service node executed) |
| `information_retrieval` | Transcript (data displayed) + API (data matches) + Debug (service node queried) |
| `data_modification` | Transcript + API (field values changed) + Debug (PUT/PATCH executed) |
| `data_deletion` | Transcript + API (record gone) + Debug (DELETE executed) |
| `workflow_execution` | Each step verified independently |
| `faq_response` | CBM (FAQ configured) + Transcript (answer evaluated via semantic similarity) |
| `validation_check` | Transcript: validation result shown |
| `escalation` | Debug: agent transfer node executed |

### Assignment Use Case — Full JSON Schema

```jsonc
// File: data/assignments/ASSIGN-MEDI-001/assignment.json
{
  "assignmentId": "ASSIGN-MEDI-001",
  "name": "Medi-Assistant",
  "version": "v1.0",
  "domain": "Medical Appointment Management",
  "description": "Build a conversational bot that manages medical appointments. The bot must allow patients to book, view, modify, and cancel appointments via a backend API.",
  "createdBy": "EVAL-001",
  "createdAt": "2026-03-01T00:00:00Z",

  // ─── DISTRIBUTION ──────────────────────────────────────────────────────────
  // Method: link-based. Evaluator shares this URL with candidates (e.g. via email).
  // No candidate account required. Submission link is unique per assignment.
  "distribution": {
    "method": "link",
    "submissionLink": "https://governiq.app/submit/ASSIGN-MEDI-001",
    "linkToken": "tkn_abc123xyz",
    "linkExpiresAt": null,        // null = never expires
    "cohortId": null              // null = not cohort-restricted
  },

  // ─── USE CASE DOCUMENT ─────────────────────────────────────────────────────
  "useCaseDocument": {
    "problemDescription": "A medical clinic needs a chatbot to help patients manage their appointments without calling the front desk. The bot should handle the full appointment lifecycle: booking, viewing, modifying, and cancelling.",
    "deliverables": [
      "A Kore.ai XO Platform bot with all required dialog tasks",
      "Webhook V2 channel enabled and functional",
      "Integration with the provided MockAPI backend",
      "FAQ responses for at least 3 common patient questions"
    ]
  },

  // ─── TASK LIST ─────────────────────────────────────────────────────────────
  "tasks": [
    {
      "taskId": "T1-BOOK",
      "name": "Book Appointment",
      "category": "data_collection",
      "userStory": "As a patient, I want to book a medical appointment by providing my details so that I receive a confirmed booking with a reference ID.",
      "dataFields": [
        { "field": "patientName",  "type": "string", "description": "Patient's full name" },
        { "field": "date",         "type": "date",   "format": "DD-MM-YYYY", "description": "Preferred appointment date" },
        { "field": "doctorType",   "type": "list",   "description": "Type of specialist (e.g. Cardiologist, Dermatologist)" },
        { "field": "phone",        "type": "phone",  "description": "10-digit mobile number" },
        { "field": "time",         "type": "time",   "description": "Preferred time slot (e.g. 10:30 AM)" }
      ],
      "acceptanceCriteria": [
        "Bot collects all 5 required data fields via conversation",
        "Bot displays a summary before the candidate confirms",
        "Bot provides a booking reference ID after confirmation",
        "Appointment data is saved to the backend API"
      ]
    },
    {
      "taskId": "T2-GET",
      "name": "View Appointment",
      "category": "information_retrieval",
      "userStory": "As a patient, I want to view my existing appointment details by providing my booking reference ID.",
      "dataFields": [
        { "field": "bookingId", "type": "string", "description": "Booking reference ID from the confirmation" }
      ],
      "acceptanceCriteria": [
        "Bot retrieves appointment record using the booking ID",
        "Bot displays all appointment details clearly",
        "Bot queries the GET endpoint of the backend API"
      ]
    },
    {
      "taskId": "T3-MODIFY",
      "name": "Modify Appointment",
      "category": "data_modification",
      "userStory": "As a patient, I want to modify the date and time of my existing appointment.",
      "dataFields": [
        { "field": "bookingId", "type": "string", "description": "Existing booking reference ID" },
        { "field": "newDate",   "type": "date",   "format": "DD-MM-YYYY", "description": "New preferred date" },
        { "field": "newTime",   "type": "time",   "description": "New preferred time" }
      ],
      "acceptanceCriteria": [
        "Bot identifies the existing appointment by booking ID",
        "Bot collects new date and time",
        "Bot calls the PUT/PATCH endpoint to update the record",
        "Bot confirms the modification with updated details"
      ]
    },
    {
      "taskId": "T4-CANCEL",
      "name": "Cancel Appointment",
      "category": "data_deletion",
      "userStory": "As a patient, I want to cancel my appointment and receive a cancellation confirmation.",
      "dataFields": [
        { "field": "bookingId", "type": "string", "description": "Booking reference ID to cancel" }
      ],
      "acceptanceCriteria": [
        "Bot identifies the appointment by booking ID",
        "Bot confirms cancellation intent before deleting",
        "Bot calls the DELETE endpoint",
        "Bot confirms cancellation to the user"
      ]
    },
    {
      "taskId": "T5-WELCOME",
      "name": "Welcome & Navigation",
      "category": "greeting",
      "userStory": "As a patient, when I open the bot I want to be greeted and shown what the bot can do.",
      "dataFields": [],
      "acceptanceCriteria": [
        "Bot triggers a welcome message on connect",
        "Bot shows available options or a menu",
        "Bot navigates to the correct task when user selects an option"
      ]
    }
  ],

  // ─── FAQ TOPICS ────────────────────────────────────────────────────────────
  "faqTopics": [
    {
      "topic": "insurance",
      "description": "Questions about insurance acceptance and coverage",
      "required": true
    },
    {
      "topic": "hours",
      "description": "Questions about clinic opening and closing hours",
      "required": true
    },
    {
      "topic": "location",
      "description": "Questions about clinic location, parking, and transport",
      "required": true
    }
  ],

  // ─── TECHNICAL REQUIREMENTS ───────────────────────────────────────────────
  "technicalRequirements": {
    "webhookVersion": "v2",
    "backendApiType": "MockAPI",
    "backendApiDescription": "RESTful API with CRUD endpoints for appointments resource",
    "minDialogTasks": 5,
    "minFAQsInKnowledgeGraph": 3,
    "minTrainingUtterancesPerTask": 5,
    "supportedLanguages": ["en"]
  },

  // ─── SCORING OVERVIEW (shown to candidate) ────────────────────────────────
  "scoringOverview": {
    "maxScore": 95,
    "passingScore": 70,
    "passingPercentage": 74,
    "taskBreakdown": [
      { "taskId": "T1-BOOK",    "maxPoints": 35, "description": "Book Appointment (critical task)" },
      { "taskId": "T2-GET",     "maxPoints": 15, "description": "View Appointment" },
      { "taskId": "T3-MODIFY",  "maxPoints": 15, "description": "Modify Appointment" },
      { "taskId": "T4-CANCEL",  "maxPoints": 15, "description": "Cancel Appointment" },
      { "taskId": "T5-WELCOME", "maxPoints": 5,  "description": "Welcome & Navigation" },
      { "taskId": "FAQ",        "maxPoints": 10, "description": "FAQ Responses (3 topics)" }
    ],
    "notes": [
      "Structural analysis (CBM) is informational only — does not affect your score.",
      "T1-BOOK is a critical task: you must score at least 50% on it to pass overall.",
      "Debug-dependent checks receive reduced weight if internal bot logs are unavailable."
    ]
  }
}
```

---

## 5. Evaluation Manifest

### What it is

The evaluator's complete playbook. A manifest is **sufficient** when a system with zero domain knowledge could follow it and arrive at the same grade a domain expert would. Every vague instruction is a potential grading error.

### Design principle: Sufficiency

For every task, ask: "Could someone with no medical knowledge follow this and grade correctly?" If yes, the manifest is sufficient. If no, add `semanticHints`, `lookFor` criteria, or `feedbackTemplates` until the answer is yes.

### Evaluation Manifest — Full JSON Schema

```jsonc
// File: data/assignments/ASSIGN-MEDI-001/manifest.json
{
  "manifestId": "MANIFEST-MEDI-001",
  "version": "v1.0",
  "assignmentId": "ASSIGN-MEDI-001",
  "assignmentName": "Medi-Assistant",
  "description": "Full evaluation playbook for the Medi-Assistant assignment",
  "createdBy": "EVAL-001",
  "createdAt": "2026-03-01T00:00:00Z",

  // ─── EXECUTION CONFIG ──────────────────────────────────────────────────────
  "executionConfig": {
    "maxTurnsPerTask": 20,          // Terminate task if conversation exceeds this
    "interMessageDelayMs": 1500,    // Delay between webhook messages (rate limit buffer)
    "pollTimeoutMs": 30000,         // Max time to wait for pollId resolution
    "pollIntervalMs": 1000,         // How often to poll for async service node result
    "webhookTimeoutMs": 15000,      // Per-request timeout for webhook calls
    "actorTemperature": 0,          // LLM actor must be deterministic
    "judgeTemperature": 0,          // LLM judge must be deterministic
    "feedbackTemperature": 0.3,     // Slight creativity for readable feedback text
    "maxLlmRetriesPerTurn": 3,      // Retry LLM on failure before halting task
    "stallDetectionTurns": 2        // Re-state intent after this many non-progress turns
  },

  // ─── VALUE POOLS (anti-gaming) ─────────────────────────────────────────────
  // One value is randomly selected per pool at evaluation start and locked for the
  // entire evaluation. A correctly built bot must handle ANY value from the pool.
  "personas": {
    "pools": {
      "patientName":  ["Meera Sharma", "Rajesh Kumar", "Anita Desai", "Vikram Patel", "Sunita Reddy"],
      "date":         ["25-03-2026", "02-04-2026", "15-04-2026", "10-05-2026"],
      "doctorType":   ["Cardiologist", "Dermatologist", "Orthopedic", "ENT Specialist", "General Physician"],
      "phone":        ["9876543210", "8765432109", "7654321098", "6543210987"],
      "time":         ["10:30 AM", "2:00 PM", "4:45 PM", "11:00 AM"],
      "newDate":      ["20-04-2026", "05-05-2026", "22-05-2026"],   // for T3-MODIFY
      "newTime":      ["9:00 AM", "3:30 PM", "5:00 PM"]             // for T3-MODIFY
    }
  },

  // ─── TASKS ─────────────────────────────────────────────────────────────────
  "tasks": [

    // ══════════════════════════════════════════════════════════════════════════
    // T1-BOOK: Book Appointment
    // ══════════════════════════════════════════════════════════════════════════
    {
      "taskId": "T1-BOOK",
      "name": "Book Appointment",
      "category": "data_collection",

      // Expected dialog task name in the candidate's bot export.
      // Used for CBM matching and for cross-referencing completedTaskName
      // from V2 webhook endOfTask response.
      "dialogTaskName": "BookAppointment",
      "dialogTaskNameVariants": ["Book Appointment", "bookAppointment", "Appointment Booking"],

      // ── TRIGGER ────────────────────────────────────────────────────────────
      // The Actor's first message. Must unambiguously trigger the booking dialog.
      "trigger": {
        "primary": "I'd like to book an appointment",
        "alternatives": [
          "I need to see a doctor",
          "Book an appointment for me",
          "I want to schedule a visit"
        ]
      },

      // ── ENTITY COLLECTION ─────────────────────────────────────────────────
      // Each entity the bot must collect. semanticHints are phrases the bot
      // uses when asking — the Actor uses these to recognise when to inject a value.
      "entityCollection": [
        {
          "entityId": "patientName",
          "description": "Patient's full name",
          "valuePool": "patientName",
          "semanticHints": [
            "What is your name?",
            "May I have your name?",
            "Please provide your name",
            "Your name please",
            "Patient name"
          ],
          "format": "string",
          "required": true
        },
        {
          "entityId": "date",
          "description": "Preferred appointment date",
          "valuePool": "date",
          "semanticHints": [
            "What date would you like?",
            "Preferred date?",
            "When would you like to visit?",
            "Choose a date",
            "Appointment date"
          ],
          "format": "DD-MM-YYYY",
          "required": true
        },
        {
          "entityId": "doctorType",
          "description": "Type of doctor required",
          "valuePool": "doctorType",
          "semanticHints": [
            "What type of doctor?",
            "Which specialty?",
            "Which specialist?",
            "Type of doctor needed",
            "Doctor type"
          ],
          "required": true
        },
        {
          "entityId": "phone",
          "description": "Patient's mobile number",
          "valuePool": "phone",
          "semanticHints": [
            "Phone number?",
            "Contact number?",
            "Mobile number?",
            "Your phone"
          ],
          "format": "10-digit numeric",
          "required": true
        },
        {
          "entityId": "time",
          "description": "Preferred appointment time",
          "valuePool": "time",
          "semanticHints": [
            "What time?",
            "Preferred time?",
            "At what time?",
            "Time slot"
          ],
          "format": "HH:MM AM/PM",
          "required": true
        }
      ],

      // ── BEHAVIOR CHECKS ───────────────────────────────────────────────────
      // Each check is evaluated independently by the Judge after all evidence
      // is collected. lookFor tells the Judge exactly what constitutes a pass.
      "behaviorChecks": [
        {
          "checkId": "B1",
          "description": "Bot triggers booking dialog within 3 turns",
          "lookFor": "The bot must begin collecting booking information within 3 turns of the first user message. A greeting followed immediately by asking for name or stating it can book counts as triggered.",
          "evidencePriority": ["transcript", "debug"],
          "scoring": { "type": "binary", "maxPoints": 3 }
        },
        {
          "checkId": "B2",
          "description": "Bot collects patient name",
          "lookFor": "Bot must ask for the patient name (using a phrase similar to semanticHints) and extract the value. Check debug log for EntityExtraction event for 'patientName' entity.",
          "entityRef": "patientName",
          "evidencePriority": ["debug", "entityTracking", "transcript"],
          "scoring": { "type": "binary", "maxPoints": 4 }
        },
        {
          "checkId": "B3",
          "description": "Bot collects preferred date",
          "lookFor": "Bot must ask for appointment date and extract it. Debug log should show EntityExtraction for the date entity. Format DD-MM-YYYY or similar variants are acceptable.",
          "entityRef": "date",
          "evidencePriority": ["debug", "entityTracking", "transcript"],
          "scoring": { "type": "binary", "maxPoints": 4 }
        },
        {
          "checkId": "B4",
          "description": "Bot collects doctor type",
          "lookFor": "Bot must ask for doctor type/specialty and extract the value. The entity must be of List type and include the test value in its enumeration.",
          "entityRef": "doctorType",
          "evidencePriority": ["debug", "entityTracking", "transcript"],
          "scoring": { "type": "binary", "maxPoints": 4 }
        },
        {
          "checkId": "B5",
          "description": "Bot collects all 5 required entities",
          "lookFor": "All 5 entities (patientName, date, doctorType, phone, time) must be collected. Score proportionally: each entity = 1/5 of points.",
          "entityRefs": ["patientName", "date", "doctorType", "phone", "time"],
          "evidencePriority": ["debug", "entityTracking", "transcript"],
          "scoring": {
            "type": "proportional",
            "maxPoints": 5,
            "proportionalOf": "entityCollection"
          }
        },
        {
          "checkId": "B6",
          "description": "Bot shows appointment summary before confirmation",
          "lookFor": "Bot must display a summary of the collected details and ask for confirmation before calling the API. Look for summary text containing patient name, date, or doctor type in the transcript.",
          "evidencePriority": ["transcript"],
          "scoring": { "type": "binary", "maxPoints": 3 }
        },
        {
          "checkId": "B7",
          "description": "Bot calls POST API with correct data",
          "lookFor": "API after-snapshot must contain a new record. Compare record field values against persona values. Score graduated based on field match quality.",
          "evidencePriority": ["apiSnapshot", "debug", "transcript"],
          "scoring": {
            "type": "graduated",
            "maxPoints": 8,
            "levels": [
              { "score": 8, "condition": "New record exists with ALL persona field values matching" },
              { "score": 5, "condition": "New record exists but SOME fields don't match persona values" },
              { "score": 2, "condition": "API was called (debug shows service node execution) but returned error" },
              { "score": 0, "condition": "No new record in API snapshot AND no service node event in debug" }
            ]
          }
        },
        {
          "checkId": "B8",
          "description": "Bot returns booking confirmation with reference ID",
          "lookFor": "After the API call, the bot must send a confirmation message containing a booking/reference ID (a code like APT-XXX or similar alphanumeric identifier). This ID will be captured for use in T2-T4.",
          "captureId": "bookingId",
          "evidencePriority": ["transcript"],
          "scoring": { "type": "binary", "maxPoints": 4 }
        },
        {
          "checkId": "B9",
          "description": "Bot handles invalid date input gracefully",
          "lookFor": "When given an invalid date (e.g. '99-99-9999'), bot must reject it and ask again. A validation message must appear in the transcript. Bot must NOT accept the invalid date.",
          "isNegativeTest": true,
          "negativeInput": "99-99-9999",
          "evidencePriority": ["debug", "transcript"],
          "scoring": { "type": "binary", "maxPoints": 3, "category": "bonus" }
        }
      ],

      // ── API VERIFICATION ──────────────────────────────────────────────────
      "apiVerification": {
        "endpoint": "{{backendApiUrl}}/appointments",
        "method": "POST",
        "snapshotBefore": true,
        "snapshotAfter": true,
        // These are the API field names and what values they should contain.
        // {{persona.X}} resolves to the randomly selected value for entity X.
        "expectedFieldMappings": {
          "name":       "{{persona.patientName}}",
          "date":       "{{persona.date}}",
          "doctorType": "{{persona.doctorType}}",
          "phone":      "{{persona.phone}}",
          "time":       "{{persona.time}}"
        }
      },

      // ── CAPTURE FROM CONVERSATION ─────────────────────────────────────────
      // After the task conversation ends, these regex patterns are applied to the
      // full transcript to extract dynamic values for use in dependent tasks.
      "captureFromConversation": [
        {
          "captureId": "bookingId",
          "description": "The booking reference ID returned by the bot in its confirmation",
          "patterns": [
            "(?:Booking|Appointment|Reference|Ref)\\s*(?:ID|No\\.?|Number)?\\s*[:\\-]?\\s*([A-Z0-9\\-]+)",
            "APT-\\d+",
            "ID[:\\s]+([A-Z0-9\\-]+)"
          ],
          "required": true,
          "fallback": "checkApiSnapshot"  // If regex fails, try extracting ID from API after-snapshot
        }
      ],

      // ── DEPENDENCIES ──────────────────────────────────────────────────────
      "dependencies": {
        "dependsOn": [],
        "requiredData": []
      },

      // ── FEEDBACK TEMPLATES ────────────────────────────────────────────────
      // Used by the Feedback Writer as starting points. LLM enriches these
      // with specific evidence (entity names, turn numbers, debug details).
      "feedbackTemplates": {
        "onPass": "Booking task completed successfully. All entities collected, API record created with correct data, and confirmation provided.",
        "onEntityFail": "The bot did not collect '{{entityId}}'. Ensure the entity node is present in the BookAppointment dialog and has the correct entity type. The bot prompt should include phrases like: {{semanticHints}}.",
        "onApiFailNoCall": "No appointment was created in the backend. Ensure your service node is connected to the dialog flow and the POST endpoint URL is correct.",
        "onApiFailPartialData": "The appointment was saved but some fields were missing or incorrect in the API record. Check your service node request body mapping — ensure all entity context variables are mapped to the correct API fields.",
        "onNoConfirmationId": "The bot did not return a booking reference ID after confirmation. Ensure your message node includes the booking ID from the API response."
      }
    },

    // ══════════════════════════════════════════════════════════════════════════
    // T2-GET: View Appointment
    // ══════════════════════════════════════════════════════════════════════════
    {
      "taskId": "T2-GET",
      "name": "View Appointment",
      "category": "information_retrieval",
      "dialogTaskName": "GetAppointment",
      "dialogTaskNameVariants": ["View Appointment", "Check Appointment", "getAppointment"],

      "trigger": {
        "primary": "I'd like to check my appointment",
        "alternatives": [
          "Show me my appointment",
          "What are my appointment details?",
          "Get my booking"
        ]
      },

      "entityCollection": [
        {
          "entityId": "bookingId",
          "description": "Booking reference ID from T1",
          // valueSource: instead of a pool, this comes from a previous task's captured output
          "valueSource": { "capturedFrom": "T1-BOOK", "captureId": "bookingId" },
          "semanticHints": [
            "What is your booking ID?",
            "Booking reference?",
            "Appointment ID?",
            "Reference number?"
          ],
          "required": true
        }
      ],

      "behaviorChecks": [
        {
          "checkId": "G1",
          "description": "Bot triggers the Get Appointment dialog",
          "lookFor": "Bot must enter the appointment retrieval dialog within 3 turns of the trigger.",
          "evidencePriority": ["transcript", "debug"],
          "scoring": { "type": "binary", "maxPoints": 3 }
        },
        {
          "checkId": "G2",
          "description": "Bot asks for booking ID and collects it",
          "lookFor": "Bot must ask for a booking ID (or reference number), and the Actor must have provided the booking ID from T1.",
          "entityRef": "bookingId",
          "evidencePriority": ["entityTracking", "transcript"],
          "scoring": { "type": "binary", "maxPoints": 3 }
        },
        {
          "checkId": "G3",
          "description": "Bot queries GET API with booking ID",
          "lookFor": "Debug log must show a service node executing a GET request. The URL or payload should include the booking ID from T1.",
          "evidencePriority": ["debug", "apiSnapshot"],
          "scoring": { "type": "binary", "maxPoints": 4 }
        },
        {
          "checkId": "G4",
          "description": "Bot displays correct appointment details",
          "lookFor": "Bot must display appointment information in the transcript. The displayed data must match the record in the API (patient name, date, doctor type, or time). At least 2 fields must be visible.",
          "evidencePriority": ["transcript", "apiSnapshot"],
          "scoring": { "type": "binary", "maxPoints": 5 }
        }
      ],

      "apiVerification": {
        "endpoint": "{{backendApiUrl}}/appointments/{{captured.T1-BOOK.bookingId}}",
        "method": "GET",
        "snapshotBefore": false,
        "snapshotAfter": true
      },

      "captureFromConversation": [],

      "dependencies": {
        "dependsOn": ["T1-BOOK"],
        "requiredData": [
          {
            "field": "bookingId",
            "capturedFrom": "T1-BOOK",
            "captureId": "bookingId",
            "description": "The booking ID created in T1, needed to retrieve the correct record"
          }
        ]
      },

      "feedbackTemplates": {
        "onPass": "Appointment retrieval working correctly. The bot queried the API and displayed the appointment details.",
        "onFail": "The bot did not retrieve the appointment. Ensure your GetAppointment dialog has a service node that calls the GET endpoint with the booking ID, and a message node that displays the returned fields."
      }
    },

    // ══════════════════════════════════════════════════════════════════════════
    // T3-MODIFY: Modify Appointment
    // ══════════════════════════════════════════════════════════════════════════
    {
      "taskId": "T3-MODIFY",
      "name": "Modify Appointment",
      "category": "data_modification",
      "dialogTaskName": "ModifyAppointment",
      "dialogTaskNameVariants": ["Update Appointment", "Reschedule", "modifyAppointment"],

      "trigger": {
        "primary": "I'd like to modify my appointment",
        "alternatives": [
          "I need to reschedule my appointment",
          "Can I change my booking?",
          "I want to update my appointment"
        ]
      },

      "entityCollection": [
        {
          "entityId": "bookingId",
          "valueSource": { "capturedFrom": "T1-BOOK", "captureId": "bookingId" },
          "semanticHints": ["Booking ID?", "Reference number?", "Appointment ID?"],
          "required": true
        },
        {
          "entityId": "newDate",
          "description": "New preferred appointment date",
          "valuePool": "newDate",
          "semanticHints": ["New date?", "Reschedule to?", "New preferred date?"],
          "format": "DD-MM-YYYY",
          "required": true
        },
        {
          "entityId": "newTime",
          "description": "New preferred appointment time",
          "valuePool": "newTime",
          "semanticHints": ["New time?", "New time slot?", "Preferred new time?"],
          "required": true
        }
      ],

      "behaviorChecks": [
        {
          "checkId": "M1",
          "description": "Bot triggers modify dialog",
          "lookFor": "Bot enters the modification flow within 3 turns.",
          "scoring": { "type": "binary", "maxPoints": 2 }
        },
        {
          "checkId": "M2",
          "description": "Bot collects new date and time",
          "lookFor": "Bot collects both newDate and newTime entities.",
          "entityRefs": ["newDate", "newTime"],
          "evidencePriority": ["debug", "entityTracking", "transcript"],
          "scoring": { "type": "proportional", "maxPoints": 4, "proportionalOf": "entityCollection" }
        },
        {
          "checkId": "M3",
          "description": "Bot calls PUT/PATCH API to update record",
          "lookFor": "API after-snapshot must show the appointment record with updated date and/or time matching the new values. Debug must show a PUT or PATCH service node call.",
          "evidencePriority": ["apiSnapshot", "debug"],
          "scoring": {
            "type": "graduated",
            "maxPoints": 6,
            "levels": [
              { "score": 6, "condition": "Record updated with both newDate and newTime matching" },
              { "score": 3, "condition": "Record updated but only one field changed" },
              { "score": 1, "condition": "API called but record unchanged" },
              { "score": 0, "condition": "No API call detected" }
            ]
          }
        },
        {
          "checkId": "M4",
          "description": "Bot confirms modification",
          "lookFor": "Bot sends a confirmation message showing the updated appointment details.",
          "evidencePriority": ["transcript"],
          "scoring": { "type": "binary", "maxPoints": 3 }
        }
      ],

      "apiVerification": {
        "endpoint": "{{backendApiUrl}}/appointments/{{captured.T1-BOOK.bookingId}}",
        "method": "PUT",
        "snapshotBefore": true,
        "snapshotAfter": true,
        "expectedFieldMappings": {
          "date": "{{persona.newDate}}",
          "time": "{{persona.newTime}}"
        }
      },

      "captureFromConversation": [],

      "dependencies": {
        "dependsOn": ["T1-BOOK"],
        "requiredData": [
          { "field": "bookingId", "capturedFrom": "T1-BOOK", "captureId": "bookingId" }
        ]
      },

      "feedbackTemplates": {
        "onPass": "Appointment modification working correctly.",
        "onApiFail": "The appointment was not updated in the API. Check that your service node uses PUT/PATCH and maps newDate and newTime to the correct API fields."
      }
    },

    // ══════════════════════════════════════════════════════════════════════════
    // T4-CANCEL: Cancel Appointment
    // ══════════════════════════════════════════════════════════════════════════
    {
      "taskId": "T4-CANCEL",
      "name": "Cancel Appointment",
      "category": "data_deletion",
      "dialogTaskName": "CancelAppointment",
      "dialogTaskNameVariants": ["Delete Appointment", "cancelAppointment"],

      "trigger": {
        "primary": "I'd like to cancel my appointment",
        "alternatives": ["Cancel my booking", "I need to cancel my appointment"]
      },

      "entityCollection": [
        {
          "entityId": "bookingId",
          "valueSource": { "capturedFrom": "T1-BOOK", "captureId": "bookingId" },
          "semanticHints": ["Booking ID?", "Which appointment?", "Reference number?"],
          "required": true
        }
      ],

      "behaviorChecks": [
        {
          "checkId": "C1",
          "description": "Bot triggers cancel dialog",
          "scoring": { "type": "binary", "maxPoints": 2 }
        },
        {
          "checkId": "C2",
          "description": "Bot confirms cancellation intent before deleting",
          "lookFor": "Bot must ask for cancellation confirmation (e.g. 'Are you sure?') before calling the DELETE API.",
          "evidencePriority": ["transcript"],
          "scoring": { "type": "binary", "maxPoints": 3 }
        },
        {
          "checkId": "C3",
          "description": "Bot calls DELETE API",
          "lookFor": "API after-snapshot must show the appointment record is gone (or marked cancelled). Debug must show DELETE service node execution.",
          "evidencePriority": ["apiSnapshot", "debug"],
          "scoring": {
            "type": "graduated",
            "maxPoints": 7,
            "levels": [
              { "score": 7, "condition": "Record no longer exists in API after-snapshot" },
              { "score": 4, "condition": "DELETE was called but record still exists (API issue)" },
              { "score": 0, "condition": "No DELETE call detected" }
            ]
          }
        },
        {
          "checkId": "C4",
          "description": "Bot confirms cancellation to user",
          "lookFor": "Bot sends a confirmation message that the appointment has been cancelled.",
          "evidencePriority": ["transcript"],
          "scoring": { "type": "binary", "maxPoints": 3 }
        }
      ],

      "apiVerification": {
        "endpoint": "{{backendApiUrl}}/appointments/{{captured.T1-BOOK.bookingId}}",
        "method": "DELETE",
        "snapshotBefore": true,
        "snapshotAfter": true
      },

      "captureFromConversation": [],

      "dependencies": {
        "dependsOn": ["T1-BOOK"],
        "requiredData": [
          { "field": "bookingId", "capturedFrom": "T1-BOOK", "captureId": "bookingId" }
        ]
      },

      "feedbackTemplates": {
        "onPass": "Cancellation working correctly.",
        "onFail": "The appointment was not cancelled. Ensure your service node calls the DELETE endpoint with the booking ID."
      }
    },

    // ══════════════════════════════════════════════════════════════════════════
    // T5-WELCOME: Welcome & Navigation
    // ══════════════════════════════════════════════════════════════════════════
    {
      "taskId": "T5-WELCOME",
      "name": "Welcome & Navigation",
      "category": "greeting",
      "dialogTaskName": "Welcome",
      "dialogTaskNameVariants": ["OnConnect", "welcome", "Greet"],

      "trigger": {
        // ON_CONNECT event — not a text message
        "primary": null,
        "triggerType": "ON_CONNECT"
      },

      "entityCollection": [],

      "behaviorChecks": [
        {
          "checkId": "W1",
          "description": "Bot sends a welcome/greeting message on connect",
          "lookFor": "First bot message must contain a greeting (Hello, Hi, Welcome, or similar).",
          "evidencePriority": ["transcript"],
          "scoring": { "type": "binary", "maxPoints": 2 }
        },
        {
          "checkId": "W2",
          "description": "Bot shows available options or menu",
          "lookFor": "Bot must display the available services or a menu within the first 2 turns. Options or buttons are acceptable.",
          "evidencePriority": ["transcript"],
          "scoring": { "type": "binary", "maxPoints": 3 }
        }
      ],

      "apiVerification": null,
      "captureFromConversation": [],
      "dependencies": { "dependsOn": [], "requiredData": [] },

      "feedbackTemplates": {
        "onPass": "Welcome task working correctly. Bot greets users and shows available options.",
        "onFail": "The bot did not trigger a welcome response on connect. Ensure the ON_CONNECT event is configured in the webhook channel settings and your welcome dialog is connected to it."
      }
    },

    // ══════════════════════════════════════════════════════════════════════════
    // Example: a web driver task (taskId and position are evaluator-defined)
    // Any task with uiPolicy: "web_driver" runs on the Web SDK + Playwright.
    // This example uses "T6-RICH-UI" as the task ID — evaluators name tasks freely.
    // The task can appear at any position in the sequence (first, middle, last).
    // ══════════════════════════════════════════════════════════════════════════
    {
      "taskId": "T6-RICH-UI",   // evaluator-defined — any ID is valid
      "name": "Rich UI Interaction",
      "driver": "web",
      "uiPolicy": "web_driver",

      "trigger": {
        "primary": "[Opening message that activates the rich UI dialog]"
      },

      // UI elements the bot is required to render during this task
      "uiSpec": {
        "expectedElements": ["carousel", "inline_form", "buttons"],

        "carousel": {
          // Which persona entity to match against rendered card titles
          "entityRef": "entityId1",
          // "exact" | "contains" | "semantic"
          "matchStrategy": "semantic"
        },

        "inline_form": {
          "formFields": [
            {
              "entityRef": "entityId1",
              // Human-readable labels the evaluator expects to appear on this field
              "labelHints": ["Field Label A", "Alternate Label A"]
            },
            {
              "entityRef": "entityId2",
              "labelHints": ["Field Label B", "Alternate Label B"]
            },
            {
              "entityRef": "entityId3",
              "labelHints": ["Field Label C"]
            }
          ],
          // What to do with form fields that cannot be mapped to any manifest entity
          // "leave_empty" | "fill_placeholder"
          "unmappedFieldBehavior": "leave_empty"
        },

        "buttons": {
          "entityRef": "entityId3",
          "matchStrategy": "semantic"
        }
      },

      // One behavior check per expected UI element + one for API outcome
      "behaviorChecks": [
        {
          "checkId": "U1",
          "description": "Bot renders a carousel for selection",
          "lookFor": "Bot must present a carousel with selectable options. The correct option must correspond to the persona value for entityId1.",
          "evidencePriority": ["uiInteraction"],
          "scoring": { "type": "binary", "maxPoints": 5 }
        },
        {
          "checkId": "U2",
          "description": "Bot renders an inline form collecting required fields",
          "lookFor": "Bot must present a form with labeled fields. All required entity fields must be present and mappable from their labels.",
          "evidencePriority": ["uiInteraction"],
          "scoring": {
            "type": "graduated",
            "maxPoints": 8,
            "levels": [
              { "score": 8, "condition": "All fields mapped and form submitted successfully" },
              { "score": 4, "condition": "Partial fields mapped, form submitted" },
              { "score": 0, "condition": "Form not rendered or submission failed" }
            ]
          }
        },
        {
          "checkId": "U3",
          "description": "Bot presents buttons at the required point in the dialog",
          "lookFor": "Bot must present clickable button options at the point defined in the manifest. Buttons may serve as navigation options, confirmation choices, or selection menus depending on the dialog design.",
          "evidencePriority": ["uiInteraction"],
          "scoring": { "type": "binary", "maxPoints": 3 }
        },
        {
          "checkId": "U4",
          "description": "API record created after UI interaction completes",
          "lookFor": "After all UI interactions complete, a record must appear in the API snapshot with the correct field values matching the persona.",
          "evidencePriority": ["apiSnapshot"],
          "scoring": { "type": "binary", "maxPoints": 4 }
        }
      ],

      "dependencies": { "dependsOn": [], "requiredData": [] },

      "feedbackTemplates": {
        "onCarouselMissing": "The bot did not present a carousel. Ensure your message node uses a carousel template with dynamically populated options.",
        "onCarouselNoMatch": "A carousel was rendered but none of the cards matched the expected value. Ensure your card list covers all possible values from the entity pool — a hardcoded list that does not include all persona values will fail for some candidates.",
        "onCarouselEntityNotExtracted": "A card was selected from the carousel but the entity value was not captured by the bot. Ensure the button payload value matches one of the configured values in your entity node's enumerated list — the payload must correspond to a valid entity value, not just display text.",
        "onCarouselApiValueMissing": "The carousel interaction completed but the selected value did not appear in the API record. Check your service node request body mapping — the carousel entity must be included in the payload sent to the backend.",
        "onFormMissing": "The bot did not present a form. Ensure a form node is connected to the dialog flow at the correct point.",
        "onFormPartial": "The form was presented but some required fields were missing or could not be mapped. Check that your form component labels match the assignment field names.",
        "onButtonsMissing": "The bot did not present the required buttons at the expected point in the dialog. Ensure your message node includes a button template. Buttons may be used for navigation, confirmation, or selection — check the assignment spec for where they are expected.",
        "onApiMissing": "The UI interactions completed but no record was created in the backend API. Check that your form submission is wired to a service node."
      }
    }
  ],

  // ─── FAQ TASKS ─────────────────────────────────────────────────────────────
  // Scoring mechanism: semantic similarity via sentence-transformers.
  // Bot response is compared against expectedAnswer. Pass if similarity >= similarityThreshold.
  // expectedAnswer is the canonical answer the evaluator configured in the knowledge graph.
  // similarityThreshold is required — Manifest Readiness Validator flags if missing.
  "faqTasks": [
    {
      "taskId": "FAQ-INSURANCE",
      "topic": "insurance",
      "question": "Do you accept insurance?",
      "alternativeQuestions": [
        "Is insurance accepted?",
        "What insurance do you take?",
        "Are you covered by insurance?"
      ],
      "expectedAnswer": "Yes, we accept all major insurance providers. Please bring your insurance card on the day of your appointment.",
      "similarityThreshold": 0.75,
      "evidencePriority": ["transcript", "cbm"],
      "scoring": { "type": "binary", "maxPoints": 3 }
    },
    {
      "taskId": "FAQ-HOURS",
      "topic": "hours",
      "question": "What are your opening hours?",
      "alternativeQuestions": [
        "What time do you open?",
        "When is the clinic open?",
        "What are your working hours?"
      ],
      "expectedAnswer": "The clinic is open from 9 AM to 5 PM, Monday to Saturday.",
      "similarityThreshold": 0.80,
      "scoring": { "type": "binary", "maxPoints": 3 }
    },
    {
      "taskId": "FAQ-LOCATION",
      "topic": "location",
      "question": "Where are you located?",
      "alternativeQuestions": [
        "What is your address?",
        "How do I get there?",
        "Where is the clinic?"
      ],
      "expectedAnswer": "We are located at 3rd Floor, Medicity Tower, MG Road, Bangalore. Parking is available in the basement.",
      "similarityThreshold": 0.80,
      "scoring": { "type": "binary", "maxPoints": 4 }
    }
  ],

  // ─── SCORING ───────────────────────────────────────────────────────────────
  "scoring": {
    "maxScore": 95,
    "passingScore": 70,
    "passingPercentage": 74,

    "taskWeights": [
      { "taskId": "T1-BOOK",    "maxPoints": 35, "criticalTask": true,  "criticalThreshold": 50 },
      { "taskId": "T2-GET",     "maxPoints": 15, "criticalTask": false },
      { "taskId": "T3-MODIFY",  "maxPoints": 15, "criticalTask": false },
      { "taskId": "T4-CANCEL",  "maxPoints": 15, "criticalTask": false },
      { "taskId": "T5-WELCOME", "maxPoints": 5,  "criticalTask": false },
      { "taskId": "FAQ",        "maxPoints": 10, "criticalTask": false }
    ],

    // criticalTask rule: if a critical task scores below criticalThreshold (%),
    // the candidate CANNOT pass regardless of overall score.
    "criticalTaskLogic": "If T1-BOOK scores below 50% (17.5 points), candidate fails even if total score ≥ 70."
  },

  // ─── ASSIGNMENT BASELINE (plagiarism exclusion) ────────────────────────────
  // Text from the assignment document that naturally appears in all bots.
  // Excluded from Tier 2 plagiarism comparison to avoid false positives.
  "assignmentBaseline": {
    "excludeUtterances": [
      "book an appointment",
      "cancel my appointment",
      "modify my appointment",
      "view my appointment",
      "What are your visiting hours?",
      "Do you accept insurance?"
    ],
    "templateBotExport": null   // If evaluator provides a template, its node labels are excluded
  },

  // ─── ATTEMPT POLICY ───────────────────────────────────────────────────────
  "attemptPolicy": {
    "maxAttempts": 3,
    "cooldownMinutes": 60,
    "showPreviousFeedback": true,
    "allowPartialResubmit": false
  }
}
```

---

---

# Part 3 — Platform Capabilities

## 6. Kore.ai APIs & Webhooks

### 6.1 Webhook Channel (How We Talk to the Bot)

#### Why webhook — channel selection rationale

Three channels exist for talking to a Kore.ai bot:

| Channel | Driveable programmatically? | Machine-readable responses? | Task completion signal? | Entity/state signals? |
|---------|-----------------------------|-----------------------------|-------------------------|-----------------------|
| **Talk to Bot** (internal test) | No — no public API | N/A | N/A | N/A |
| **Web Widget** | Yes — via Playwright | No — rendered HTML, must scrape | No | No |
| **Webhook V2** | Yes | Yes — structured JSON | **Yes** (`endOfTask`, `completedTaskName`) | **Yes** (`pollId`, entity tracking) |

**Talk to Bot** is what human evaluators use. It runs the full dialog engine identically to production. But it has no API surface — it cannot be driven programmatically. Eliminated.

**Web Widget** is driveable via Playwright. But you lose the structured JSON responses — you are scraping rendered HTML instead of parsing API responses. Extracting entity tracking, task completion signals, and async service node results reliably from rendered HTML is not tractable. Eliminated.

**Webhook V2** is the right choice — not for session management, but for signal quality:
- `endOfTask: true` + `completedTaskName` tell you exactly when a dialog task completes and which task it was. No heuristics, no content analysis.
- `pollId` tells you a service node went async — poll for result rather than treating silence as an error.
- `data[]` is a structured array — buttons, forms, carousels, and text all come back as typed objects you can parse, not HTML you must scrape.
- The full response is machine-readable JSON. Every piece of state you need for grading is in the payload.

**CBM note:** CBM tells you structure exists — service nodes are wired, entity nodes are defined. It cannot tell you whether the request body mapping is correct or whether entity prompts trigger reliably. Live webhook testing is the only channel that catches these. This is the core justification for the dual-pipeline: CBM catches missing structure, webhook catches broken behaviour.

> **Open verification item:** The session ID assumption (same `from.id` across messages maintains a session) should be verified against a live Kore.ai bot before Go 2 development. The architecture does not depend on this for correctness — `endOfTask` is the primary task boundary signal — but it should be confirmed to avoid surprises.

Two versions with different endpoints:

| Version | Endpoint | Notes |
|---------|----------|-------|
| V1 | `POST /chatbot/hooks/{botId}` | Simpler payload. `message.text` for text. No `endOfTask`. |
| V2 | `POST /chatbot/v2/webhook/{botId}` | Preferred. `endOfTask`, `completedTaskName`, `pollId` for async service nodes. |

**V2 Request payload:**
```json
{
  "session": { "new": true },
  "message": { "type": "text", "val": "I'd like to book an appointment" },
  "from": { "id": "eval-SUB-0342-T1-BOOK", "userInfo": { "firstName": "", "lastName": "" } },
  "mergeIdentity": true,
  "customData": {},
  "metaTags": { "userLevelTags": [], "sessionLevelTags": [], "messageLevelTags": [] }
}
```

**V2 Response payload:**
```json
{
  "to": "eval-SUB-0342-T1-BOOK",
  "from": "st-botId-xxx",
  "data": [
    { "type": "text", "val": "Bot's response message", "createdOn": "...", "messageId": "ms-xxx" }
  ],
  "_v": "v2",
  "endOfTask": true,
  "endReason": "Fulfilled",
  "completedTaskId": "dg-xxx",
  "completedTaskName": "BookAppointment",
  "pollId": "poll-xxx"
}
```

**Critical fields the system must use:**

| Field | Use |
|-------|-----|
| `endOfTask` | Tells us exactly when a dialog task finishes. No guessing from content. |
| `endReason` | `Fulfilled` = success. `UserAbandoned` = mid-task dropout. |
| `completedTaskName` | Which dialog completed. Cross-reference against manifest `dialogTaskName`. |
| `pollId` | Service/webhook nodes defer response. Must poll until result arrives. |
| `data[]` | Array — bot can send multiple messages per turn. Read all items, not just `data[0]`. |

**Session management:**
- `session.new: true` on the first message starts a new session.
- Same `from.id` on subsequent messages continues the session.
- `ON_CONNECT` event triggers the bot's welcome/on-connect behavior: send `{ "message": { "type": "event", "val": "ON_CONNECT" } }`.
- `SESSION_CLOSURE` event explicitly closes a session: send `{ "message": { "type": "event", "val": "SESSION_CLOSURE" } }`.
- **Session isolation (deliberate design decision):** Each task uses a unique `from.id`: `eval-{submissionId}-{taskId}`. A `SESSION_CLOSURE` event is sent after each task before starting the next. This is intentional — isolated sessions make each task independently reproducible and independently scoreable. Session-level context (entity memory, NLP history) from T1 does not carry into T2. See Q16.

**Authentication:**
- JWT with payload `{ "appId": "{clientId}", "sub": "random-string" }`, signed with clientSecret.
- `appId` is **case-sensitive**. Must be exactly `appId` — not `App ID`, `appid`, or `APPID`.
- JWT must NOT include `userIdentity` unless it matches `from.id` exactly (causes 401 otherwise).
- Token expiry: 3600 seconds. Regenerate 5 minutes before expiry.

---

### 6.2 Polling Handler (V2 pollId)

When a bot's service node calls an external API, the webhook response may not include the final message immediately — it returns a `pollId` instead.

```
POST /chatbot/v2/webhook/{botId}
  └─ Response: { "pollId": "poll-xxx" }  ← Service node is executing

GET /chatbot/v2/webhook/{botId}/poll/{pollId}  ← Poll at 1s intervals
  └─ Until: response includes data messages OR endOfTask: true

Timeout: 30 seconds. Log poll count in diagnostics.
```

If polling is not implemented, the system misses the bot's response after API calls — which is often the most important message (confirmation, booking ID, error message).

---

### 6.3 Debug Logs API

**What the debug log contains per conversation turn:**

| Event type | What it tells us |
|-----------|-----------------|
| `intent node processing completed` | Which intent was matched |
| `entity node initiated` | Bot asking user for a specific entity |
| Entity extraction result | Entity name, extracted value, confidence score |
| `Service node execution` | URL called, HTTP method, status code, response |
| `Script node execution` | Script output, any errors |
| NL Analysis | ML engine score, FM score, KG score per intent candidate |
| `koreDebugger.log()` | Custom debug statements from the bot developer |

**Availability delay:** Debug logs can take 0–10 hours to appear after a session ends. The system must poll on a retry schedule (see Section 10).

**Authentication:** Admin-scope JWT (separate from app-scope). Same JWT format but with admin clientId/clientSecret.

---

### 6.4 Conversation History API V2

Returns up to 10,000 messages per request, filterable by Session-Id. Used to cross-verify the canonical transcript against our webhook-recorded transcript.

---

### 6.5 Bot Export (appDefinition.json — CBM Source)

Contains: dialog task definitions, entity node configs (name, type, prompts, validations, regex, retries), service node configs (URL, method, request body mappings, response mappings), knowledge graph / FAQ definitions, NLP training data, global settings, flow connections.

---

### 6.6 Other APIs

| API | Scope | Use in evaluation |
|-----|-------|------------------|
| Bot Details API | Admin | Check publish status, version, language |
| Analytics API | Admin | Post-eval: task success rates, unhandled utterances |
| Sessions History API | Admin | Session metadata, duration, status |
| Conversation Summary API | Admin | Auto-generated summaries |

---

# Part 4 — Evaluation Pipeline

## 7. Gate 0 — Submission Validation

Runs immediately on submission. Takes < 15 seconds. Catches bad credentials and unreachable endpoints before wasting queue capacity.

### Field-by-field validation

| Field | Client-side | Server-side | Pre-evaluation |
|-------|-------------|-------------|----------------|
| **Webhook URL** | Must start `https://`, contain `/chatbot/` | Trim whitespace, validate URL format, reject `http://` | `HEAD` request. 404 → "Webhook URL not found". No response → "Unable to reach". |
| **Bot ID** | Must start `st-` | Trim, validate format `st-{uuid}` | Call Bot Details API. 404 → "Bot ID not found". |
| **App Client ID** | Must start `cs-` | Trim, validate format | Generate JWT, send `ON_CONNECT`. 401 → "Credentials invalid". |
| **App Client Secret** | Non-empty | Trim, length check | Used with Client ID above |
| **Admin Client ID** | Must start `cs-` | Trim, validate | Generate admin JWT, call Bot Details API. 401 → "Admin credentials invalid". |
| **Admin Client Secret** | Non-empty | Same | Used with Admin Client ID |
| **Backend API URL** | Must start `https://` or `http://` | Trim, validate URL | `GET` request. Any response (even 404) = reachable. Refused = unreachable. |
| **Bot Export (.zip)** | `.zip` only, max 50 MB | Verify ZIP signature, extract, find `appDefinition.json` | N/A |
| **Assignment** | Must select one | Validate assignment ID exists, manifest exists and is in SHADOW or PRODUCTION state | N/A |

### Whitespace sanitization (applied to ALL text fields)

Candidates copy-paste credentials from Kore.ai — this introduces leading/trailing spaces, non-breaking spaces (`\u00A0`), zero-width characters (`\u200B`, `\uFEFF`), and embedded newlines.

```
1. Trim leading and trailing whitespace
2. Remove zero-width characters (\u200B, \uFEFF, \u00AD)
3. Remove newline and carriage return characters
4. Collapse multiple spaces into one (URL fields)
5. Preserve original in "rawInput" field for debugging
6. Log: "Field '{name}' sanitized: removed {n} leading / {m} trailing chars"
```

### Pre-evaluation connectivity check

Before entering Gate 1:

```
1. WEBHOOK REACHABILITY
   Send: ON_CONNECT event to webhook URL with app JWT
   200  → Bot is reachable
   401  → "Invalid app credentials"
   404  → "Webhook URL not found — is the webhook channel enabled?"
   504  → "Webhook timing out — is the bot published?"
   CONN → "Cannot reach webhook URL"

2. ADMIN API — BOT DETAILS (single call, three checks)
   Send: GET /bot/{botId} with admin JWT
   From the single response:

   a) CREDENTIALS
      401  → FAIL: "Invalid admin credentials"
      404  → FAIL: "Bot ID not found"
      200  → credentials valid, continue to b) and c)

   b) PUBLISH STATUS
      Check publish state field in response.
      Not published → FAIL: "Your bot is not published.
        Publish it in XO Platform before submitting.
        Go to Deploy → Publish and select all components."
      Published → pass

   c) WEB CHANNEL
      Inspect enabled channels list for web SDK entry.
      (Exact field name confirmed by workbench — Section 28)
      Absent → WARN (not FAIL): "Web channel not enabled on your bot.
        Any tasks requiring web driver evaluation cannot be tested. Enable the
        Web SDK channel in XO Platform: Channels → Web/Mobile Client → Enable.
        All webhook tasks and FAQ will be evaluated normally."
      Present → pass
      Note: WARN not FAIL — all webhook tasks and FAQ proceed regardless.
      Tasks with uiPolicy: web_driver are skipped and scored 0 if web channel absent.

3. BACKEND API REACHABILITY
   Send: GET to backendApiUrl
   Any response → reachable (even 404 means server is up)
   CONN → "Cannot reach backend API URL"

4. WEBHOOK VERSION CHECK
   Parse the webhook URL path.
   Must contain `/v2/` (i.e. `.../chatbot/v2/...`)
   V1 URL detected → FAIL: "V2 webhook channel required.
     Your webhook URL appears to be V1 (missing `/v2/`).
     In XO Platform: Channels → Webhook → Version 2.0 → Enable.
     V1 is not supported — it does not send endOfTask signals or
     structured template responses that GovernIQ depends on."
   URL is ambiguous (no version segment) → WARN, proceed
   V2 confirmed → pass

→ ALL PASS: proceed to Gate 1
→ ANY FAIL: return specific error to candidate. Do NOT start evaluation.
```

---

## 8. Gate 1 — Prebuild Checklist (CBM Structural Audit)

Runs automatically after Gate 0 passes. Takes < 30 seconds. Uses the bot export ZIP.

```
1. PARSEABLE         Bot export opens and contains appDefinition.json
2. DIALOG TASKS      Each manifest task maps to a dialog in the export
                     → Extract entity prompts as semanticHints (for manifest enrichment)
3. ENTITY NODES      Each data field has a corresponding entity node
                     → Extract entity type, prompts, retry count, validation regex
4. SERVICE NODES     API tasks have service nodes with URLs configured
                     → Extract request body mappings (entity → payload field)
                     → Extract HTTP method
5. FLOW CONNECTIVITY Nodes are connected, no dead ends in the dialog flow
6. FAQ COVERAGE      All required FAQs exist in the knowledge graph
                     → Check answers are non-empty (structural check only — semantic evaluation runs in Gate 2)
                     → List all FAQs (even extra ones — informational)
7. NLP TRAINING      Each dialog has minimum utterances (per manifest config)
8. GLOBAL SETTINGS   DialogGPT status, supported language, session timeout
9. PUBLISH STATUS    Bot is published (via Bot Details API)
```

**Output:** CBM context object (used throughout evaluation) + structural readiness report + specific gap feedback.

**Gate 1 fail:** Candidate receives structural feedback immediately. No live testing runs. State → `COMPLETED_STRUCTURAL`.

---

## 9. Gate 2 — Live Testing (Webhook Conversations)

Runs one task at a time, sequentially (tasks have dependencies). Takes 3–10 minutes total.

For each task:
1. Send `SESSION_CLOSURE` to end any lingering session
2. Generate unique `from.id`: `eval-{submissionId}-{taskId}`
3. Send `ON_CONNECT` event (V2) or opening message (V1)
4. Inject evaluation context (selected persona values + captured outputs from prior tasks)
5. Run Actor conversation loop (see Section 14)
6. After `endOfTask: true` (or turn limit), record transcript + entity tracking log
7. Take API before/after snapshots
8. Send `SESSION_CLOSURE`
9. Store all evidence for Gate 3

**Task execution order:** Determined by dependency graph. Tasks with no dependencies run first. Dependent tasks run after their prerequisites complete.

**If a task fails mid-conversation (system error):** Log the partial transcript. Mark task as `SYSTEM_ERROR`. Continue to non-dependent tasks. Dependent tasks are skipped with reason `DEPENDENCY_FAILED`.

### FAQ evaluation

After all webhook tasks complete, FAQ questions are sent sequentially via the same webhook driver — each in its own isolated session.

For each FAQ task:
1. Generate unique `from.id`: `eval-{submissionId}-{taskId}`
2. Send the FAQ question as a text message
3. Poll for bot response
4. Extract response text from transcript
5. Compute semantic similarity between response text and manifest `expectedAnswer` using a multilingual sentence-transformers model — handles responses in any supported language regardless of the language `expectedAnswer` is written in
6. Pass if similarity ≥ `similarityThreshold`
7. Store result and transcript as evidence

**Scoring:** Binary — full points if similarity meets threshold, zero if not.

**Failure mode — generic deflection:** A bot that responds with "Please contact our front desk" scores low because the response does not semantically match the configured answer — correct outcome, the knowledge graph was not properly configured. Feedback: *"Your bot responded but the answer didn't match the configured knowledge graph response — check your FAQ answer content."*

**Manifest Readiness Validator:** Flags any FAQ task where `similarityThreshold` is missing before the evaluation runs.

---

## 10. Gate 3 — Evidence Collection & Debug Log Polling

After Gate 2, transcript and API snapshots are immediately available. Debug logs may not be.

### Debug log retry schedule

```javascript
const intervals = [0, 5*60, 15*60, 30*60, 60*60, 2*60*60, 4*60*60, 8*60*60, 10*60*60];
//                 now   5m    15m    30m    1h     2h      4h      8h      10h

For each interval:
  1. Call getDebugLog(sessionId) for each task session
  2. If logs returned AND contain intent/entity/service events:
     → Mark as AVAILABLE. Cancel remaining retries. Proceed to Gate 4.
  3. If logs returned but empty:
     → Continue to next interval (logs not yet populated)
  4. If API error (401, 500, timeout):
     → Log error, continue to next interval

After all intervals exhausted:
  → State: GRADING_WITHOUT_DEBUG
  → Grade with available streams (no debug)
  → Flag for manual review: "Debug logs unavailable — confidence reduced"
  → Lower confidence on checks that depend on debug evidence
```

### Partial grading without debug logs

| Check type | Without debug logs | Confidence |
|-----------|-------------------|------------|
| Entity collected | Transcript shows value provided | Medium |
| API call success | API snapshot shows record created | High (API is authoritative) |
| Intent matched | Cannot verify | Low |
| Service node error | Cannot diagnose root cause | Must cite API result only |
| NLP quality | Cannot score | Skip NLP feedback |

Flag in feedback: *"Some diagnostic details may be limited as internal bot logs were unavailable at time of evaluation."*

---

## 11. Gate 4 — Grading & Feedback

After all evidence is collected, the Judge evaluates each check independently (see Section 14). All Judge calls for a single task can be parallelized. Feedback Writer runs after all checks in a task are graded.

**Sanity checks before releasing results:**

```
1. SCORE SANITY     If total = 0/100: Did any task succeed?
                    If T5-WELCOME passed but everything else = 0 → systemic issue.

2. TRANSCRIPT       If all tasks have < 3 turns: bot may be unresponsive.
                    If every bot response is empty or an error → flag.

3. API EVIDENCE     If API snapshots are identical before/after across ALL tasks:
                    Either bot never called API, or wrong backendApiUrl.

4. ENTITY TRACKING  If actor injected 0 entities across all tasks:
                    Actor/entity matching is broken, not the candidate's bot.

5. CONSISTENCY      If transcript shows "Booked!" but API shows no record AND
                    debug shows no service node: session isolation issue?
```

Any sanity check failure → Flag for manual review with diagnostic detail.

---

## 12. Evaluation Lifecycle State Machine

```
SUBMITTED
    │
    ▼
PREBUILD_RUNNING ──── Gate 1 fail ──→ COMPLETED_STRUCTURAL
    │
    ▼
LIVE_TESTING ──── connectivity fail ──→ FAILED_CONNECTIVITY
    │
    ▼
LIVE_TESTING (running)
    │
    ▼
EVIDENCE_COLLECTED
    │
    ▼
AWAITING_DEBUG_LOGS ◄── retry schedule (0 → 10 hours)
    │
    ├── Logs available ──→ GRADING (5 streams webhook / 6 streams web driver)
    └── Max retries ──────→ GRADING_WITHOUT_DEBUG (no debug stream)
                                │
                                ▼
                            GRADED (results computed, NOT released)
                                │
                    ┌───────────┴───────────┐
               Calibration ON          Calibration OFF
                    │                       │
                    ▼                       ▼
          AWAITING_EVALUATOR_VERIFY  AWAITING_EVALUATOR_APPROVAL
                    │                       │
                    └───────────┬───────────┘
                                ▼
                            RELEASED
```

**State definitions:**

| State | What's happening |
|-------|-----------------|
| `SUBMITTED` | Received, queued |
| `PREBUILD_RUNNING` | CBM parsing + structural checks |
| `COMPLETED_STRUCTURAL` | Gate 1 failed — structural feedback only |
| `LIVE_TESTING` | Webhook conversations running |
| `EVIDENCE_COLLECTED` | Transcript + API snapshots gathered |
| `AWAITING_DEBUG_LOGS` | Polling Kore.ai at retry intervals |
| `GRADING` | All evidence gathered, grading each check |
| `GRADING_WITHOUT_DEBUG` | Grading without debug logs, flagged for review |
| `GRADED` | Results computed, not yet released |
| `AWAITING_EVALUATOR_VERIFY` | Calibration mode: deep review |
| `AWAITING_EVALUATOR_APPROVAL` | Normal mode: light review |
| `RELEASED` | Visible to candidate |
| `FAILED_CONNECTIVITY` | Bot unreachable at Gate 2 start — candidate notified to resubmit |
| `FAILED_SYSTEM_ERROR` | System issue, manual review required |

**What the candidate sees at each state:**

```
SUBMITTED          → "Your submission has been received. Evaluation will begin shortly."
PREBUILD_RUNNING   → "Analyzing your bot's structure..."
LIVE_TESTING       → "Testing Task 1: Book Appointment... Task 2: Check Status..."
EVIDENCE_COLLECTED → "Test conversations complete. Gathering diagnostic data..."
AWAITING_DEBUG     → "Evaluation in progress. Collecting detailed analysis data."
GRADING            → "Computing your results..."
GRADED             → "Evaluation complete. Your results are being reviewed."
RELEASED           → Score, per-task breakdown, full feedback
FAILED_CONNECTIVITY→ "Your bot could not be reached during testing. Please verify
                       your webhook is active and resubmit."
FAILED_SYSTEM_ERROR→ "We encountered an issue. Flagged for manual review. You'll
                       hear back within 24 hours."
```

---

# Part 5 — Scoring Model

## 13. Scoring Architecture

The evaluator defines all scoring rules in the manifest. The system applies them. Nothing is hardcoded.

### Scoring strategies

| Strategy | How it works | When to use |
|----------|-------------|------------|
| `binary` | Pass = full points, Fail = 0 | Simple yes/no checks |
| `proportional` | Score = (passed/total) × maxPoints | Entity collection (4 of 6 = 67%) |
| `graduated` | Multiple defined levels with different scores | API verification (full / partial / error / none) |
| `bonus` | Points added only if check passes, no penalty if skipped | Negative tests, extra features |
| `penalty` | Points deducted if check fails | Critical errors that should reduce score even if other checks pass |

### Critical task logic

```
IF task.criticalTask = true
AND task.score < task.criticalThreshold% of task.maxPoints
THEN:
  candidate_can_pass = false
  REGARDLESS of total score

Feedback: "Your total score is 90/100, but Task 1 (Book Appointment)
scored below the critical threshold (15/35 = 43%, minimum: 50%).
This task is critical for passing."
```

### Evidence model — evidence streams per task

| Stream | Source | Authority |
|--------|--------|-----------|
| API Snapshot | Backend API before/after | **Highest** — ground truth |
| Debug Log | Kore.ai internal events | High — shows exactly what happened inside the bot |
| Transcript | Webhook conversation | Medium — shows what was said |
| Entity Tracking | Actor injection log | Medium — shows what values were provided and when |
| CBM Context | Bot export | Low — shows configuration, not runtime behaviour |

Webhook tasks use all five streams above. Web driver tasks add a sixth: **UI Interaction** (screenshots, element detection log, DOM interaction trace — produced by the Web Driver). Grading state machine counts reflect the task type: 5 streams for webhook tasks, 6 for web driver tasks.

**When evidence conflicts:** Use authority hierarchy: API > Debug > Transcript > Entity Tracking > CBM.

*Example:* Bot says "Booked!" (transcript) but API shows no new record (API) and debug shows ServiceNode returned 400 (debug). **Verdict: FAIL.** Root cause from debug. Fix suggestion from CBM service node config.

### Cross-referencing rules

**When evidence agrees:** Full confidence. *"Bot collected name (transcript ✓), entity extracted at 0.99 confidence (debug ✓), stored in API record (API ✓)."*

**When evidence partially agrees:** Grade based on authoritative stream. Note the discrepancy in feedback.

**When debug is unavailable:** Grade API checks from API snapshot (still high confidence). Downgrade entity/intent checks (medium confidence). Skip NLP quality checks.

### Scoring report format

```
SCORING SUMMARY — SUB-2026-0342
════════════════════════════════

Task          Max  Scored  Method     Status
T1-BOOK        35    28   Mixed      ▰▰▰▰▰▰▰▰░░ 80%
  B1 (intent)   3     3   Binary     ✓
  B2 (name)     4     4   Binary     ✓
  B5 (all ent) 5      3   Proport    ⚠ 3/5 entities (doctorType, phone missing)
  B7 (API)      8     5   Graduated  ⚠ Partial: doctorType null in record
  B8 (confirm)  4     4   Binary     ✓
  B9 (neg test) 3     3   Bonus      ✓

T2-GET         15    10   Mixed      ▰▰▰▰▰▰▰░░░ 67%
T3-MODIFY      15    12   Mixed      ▰▰▰▰▰▰▰▰░░ 80%
T4-CANCEL      15    13   Mixed      ▰▰▰▰▰▰▰▰▰░ 87%
T5-WELCOME      5     5   Binary     ▰▰▰▰▰▰▰▰▰▰ 100%
FAQ            10     8   Mixed      ▰▰▰▰▰▰▰▰░░ 80%

TOTAL: 76/95 (80%) — PASS ✓
Critical tasks: T1-BOOK 80% ≥ 50% threshold ✓
```

---

---

# Part 6 — LLM Mechanism

## 14. Actor, Judge, and Feedback Writer

The LLM plays three distinct roles per evaluation. They **must be separate calls** — never combined.

```
┌──────────────┐     ┌──────────────┐     ┌──────────────────┐
│    ACTOR      │     │    JUDGE      │     │  FEEDBACK WRITER  │
│               │     │               │     │                   │
│ Plays persona │     │ Reads evidence│     │ Writes readable   │
│ in live convo │     │ verdicts each │     │ feedback from     │
│               │     │ check         │     │ Judge verdicts    │
│ temp = 0      │     │ temp = 0      │     │ temp = 0.3        │
│ DURING Gate 2 │     │ AFTER Gate 3  │     │ AFTER judging     │
└──────────────┘     └──────────────┘     └──────────────────┘
```

**Why separate roles matter:** If the Actor also judges, it has insider knowledge of its own intent and may be too lenient or strict. The Judge must see only what actually happened — same as a human reviewer reading a transcript blind.

---

### Role 1: The Actor

**What it does:** Plays a specific persona in the webhook conversation, goal-driven rather than conversational. One LLM call per turn.

#### Value pools and anti-gaming

The manifest defines pools. At evaluation start, one value is randomly selected per pool and locked for the entire evaluation. A correctly built bot handles any value — not just a hardcoded one.

```
Selected for this evaluation (random):
  patientName: "Rajesh Kumar"
  date:        "02-04-2026"
  doctorType:  "Orthopedic"
  phone:       "8765432109"
  time:        "2:00 PM"
```

#### Evaluation context — cross-task persistence

```jsonc
// evaluationContext.json — created at evaluation start, updated after each task
{
  "evaluationId": "EVAL-2026-0342-02",
  "selectedValues": {
    "patientName": "Rajesh Kumar",
    "date": "02-04-2026",
    "doctorType": "Orthopedic",
    "phone": "8765432109",
    "time": "2:00 PM"
  },
  "taskOutputs": {
    "T1-BOOK": {
      "status": "completed",
      "capturedValues": {
        "bookingId": "APT-442",
        "confirmedDate": "02-04-2026"
      }
    },
    "T3-MODIFY": {
      "status": "pending",
      "modifiedValues": {
        "newDate": "15-04-2026",
        "newTime": "4:45 PM"
      }
    }
  },
  "currentTask": "T3-MODIFY"
}
```

#### Actor prompt (T3-MODIFY example)

```
You are Rajesh Kumar.

You are interacting with a chatbot to modify your existing appointment.

CONTEXT FROM PREVIOUS INTERACTIONS:
  You previously booked an appointment:
    Booking ID: APT-442
    Original Date: 02-04-2026
    Doctor: Orthopedic
  You now want to change the date.

INFORMATION YOU HAVE:
  Your Name: Rajesh Kumar
  Your Booking ID: APT-442
  New Date: 15-04-2026
  New Time: 4:45 PM

YOUR GOAL: Modify appointment APT-442 to the new date and time.

CRITICAL RULES:
1. Every response MUST move the conversation toward your goal.
2. If the bot greets you or says something open-ended, immediately state your intent.
3. When the bot asks a question, answer it directly. Never ask questions back.
4. If the bot asks for something not in your list, say "I don't have that" and redirect.
5. If stuck (bot repeating or off-topic) after 2 turns, re-state intent forcefully.
6. Do NOT engage in small talk. Do NOT say "as an AI".

CONVERSATION SO FAR: {transcript}
BOT'S LATEST MESSAGE: "{botResponse}"
YOUR RESPONSE:
```

#### Actor behavior rules (always active)

```
RULE 1: STATE INTENT ON FIRST TURN
  Whatever the bot says first, Actor's first response must include task intent.
  Bot: "Hi!"                       → Actor: "Hi, I'd like to modify my appointment."
  Bot: (shows menu with buttons)   → Actor clicks [Modify Appointment]

RULE 2: ANSWER QUESTIONS WITH VALUES, NEVER WITH QUESTIONS
  Bot: "What is your name?"        → Actor: "Rajesh Kumar"          ✓
  Bot: "What is your name?"        → Actor: "Do you need full name?" ✗

RULE 3: STALL DETECTION
  If 2 consecutive turns pass without bot asking for an entity or advancing:
  → Re-state intent. After 3 stalls: provide ALL remaining entity values in one message.
  → If bot still doesn't progress after 3 stalls: terminate task.

RULE 4: CONFIRM AND MOVE ON
  Bot: "Confirm your appointment?"  → Actor: "Yes"  ✓
  Bot: "Confirm your appointment?"  → Actor: "Yes, thank you so much!" ✗

RULE 5: HANDLE RESPONSE TYPES FUNCTIONALLY
  Buttons    → Click the one matching task goal (no deliberation)
  Forms      → Fill all fields from entity list, submit immediately
  Confirmation → "Yes" (one word)
  Error      → Log it, terminate task, mark as TASK_ERROR
```

#### Post-task value extraction

After the task conversation ends, a dedicated LLM call extracts dynamic outputs (like booking IDs):

```
Given the following conversation, extract the values listed below.
Return ONLY JSON. If a value cannot be found, set it to null.

TRANSCRIPT: [full task transcript]

VALUES TO EXTRACT:
  - bookingId: The appointment/booking ID given by the bot

EXTRACTED:
{ "bookingId": "APT-442" }
```

These feed into `evaluationContext.taskOutputs` and are available to all subsequent tasks.

---

### Role 2: The Judge

**What it does:** Receives one specific check definition + relevant evidence, produces a structured verdict. One call per check. Checks within a task can be parallelized.

#### Judge prompt structure

```
You are an evaluation judge. Determine whether a chatbot passed a specific check.
Base your verdict ONLY on the evidence below. Do not assume or infer.
If evidence doesn't clearly show the check passed, it FAILED.

CHECK:
  ID: B7
  Description: "Bot calls POST API with correct data"
  Scoring: graduated
  What to look for: "API must show new record matching ALL persona field values."

EVIDENCE STREAM 1 — TRANSCRIPT: [relevant turns only]
EVIDENCE STREAM 2 — ENTITY TRACKING: [what Actor provided, when]
EVIDENCE STREAM 3 — API SNAPSHOT DIFF: [before vs after]
EVIDENCE STREAM 4 — DEBUG LOG: [service node events]
EVIDENCE STREAM 5 — CBM CONFIG: [service node URL, method, request body mapping]

Respond in this JSON format:
{
  "verdict": "PASS | PARTIAL | FAIL",
  "confidence": "HIGH | MEDIUM | LOW",
  "scoreAwarded": <number>,
  "evidenceCited": ["specific evidence items"],
  "reasoning": "2-3 sentences"
}
```

**Focused evidence assembly:** Each check only receives relevant evidence. Entity checks don't get API snapshots. API checks don't get entity tracking for unrelated entities. This keeps Judge prompts focused and improves accuracy.

#### Judge verdicts by check type

| Check type | Evidence priority | PASS criteria |
|-----------|------------------|---------------|
| Entity collection | Debug > Entity tracking > Transcript | Bot asked → value provided → debug confirms extraction |
| API call | API snapshot > Debug > Transcript | New record with ALL field values matching persona |
| Intent recognition | Debug (NL Analysis) > Transcript | Correct intent, confidence > threshold |
| Flow behavior | Transcript > CBM | Conversation followed expected path |
| FAQ | Transcript > CBM | Bot response is semantically similar to `expectedAnswer` (similarity ≥ `similarityThreshold`) |
| Negative test | Transcript > Debug | Bot rejected invalid input and asked again |

---

### Role 3: The Feedback Writer

**What it does:** Takes Judge verdicts and evidence, produces human-readable candidate feedback. Constructive, specific, and actionable.

#### Feedback Writer rules

```
1. Start with what worked well.
2. For failures: explain WHAT went wrong and WHY (use debug info if available).
3. For each issue: suggest a SPECIFIC fix. Never say "improve your bot".
4. Say "the bot didn't" not "you didn't".
5. Reference specific turn numbers and entity names.
6. If debug logs provided root cause, include it.
7. Keep concise: 3-5 sentences per task.
8. Suppress downstream consequence failures when a root cause failure already fired.
   Example: if onCarouselEntityNotExtracted fired, suppress onCarouselApiValueMissing —
   the API missing the value is a consequence of the entity not being captured, not a
   separate issue. Fix the entity extraction and the API record fixes itself. Showing
   both messages sends the candidate in two directions for one root cause.
   General rule: if failure B is a known consequence of failure A, show A only.
```

#### Feedback Writer output example

```markdown
### Task 1: Book Appointment — 28/35 (80%)

**What worked well:**
Your bot correctly triggered the booking intent and collected patient name, date,
and phone number smoothly. The confirmation message with the booking ID was clear.

**What needs fixing:**
- **Doctor Type entity not extracted (Turn 9):** The user said "Cardiologist"
  but your entity node 'doctorType' is a List type that doesn't include it in its
  enumerated values. Add all required specialties to the entity's value list.

- **API record incomplete:** Because doctorType wasn't extracted, the POST call
  sent `doctorType: null`. Fix the entity issue above and this resolves automatically.
```

---

### LLM call budget per typical evaluation

```
ACTOR (5 tasks, avg 10 turns each):       ~46 calls
JUDGE (5 tasks, avg 8 checks each):       ~40 calls  ← parallelized per task
FEEDBACK WRITER (5 tasks + 1 summary):      6 calls
POST-TASK VALUE EXTRACTION (5 tasks):       5 calls
──────────────────────────────────────────────────
TOTAL:                                    ~97 calls

Local LLM (LM Studio, ~2s/call):   ~3 minutes
Cloud LLM (parallel Judge calls):  ~1.5 minutes
```

### LLM failure handling

```
ACTOR fails mid-turn:
  → Retry up to 3 times. If all fail: terminate task → SYSTEM_ERROR.
  → Other tasks still proceed (T1 failure doesn't block T5).

JUDGE fails on a check:
  → Retry up to 3 times. If all fail: mark check as JUDGE_ERROR.
  → Score = 0 for that check, flagged: "Unable to evaluate — system error".
  → Other checks still proceed.

FEEDBACK WRITER fails:
  → Retry up to 3 times. If all fail: use template fallback (no LLM).
  → "Check B4 (Doctor Type): FAIL. The bot did not extract this entity."
```

---

# Part 7 — Real-World Challenges

## 15. Challenges 1–25

### Challenge 1: Polling for Service Node Responses
When a service node calls an external API, the webhook returns a `pollId` instead of the final message. **Solution:** Poll `GET /chatbot/v2/webhook/{botId}/poll/{pollId}` at 1-second intervals until `endOfTask: true` or data messages appear. Timeout: 30 seconds.

### Challenge 2: Rate Limiting (429)
Rapid message sequences trigger 429. **Solution:** Exponential backoff with jitter. `interMessageDelayMs: 1500` default. Max 1 concurrent conversation per bot.

### Challenge 3: Webhook Timeout (504)
15-second sync timeout. Complex service nodes exceed it. **Solution:** V2 `pollId` mechanism handles this natively. For V1: detect 504, retry with backoff. Distinguish from bot-not-published (both can 504).

### Challenge 4: Digital Forms
Some bots use form nodes — bot sends form definition, client must respond with `formData`. **Solution:** Detect `type: "template"` with form definition. Extract component IDs. Map to persona facts using semantic hints. Respond with `message.type: "formData"`, `message.val: { formId, data: [...] }`.

### Challenge 5: Welcome Task Not Triggering
`ON_CONNECT` doesn't always fire in V1. **Solution:** For V2, explicitly send `ON_CONNECT` event as the first message.

### Challenge 6: Session Isolation Between Tasks
Same `from.id` causes context bleed between tasks. **Solution:** Unique `from.id` per task: `eval-{submissionId}-{taskId}`. Send `SESSION_CLOSURE` after each task. For dependent tasks, inject context through Actor persona (not session state).

### Challenge 7: Entity Recognition Uncertainty
Entity extraction confidence varies. **Solution:** Use debug log events to distinguish: (a) entity never asked → structural issue, (b) entity asked but extraction failed → NLP training issue. Map to different feedback.

### Challenge 8: Incomplete Debug Log Diagnostics
Debug shows HTTP 400 but not the full request payload. **Solution:** Cross-reference debug (status code) + CBM (request body mapping) + entity tracking (which values were provided) to reconstruct root cause.

### Challenge 9: Multiple Messages Per Turn
Bot sends 2–5 messages in one response (`data[]` array). **Solution:** Concatenate all `data[].val` items for transcript. Analyze each independently. Confirmation message may be in `data[2]` while question is in `data[3]`.

### Challenge 10: Knowing When a Task Is Done
**Solution:** V2 provides `endOfTask: true` with `completedTaskName`. Cross-reference `completedTaskName` against manifest `dialogTaskName`. V1 fallback: Actor LLM judgment + turn limit.

### Challenge 11: Cross-Task Data Capture and Dependency Failure

T1 creates a booking ID needed by T2–T4. The naive risk: if T1 fails to capture the ID, the entire evaluation is meaningless — T2, T3, T4 all block.

#### Primary capture path

`captureFromConversation` regex patterns extract dynamic outputs from the transcript immediately after each task ends. A secondary extraction LLM call confirms ambiguous matches. If regex fails, the API after-snapshot is checked — the booking record was created, so the ID exists in the API response.

#### Synthetic dependency injection (fallback)

If T1 fails to capture the booking ID through **both** the transcript and the API snapshot — meaning T1 genuinely failed to execute the booking — GovernIQ does not abandon the evaluation. Instead:

```
1. GovernIQ calls the candidate's backend API directly (POST /appointments)
   using the persona values from T1's entity collection attempt.
2. The response contains the booking ID (e.g. APT-999).
3. This ID is injected into RuntimeContext as if T1 had captured it.
4. T2, T3, T4 proceed normally using the injected ID.
5. The evaluation scorecard is flagged: "T2–T4 evaluated with synthetic
   dependency — booking ID was created by GovernIQ, not the candidate's bot."
6. T1 score reflects its actual failures (entity misses, API call failure, etc.)
7. T2–T4 scores reflect only T2–T4 bot behaviour.
```

This pattern preserves the integrity of every task's independent evaluation. A failure in T1 does not contaminate the T2 score — and a candidate whose T1 partially works but T2/T3/T4 are perfect can still receive appropriate credit.

**Precondition:** Backend API must accept direct POST calls (not bot-only). This is already true for mock API backends. Documented in Section 28 (Pre-Build Validation) as a mandatory API test.

### Challenge 12: Buttons and Templates
Bot sends buttons — Actor can't click. **Solution:** Parse template response. Respond with button `payload` value (not label text). Use semantic matching to select the correct button.

### Challenge 13: JWT `appId` Case Sensitivity
Kore.ai only accepts `appId` (exact case). **Solution:** Hardcode JWT payload key as `appId`. Validate at submission — warn if clientId format is unexpected.

### Challenge 14: Bot is Draft (Not Published)
Webhook only works with published bots. **Solution:** Call Bot Details API in Gate 0 to check publish status. Return immediate feedback if not published.

### Challenge 15: Manifest Insufficient Context
Evaluator writes "bot should collect patient name" without specifying what the bot asks. **Solution:** Manifest Readiness Validator checks for missing `semanticHints`, missing `lookFor` criteria, missing dependency `requiredData`. When bot export is available, auto-suggest hints from entity node prompts.

### Challenge 16: MockAPI Data Pollution
Previous evaluations leave stale records. **Solution:** Compare before/after snapshots using exact field matching against persona values (not just record count). Clean up after each evaluation. Use unique persona values per evaluation.

### Challenge 17: Bot Version Drift
Candidate exports bot (v1) then publishes fixes (v2). CBM is stale. **Solution:** Check bot version/timestamp from Bot Details API. If bot modified after export timestamp → warn: "Bot export appears outdated. CBM insights are advisory."

### Challenge 18: LLM Non-Determinism
Actor may respond differently on each run. **Solution:** Actor temperature = 0. Structured prompts constrain to specific values. For calibration: run same test 3x, verify results are consistent.

### Challenge 19: Timezone and Locale Issues
Date "25-03-2026" can be parsed as March 25 or 25 March depending on locale. **Solution:** Manifest specifies `format: "DD-MM-YYYY"`. Actor provides dates in that exact format. Debug log confirms correct parsing.

### Challenge 20: Backend API Schema Unknown
Candidate's MockAPI may have different field names. **Solution:** Fetch one existing record pre-evaluation to learn schema. Use manifest `expectedFieldMappings` to define expected field names.

### Challenge 21: Concurrent Evaluations for Same Assignment
Multiple candidates share the same MockAPI (misconfiguration). **Solution:** Tier 1 plagiarism check catches this (same MockAPI URL). Each candidate should have their own MockAPI project.

### Challenge 22: Webhook URL Expires After Submission
Bot unpublished between submission and evaluation start. **Solution:** Connectivity check runs right before Gate 2 (not just at Gate 0). If fails: `FAILED_CONNECTIVITY` state, candidate notified to resubmit.

### Challenge 23: Evaluator Workload
One evaluator reviewing 50+ submissions is unsustainable. **Solution:** Dashboard sorts by flags: 🔴 manual review required, 🟡 low confidence, 🟢 high confidence. Bulk approve for 🟢. Delegation support for shared queues.

### Challenge 24: Audit Trail for Disputes
Candidate disputes grade. **Solution:** Every evaluation produces an immutable audit trail: full transcript, actor prompts + LLM responses, API snapshots with timestamps, debug logs, grading logic, evaluator actions. Hash of each record for tamper-evidence.

### Challenge 25: Bot Exceeds Requirements
Candidate builds extra features not in the manifest. **Solution:** Only evaluate manifest-defined checks. Extra features noted as "Strengths observed beyond requirements" (informational only). Evaluator can award bonus points in manual review.

---

# Part 8 — Data & Operations

## 16. Data Persistence

### POC: File-based storage

```
data/
├── assignments/
│   └── ASSIGN-MEDI-001/
│       ├── assignment.json       ← Assignment Use Case (Section 4 schema)
│       ├── manifest.json         ← Evaluation Manifest (Section 5 schema)
│       ├── manifest-meta.json    ← Lifecycle state + calibration stats
│       └── calibration/
│           ├── runs.json
│           └── agreements.json
│
├── submissions/
│   └── SUB-2026-0342/
│       ├── submission.json       ← Metadata, state history
│       ├── bot-export.zip
│       └── attempts/
│           └── ATT-01/
│               ├── attempt.json
│               ├── cbm.json
│               ├── prebuild-report.json
│               ├── tasks/
│               │   ├── T1-BOOK/
│               │   │   ├── transcript.json
│               │   │   ├── api-snapshot-before.json
│               │   │   ├── api-snapshot-after.json
│               │   │   ├── debug-log.json
│               │   │   ├── entity-tracking.json
│               │   │   ├── grading.json
│               │   │   └── actor-log.json
│               │   └── [T2-T5 same structure]
│               ├── evaluation-context.json
│               ├── scoring-summary.json
│               ├── feedback-report.json
│               ├── evaluator-review.json
│               └── audit-trail.json
│
├── candidates/
│   └── CAND-001.json
│
├── evaluators/
│   └── EVAL-001.json
│
└── queue/
    ├── pending.json
    ├── active.json
    ├── retry.json              ← Debug log retry schedule
    └── manual-review.json
```

**Key file schemas (summary):**

`submission.json` — submissionId, candidateId, assignmentId, webhookUrl, backendApiUrl, botId, currentState, stateHistory. **No credentials ever stored.**

`attempt.json` — attemptId, attemptNumber, previousAttemptId, status, overallScore, maxScore, passed, criticalTasksAllPassed, manifestVersion, taskScores, debugLogsAvailable, evaluatorReviewed, releasedAt.

`manifest-meta.json` — lifecycleState (DRAFT/CALIBRATING/SHADOW/PRODUCTION/ARCHIVED), calibrationStats (agreementRate, productionThreshold), attemptPolicy.

### Production: MongoDB + S3

| Collection | Indexes |
|-----------|---------|
| `assignments` | assignmentId, lifecycleState |
| `submissions` | submissionId, candidateId, assignmentId, currentState |
| `attempts` | attemptId, submissionId, status |
| `taskResults` | attemptId, taskId |
| `candidates` | candidateId, email |
| `evaluators` | evaluatorId, email |
| `queue` | status, priority, scheduledAt |
| `auditLog` | submissionId, timestamp |

Bot export ZIPs and large evidence files (transcripts, debug logs) go to S3/Azure Blob with path references in the database.

### Migration path

```
PHASE 1 (POC):     JSON files on disk. No auth. In-memory queue.
PHASE 2 (Pilot):   JSON files + simple password login + file-based queue (survives restart).
PHASE 3 (Prod):    MongoDB + S3 + JWT auth/SSO + RBAC + Redis job queue (Bull/BullMQ).
```

### User roles

| Role | Can do |
|------|--------|
| **Admin** | Everything |
| **Evaluator** | Create/edit assignments and manifests. Control manifest lifecycle. Review/approve/override results. Trigger resubmission. View all submissions for their assignments. |
| **Candidate** | View assigned assignments. Submit. View own results and feedback. Resubmit within attempt limits. |
| **System** | Run evaluations. Generate JWTs. Access Kore.ai APIs. Update submission states. Cannot release results directly. |

---

## 17. Submission Queue

```
Priority order:
  1. Re-runs from manual review (evaluator is waiting)
  2. First-time submissions (in order received)
  3. Retry runs (debug log polling)

Concurrency limits:
  Max 1 active webhook conversation per bot (Kore.ai rate limits)
  Max 5 concurrent evaluations total (LLM capacity)
  Evaluations for different bots can run in parallel
  Tasks within one evaluation run sequentially (dependencies)
```

### Performance expectations

| Gate | Duration | Bottleneck |
|------|----------|-----------|
| Gate 0 (Validation) | < 15 seconds | Network latency to Kore.ai + API |
| Gate 1 (Prebuild) | < 30 seconds | ZIP parsing + CBM generation |
| Gate 2 (Live testing) | 3–10 minutes | 5 tasks × 10 turns × 1.5s delay |
| Debug log collection | 0–10 hours | Kore.ai API (outside our control) |
| Gate 4 (Grading) | < 2 minutes | LLM calls (parallelized per task) |
| Feedback generation | < 30 seconds | LLM calls |

**Target:** Results within 24 hours of submission (including debug log retry + evaluator review).

---

## 18. Data Retention & Credential Security

### Retention policy

```
PERMANENT:
  Submission metadata, evaluation results, scores, feedback report,
  attempt history, manifest version snapshot

RETAIN: assignment duration + 90 days
  Bot export (.zip), CBM, raw transcripts, API snapshots, debug logs,
  evaluator review records

DELETE after 30 days:
  Actor prompts + LLM responses, polling/retry logs, rate limit event logs

DELETE immediately (never persist to disk):
  App credentials (clientId + clientSecret)
  Admin credentials
  JWT tokens (ephemeral, regenerated each use)
```

### Credential security

```
FLOW:
  1. Candidate enters credentials in form (HTTPS only)
  2. Server sanitizes → validates connectivity
  3. NOTHING stored after Gate 0 — credentials used only during evaluation
     and then purged from memory
  4. During evaluation: passed to worker process as environment variables
  5. Never logged, never in database, never in any file

OPTION: If retry is needed (system error, not candidate's fault):
  → Ask candidate to resubmit with credentials
  → Evaluator can enter credentials manually in the retry interface
```

---

## 19. Monitoring & Alerting

### Alert immediately

```
- 3+ consecutive webhook 401s for same bot (credential or bot issue)
- 5+ evaluations stuck in AWAITING_DEBUG_LOGS > 12 hours
- Manual review queue > 10 items
- LLM provider unreachable
- Any sanity check failure rate > 20% in a 24-hour window
```

### Daily digest

```
- Evaluation throughput (submissions/day, avg time to result)
- Calibration agreement rate trending
- Most common failure reasons
- Sanity check trigger rate
- Queue depth and average wait time
```

---

---

# Part 9 — Quality & Trust

## 20. Manual Review Escalation

### When to escalate

| Failure type | Whose fault | System action |
|-------------|-------------|---------------|
| Bot doesn't work | Candidate | Auto-grade, provide feedback |
| Webhook 401 | Candidate (wrong credentials) | Return credential error feedback |
| MockAPI is down | External service | Retry later, then escalate |
| Rate limited (429) | System (too many requests) | Retry with backoff, then escalate |
| LLM provider failure | System | Retry, then escalate |
| Bot export corrupt | Candidate or system | Attempt parse, escalate if ambiguous |
| Kore.ai platform outage | Platform | Detect via 5xx errors, escalate |
| Nonsensical results | System (logic bug) | Sanity checks catch this, escalate |

### Auto-detection of system vs candidate errors

```
Webhook 401:
  → Candidate error. Auto-return: "Invalid app credentials."

Webhook 504 consistently:
  Did first message (ON_CONNECT) succeed?
    YES → Bot reachable, but service nodes are slow → candidate's external API
    NO  → Bot may not be published → auto-return: "Unable to reach bot."

MockAPI returns errors:
  Can we reach the MockAPI URL at all?
    YES → Endpoint path may be wrong → candidate error
    NO  → MockAPI is down → escalate, retry later
```

### Manual review queue format

```
SUBMISSION: SUB-2026-0342  STATUS: FAILED_SYSTEM_ERROR
REASON: Webhook 504 on 3 consecutive turns during T1-BOOK.
        T2–T4 skipped (dependency). Only T5-WELCOME completed.

EVIDENCE:
  ✓ Bot export parsed (CBM available)
  ✓ T5-WELCOME transcript (6 turns, completed)
  ✗ T1-BOOK transcript (3 turns, 504 on turn 3)
  ✗ API snapshots (T1 didn't complete)
  ✗ Debug logs (not fetched)

EVALUATOR OPTIONS:
  [ ] Retry evaluation
  [ ] Complete evaluation manually (Talk to Bot)
  [ ] Grade with partial evidence (welcome task only)
  [ ] Contact candidate (wrong webhook URL?)
  [ ] Dismiss (unresolvable)
```

---

## 21. Calibration Mode

Every new manifest starts in calibration. Results are never released to candidates until calibration passes.

### Four calibration phases

**Phase 1 — Dry Run (zero candidates)**
Evaluator uses a known-good bot. System runs evaluation. Evaluator reviews every check: "Bot collected patient name → PASS → Agree? [✓] [✗]". Iterate until 100% agreement.

**Phase 2 — Known-Bad Run (zero candidates)**
Evaluator uses a deliberately broken bot (missing entities, wrong API URL, no NLP training). System must detect all planted defects. Verifies negative detection and diagnostic accuracy.

**Phase 3 — Shadow Mode (real candidates)**
Real submissions evaluated. Results held. Evaluator reviews each one. Track agreement rate: 10 candidates → 8/10 = 80% confidence. Evaluator sets threshold ("auto-release at > 95%").

**Phase 4 — Production Mode**
Agreement rate exceeds threshold. Results auto-released unless flagged by sanity checks. Evaluator reviews flagged submissions only + 10% random spot checks. If agreement rate drops → fall back to shadow mode.

### Calibration metrics

| Metric | Target |
|--------|--------|
| Agreement rate | > 95% |
| False positive rate (PASS when should FAIL) | < 5% |
| False negative rate (FAIL when should PASS) | < 5% |
| Root cause accuracy | > 80% |

### Calibration data as training signal

Every evaluator override feeds back into the system:
- Evaluator changes PASS → FAIL: `lookFor` criteria need tightening
- Evaluator changes FAIL → PASS: check is too strict or evidence misread
- Evaluator edits feedback: template needs updating
- Evaluator adds a check: manifest was incomplete

---

## 22. Manifest Lifecycle

### States

```
DRAFT → CALIBRATING → SHADOW → PRODUCTION → ARCHIVED
```

| State | Submissions | Results released | Manifest editable |
|-------|-------------|-----------------|-------------------|
| `DRAFT` | Rejected | N/A | ✓ |
| `CALIBRATING` | Evaluator's test bots only | Never (calibration only) | ✓ |
| `SHADOW` | Real candidates | Never (evaluator reviews all) | ✗ (locked) |
| `PRODUCTION` | Real candidates | Auto-release (unless flagged) | ✗ (locked) |
| `ARCHIVED` | Rejected | N/A | ✗ |

Transitions are controlled by the evaluator from the management portal. Moving to PRODUCTION requires agreement rate ≥ threshold (or evaluator override with written justification).

**Manifest versioning:** Once in SHADOW or PRODUCTION, the manifest is locked. Edits require a new version. In-progress evaluations always use the version active at submission time (`attempt.json` records `manifestVersion`).

---

## 23. Plagiarism Detection

### The environment challenge

All candidates work on the same assignment. Natural overlap is expected: same task names, same FAQ topics, similar entity prompts. Traditional text-similarity detection produces constant false positives. We need signals that distinguish independent work from copying.

### Tier 1: Infrastructure check (instant, deterministic)

```
1. MockAPI URL match:
   Extract base URL from backendApiUrl. Compare against all other submissions.
   EXACT match → INSTANT FLAG. 100% deterministic — two candidates cannot
   independently create the same MockAPI project URL.

2. Bot ID match:
   Extract botId (st-xxx) from webhook URL.
   EXACT match → INSTANT FLAG. Two candidates cannot share the same bot.

→ Any Tier 1 match: Hold submission. Notify evaluator. No evaluation runs until cleared.
```

### Tier 2: Implementation fingerprint (runs during Gate 1)

```
Signal A: Dialog node labels (weight 0.35)
  Internal node labels are personal choices. "askName" vs "getName" vs "collectPatientName".
  If 3+ tasks have identical node label sequences → suspicious.

Signal B: Script node code (weight 0.30)
  Custom JavaScript. Normalize (strip comments, whitespace). Hash each block.
  Identical hashes → copied.

Signal C: Service node request body mappings (weight 0.20)
  How entities map to API payload fields. The mapping keys are personal choices.
  Identical mappings → suspicious.

Signal D: Entity validation patterns (weight 0.10)
  Custom regex for phone, date, email. Same regex → likely copied.

Signal E: Custom message text (weight 0.05)
  Only non-assignment-prescribed text. Low weight — natural overlap expected.

implementationScore = A×0.35 + B×0.30 + C×0.20 + D×0.10 + E×0.05
```

### Thresholds and actions

| Score | Action |
|-------|--------|
| 0.0 – 0.30 | No flag |
| 0.31 – 0.55 | ℹ️ Info: "Some similarities with SUB-XXX" |
| 0.56 – 0.75 | ⚠ Flag: "Multiple implementation similarities" |
| 0.76 – 1.00 | 🔴 Hold: "Near-identical — evaluator review required" |

### Self-submission exclusion

A candidate's own attempts (Attempt 1 vs Attempt 2) are **never** compared against each other. Only different candidates are compared.

### Assignment baseline exclusion

Evaluator registers text from the assignment document that naturally appears in all bots (example utterances, FAQ questions) — excluded from Tier 2 comparison.

---

## 24. Test and Dummy Submission Handling

Every submission carries a `submissionType` flag:

| Type | Stats counted? | Review queue? | Plagiarism? | Retention |
|------|---------------|---------------|-------------|-----------|
| `REAL` | ✓ | ✓ | ✓ | Permanent |
| `CALIBRATION` | ✗ | Calibration dashboard only | ✗ | Permanent (agreement tracking) |
| `TEST` | ✗ | ✗ | ✗ | 7 days |
| `DEMO` | ✗ | ✗ | ✗ | 24 hours |

**Test mode:** Admin enables test mode banner on candidate portal. All submissions while active are tagged `TEST`. Pre-configured test bot credentials stored in settings for convenience.

---

# Part 10 — Workflows

## 25. Candidate Communication

### In-app status (POC)

Real-time status updates via polling (`GET /api/submissions/{id}/status` every 10 seconds while candidate is on the portal).

```json
{
  "submissionId": "SUB-2026-0342",
  "currentState": "LIVE_TESTING",
  "stateDescription": "Testing your bot...",
  "progress": {
    "currentTask": "T2-GET",
    "tasksCompleted": 1,
    "tasksTotal": 6,
    "percentComplete": 25
  },
  "estimatedCompletion": "2026-03-22T08:30:00Z"
}
```

### Email notifications (production only)

3 emails maximum — not spammy:

1. **Submission confirmed** — "Your bot has been submitted for evaluation. Expected results: within 24 hours."
2. **Results available** — "Score: 84/95 (88%) — PASS. View your detailed feedback: [link]"
3. **Manual review triggered** — "We encountered an issue. Flagged for review. No action needed. Within 24 hours."

### Communication at each lifecycle state

| State | Candidate sees |
|-------|---------------|
| Submitted | "Your submission has been received. Evaluation will begin shortly." |
| Validation failed | Specific error messages + [Fix and Resubmit] button |
| Gate 1 running | "Analyzing your bot's structure..." |
| Gate 1 failed | Structural feedback immediately + email |
| Live testing | "Testing Task 1 of 5: Book Appointment ▶" |
| Awaiting debug logs | "Evaluation in progress. Collecting detailed analysis data." *(no mention of logs — internal)* |
| Grading | "Computing your results..." |
| Pending approval | "Evaluation complete. Your results are being reviewed." |
| Released | Score + per-task breakdown + full feedback |
| System error | "Flagged for manual review. You'll hear back within 24 hours." |

### Time expectations

On submission page before submitting:
> *"Evaluation typically takes 30 minutes to 24 hours depending on system load. You will receive a notification when your results are ready."*

On submission confirmation:
> *"Submitted at 1:35 PM IST, March 22, 2026. Expected completion: By 1:35 PM IST, March 23, 2026. Submission ID: SUB-2026-0342"*

---

## 26. Resubmission Flow

### When candidates resubmit

| Reason | What they provide | System behavior |
|--------|-------------------|-----------------|
| Validation failed | Fix credentials + resubmit | New submission, linked to same assignment |
| Gate 1 failed | New bot export + credentials | New attempt |
| Low score | New bot export + credentials | New attempt, fresh evaluation |
| System error → evaluator retry | Nothing (evaluator handles) | Same submission re-evaluated |
| Evaluator requests resubmission | New bot export + credentials | New attempt, evaluator notes shown |

### Resubmission UX

```
RESUBMIT — Medi-Assistant
─────────────────────────
Previous Attempt: #1 — Score: 72/95 (76%)

Key issues from your last attempt:
  ✗ Service node missing doctorType mapping (-5 pts)
  ✗ No date validation on entity node (-4 pts)
  ✗ FAQ 'insurance' has 0 alternate phrasings (-3 pts)

What to provide:
  [Upload new bot export]     ← Required
  [Webhook URL]               ← Pre-filled from last submission
  [App credentials]           ← Must re-enter (never stored)
  [Admin credentials]         ← Must re-enter (never stored)
  [Backend API URL]           ← Pre-filled from last submission

  [Submit Attempt #2]
```

### Attempt tracking

Each submission creates an `ATTEMPT` record with `attemptId`, `attemptNumber`, `previousAttemptId`, linking the attempt chain. Attempt policy (maxAttempts, cooldownMinutes) is configured per manifest.

---

## 27. Evaluator Dashboard & Workflows

### Evaluator actions on a submission

| Action | When to use |
|--------|-------------|
| **Approve & Release** | Evaluator agrees with auto grade |
| **Edit Feedback** | Feedback needs human tone or correction |
| **Override Score** | System mis-graded a check (requires written justification) |
| **Request Resubmission** | Score is fair but candidate can do better |
| **Retry Evaluation** | System error caused failure (not candidate's fault) |
| **Compare Attempts** | Side-by-side score deltas across attempts |
| **View Transcript** | Read full webhook conversation turn by turn |
| **View Debug Analysis** | Parsed debug log: intents, entities, service nodes |
| **View Evidence** | All evidence streams for a specific check |
| **Dismiss** | Completely wrong bot, unresolvable |
| **Wait for Logs** | Keep in queue — logs may appear later |

### Evaluator dashboard mockup

```
EVALUATOR DASHBOARD: Medi-Assistant
═══════════════════════════════════
Summary: Total 28 | Awaiting review 4 | Auto-released 18 | Manual review 2

NEEDS ACTION (by urgency):
──────────────────────────
🔴 SUB-0342 — System error (webhook 504)     [Retry] [Ask Resubmit] [Dismiss]
🔴 SUB-0351 — System error (LLM timeout)     [Retry] [Ask Resubmit] [Dismiss]
🟡 SUB-0347 — Graded without debug logs      [Approve] [Override] [Wait for Logs]
   Confidence: Medium (no debug logs) Score: 78/95
🟡 SUB-0350 — Resubmission pending           [Approve & Release] [Edit Feedback]
   Attempt #2 | Score: 91/95 | Previous: 72/95 | Change: +19 ▲

RECENTLY REVIEWED:
──────────────────
✅ SUB-0340 — Released  Score: 88/95  Approved by: EVAL-001
✅ SUB-0339 — Released  Score: 65/95  Approved with edits
```

### Attempt comparison view

```
CANDIDATE: Rahul Sharma — Medi-Assistant

Task         Att#1  Att#2  Change
T1-BOOK       28/35  33/35  +5 ▲
T2-GET        10/15  15/15  +5 ▲ Fixed
T3-MODIFY      8/15  11/15  +3 ▲
T4-CANCEL     12/15  12/15   0 ─
T5-WELCOME     5/5    5/5    0 ─
FAQ            9/10   8/10  -1 ▼
──────────────────────────────
TOTAL:        72/95  84/95  +12

[Compare Transcripts] [View Check-by-Check Delta]

Pending issues:
  ⚠ T3-MODIFY still partial API match (8→11, not 15)
  ⚠ FAQ score dropped (9→8)
```

---

# Part 11 — Platform Assumption Workbench

## 28. Platform Assumption Workbench

The workbench is the **first deliverable of the project** — built before any evaluation application code. It connects to real Kore.ai environments using real test bots and verifies every API and platform behaviour the evaluation engine depends on. The application is built only after the workbench produces verified results.

GovernIQ is designed to evaluate candidates across the Kore.ai product portfolio. The workbench maps the full API surface of every in-scope product before any evaluation component is designed or built. Any API that fails verification — does not exist, returns an unexpected structure, has undocumented constraints — is flagged immediately and the architecture is updated before development starts.

**Current scope:** Automation AI, Search AI, Quality AI, Case Management, Web SDK, KoreUtil libraries.

**Future scope (no current use case — API surface to be documented when needed):** Agent AI, AI for Work, Agent Platform.

---

### The method: browser DevTools as the authoritative source

Kore.ai documentation is often written against older versions, not updated when endpoints change, and sometimes wrong about field names and auth formats. **The only source of truth is a working request against a live environment.**

Every API call the Kore.ai platform makes to its own backend passes through the browser. Open Kore.ai in Chrome, open DevTools Network tab, filter XHR/Fetch, perform the action in the UI that corresponds to the API needed — send a test message, view debug logs, check a bot's publish status, enable a channel. DevTools shows the exact URL, exact headers, exact request body, exact response. Copy as curl. Run it against a test bot with your own credentials. That is the verified format.

**For JWT authentication:** Trigger a test message via Talk to Bot, watch the outgoing auth header in DevTools, decode the token at jwt.io. The decoded payload is the verified JWT format the platform accepted. Do this separately for app-scope and admin-scope tokens.

---

### Automation AI

Full API list: https://docs.kore.ai/xo/apis/automation/api-list/

| API | Workbench verification task |
|-----|----------------------------|
| **Webhook V2** | Exact request/response payload; `endOfTask`, `completedTaskName`, `endReason` field names; `pollId` presence for service nodes; `SESSION_CLOSURE` response; `ON_CONNECT` behaviour; rate limit threshold and `Retry-After` format; multi-message `data[]` array behaviour |
| **Debug Logs** — `GET /fetch-debug-logs/` | **Highest priority.** Verify whether it works for webhook channel — docs show IVR examples only. Record exact `channelType` string the UI passes when viewing a webhook session's logs. Test latency across 5+ sessions at different times of day. Verify whether the 700-statement/7-day retention limit applies to the API or only the UI |
| **Conversation History** — `GET /conversation-history/` | `sessionId` filtering behaviour, max date range, exact `components[].data.text` structure for template vs text responses |
| **Bot Export** — `POST /bot-export/` + `GET /bot-export-status/` | Parse real ZIP output. Confirm entity node prompt field names, service node URL and request body mapping structure, form node component ID format, knowledge graph structure. **Extract from a real export — do not use documentation field names** |
| **Bot Publish Status** — `GET /bot-publish-status/` | Response field name for publish state, possible values |
| **Get Bots** — `GET /get-bots/` | Full response structure including channel list — confirms how Gate 0 reads web channel enablement status |
| **Analytics** — `GET /get-analytics/` | Available metrics, filter params, date range support |
| **Find Intent** — `POST /find-intent/` | Whether GovernIQ can use this for NLP quality verification |
| **Digital Form response format** | Create a bot with a form node, trigger it, record: exact `data[].type` value, component ID structure, correct `formData` response format to submit |
| **Batch Testing** | Whether a public API endpoint exists or UI-only. If no public API, remove from architecture |
| **JWT authentication** | Verify `appId` case sensitivity; `userIdentity` mismatch behaviour; admin-scope vs app-scope payload differences; token expiry handling |
| **Rate limits** | Send messages without delay, record 429 response format, `Retry-After` header, cooldown period |

---

### KoreUtil Libraries

Reference: https://docs.kore.ai/xo/apis/automation/koreutil-libraries/

KoreUtil functions are available in script nodes, message nodes, and entity nodes. Understanding them is essential for interpreting bot implementation patterns during CBM audit and debug log analysis.

| Function | Relevance to GovernIQ |
|----------|----------------------|
| `koreUtil.getFormDefinition()` | Returns form metadata and component IDs — confirms how form components are structured in bot scripts and what the CBM parser should expect |
| `koreUtil.autoTranslate()` | How bots implement multilingual responses — relevant to multilingual evaluation |
| `koreUtil.getSessionId()` | How bots access session ID in scripts — relevant to debug log session correlation |
| `koreUtil.hash()` | SHA hashing in bot scripts — relevant to Tier 2 plagiarism fingerprinting |
| `koreUtil.closeConversationSession()` | Force session termination — verify interaction with GovernIQ's `SESSION_CLOSURE` events |

---

### Search AI

Full API list: https://docs.kore.ai/xo/apis/searchai/api-list/

| API | Workbench verification task |
|-----|----------------------------|
| **Answer Generation / Advance Search V2** | Endpoint URL and exact path, request format, response structure when result found vs not found, confidence score field name and value range |
| **Authentication** | Same JWT app credentials as Automation AI or separate scope required |
| **Content APIs** | How ingested content is queried — relevant to evaluating Search AI bot implementations |
| **Answer Insights** | Whether evaluation evidence can be extracted from answer analytics |

---

### Quality AI

Full API list: https://docs.kore.ai/xo/apis/quality-ai/api-list/

| API | Workbench verification task |
|-----|----------------------------|
| **Raw Data API** | Full response structure, quality metrics per interaction, auth model |
| **Auto QA Reporting API** | Interaction-level scoring format — whether this can supplement GovernIQ's own scoring as cross-check evidence |
| **Authentication** | Whether "Configuration" app scope is separate from Automation AI credentials |

---

### Case Management

Full API list: https://docs.kore.ai/xo/apis/case-management-apis/api-list/

| API | Workbench verification task |
|-----|----------------------------|
| **Create Case** — `POST /cases` | Full request/response structure, required fields, auth model |
| **Get Cases** — `GET /cases` | Filter params, pagination, response structure |
| **Create Task / Get Tasks** — `POST/GET /tasks` | Full request/response structure |
| **Authentication** | Whether "Case Management Configuration" scope is separate from Automation AI app credentials — determines what Gate 0 must request |

---

### Web SDK (WebSocket / RTM)

Reference: https://docs.kore.ai/xo/sdk/web-socket-connect-and-rtm/

**Critical finding:** The Web SDK uses WebSocket (RTM), not HTTP REST. Authentication requires three steps before any conversation begins:
1. Generate JWT server-side
2. Exchange JWT for access token: `POST /api/1.1/oAuth/token/jwtgrant`
3. Obtain WebSocket URL: `POST /api/1.1/rtm/start` — **URL expires in 30 seconds**
4. Connect via `wss://`

The widget handles this internally when embedded in the GovernIQ host page. Playwright drives the rendered DOM. The workbench verifies:

| What | Verification task |
|------|------------------|
| Full auth flow | 3-step flow works end-to-end with candidate credentials via GovernIQ server-side JWT endpoint |
| 30-second WebSocket URL expiry | Host page establishes connection within the window — confirm timing is reliable in practice |
| DOM — buttons | Trigger a button response, inspect DOM: container class, button class, payload data attribute |
| DOM — inline forms | Trigger a form node, inspect: field label selector, input selector, component ID attribute, submit button |
| DOM — carousels | Trigger a carousel template, record full DOM structure of rendered cards |
| DOM — external URL | Trigger `openInTab` response, record navigation event and how the URL is surfaced |
| Event types | Confirm `bot_response`, `/form_delivered`, `/session_start`, `/waiting_for_user_input` field names in practice |
| Session continuity | Send 3 turns with same `userIdentity`, verify bot retains context across turns |
| CDN version pinning | Confirm versioned CDN URL format exists and SDK loads correctly when pinned |

---

### Test bot requirements

Several workbench verification tasks — particularly Web SDK DOM inspection and T6 development — require a purpose-built test bot on the Kore.ai XO Platform. This bot must be built before those verification tasks can run.

**The test bot must implement:**

| UI Element | Implementation requirement |
|-----------|---------------------------|
| **Carousel** | A message node or script node that produces carousel-style output with selectable cards. Cards must be dynamically populated from a variable so different values can be tested. |
| **Inline form** | A form node with at least 3 labeled fields of different input types (text, dropdown/select, date). Field labels must be clearly named so label-to-entity mapping can be tested. |
| **Buttons / quick replies** | A message node that presents 2–4 button options. At least one button must trigger a subsequent dialog action. |
| **External URL form** | A message node that sends a URL with `openInTab: true` pointing to a standalone form page. The form must post data to the test backend API on submission. |
| **Backend API connection** | All UI interactions must be wired to service nodes calling a test backend API (MockAPI or equivalent). The API must store submitted data so API snapshot verification works. |
| **Multilingual response** | At least one dialog path must respond in a non-English language to verify the Actor and Judge handle multilingual output correctly. |

**This test bot is a development asset, not a candidate submission.** It stays in the GovernIQ test environment and is reused across all workbench verification runs and T6 Web Driver development.

---

### Workbench output format

For each verified API, the workbench produces one entry:

```
API: Debug Logs
Verified endpoint: GET https://bots.kore.ai/api/1.1/{botId}/fetch-debug-logs (unconfirmed path — verify via DevTools)
Working curl:
  curl -X GET \
    'https://bots.kore.ai/api/1.1/st-xxx/fetch-debug-logs?identity=eval-001&channelType=???&limit=50' \
    -H 'auth: {JWT}'

JWT payload (verified): { "appId": "cs-xxx", "sub": "12345", "iat": ..., "exp": ... }
JWT signing: HS256 with clientSecret

Confirmed fields in response: [every field name actually returned]
Confirmed constraints: [700-statement limit — applies to API: YES / NO]
channelType value for webhook: [confirmed string]
Works for webhook channel: YES / NO

Notes: [anything differing from documentation]
```

Every API the evaluation engine depends on gets one entry before any code is written. If any field says "not confirmed" or a test returns an unexpected result, that stops the corresponding build component until resolved.

---

## 29. Build Inventory

### Already implemented

| Component | File | Status |
|-----------|------|--------|
| Bot export parser | `cbm/parser.py` | ✓ Exists |
| CBM evaluator | `cbm/evaluator.py` | ✓ Exists |
| Webhook client | `webhook/driver.py` (`KoreWebhookClient`) | ✓ Exists |
| LLM conversation driver | `webhook/driver.py` (`LLMConversationDriver`) | ✓ Exists (classify-inject model — replace with Actor) |
| Debug log fetcher | `webhook/kore_api.py` (`get_debug_logs`) | ✓ Exists |
| Conversation history fetcher | `webhook/kore_api.py` | ✓ Exists |
| API snapshot manager | `webhook/state_inspector.py` | ✓ Exists |
| Actor prompt builder | `webhook/driver.py` (`actorBuild`) | ✓ Exists but unused |
| Score calculator | `core/scoring.py` | ✓ Exists |
| Plagiarism detection | `plagiarism/` | ✓ Exists (SHA-256, needs Tier 2 upgrade) |

### Components to build

| # | Component | Replaces / Extends |
|---|-----------|-------------------|
| 1 | **Actor Conversation Engine** | Replace classify-inject loop with LLM-as-persona using `actorBuild()`. Add evaluation context, value pools, stall detection, button/form handling. |
| 2 | **Polling Handler** | New. V2 `pollId` polling for service node responses. |
| 3 | **Session Manager** | Extend `KoreWebhookClient`. `ON_CONNECT`, `SESSION_CLOSURE`, unique `from.id` per task. |
| 4 | **Digital Form & Template Handler** | New. Parse form/button template responses. Respond with `formData` or button payload. |
| 5 | **Rate Limit Handler** | Extend `retry.py`. Exponential backoff for 429. Configurable `interMessageDelayMs`. |
| 6 | **Cross-Task Data Bridge** | New. After each task: run captureFromConversation patterns. Store in evaluation context. Inject into dependent task Actor. |
| 7 | **Debug Log Analyzer** | New. Parse raw debug JSON. Extract intent events, entity extraction events, service node calls. Generate structured analysis. |
| 8 | **Unified Evidence Grader (Judge)** | New. Per-check Judge prompt. Focused evidence assembly. Parallel execution within task. |
| 9 | **Method-Aware API Verifier** | Extend `state_inspector.py`. Handle GET/POST/PUT/DELETE differently. Before/after snapshot diffs. |
| 10 | **Feedback Generator (Feedback Writer)** | New. Template + LLM. 4-layer output: per-check, per-task, config, overall. |
| 11 | **Manifest Readiness Validator** | New. Design-time gap detection. Completeness checks. CBM auto-enrichment of semanticHints. |
| 12 | **CBM-to-Manifest Enrichment** | New. Auto-suggest semanticHints from entity node prompts in bot export. |
| 13 | **Evaluation State Machine** | New. Async lifecycle with debug log retry schedule. Queue management. |
| 14 | **Bot Publish Status Check** | New. Call Bot Details API in Gate 0. Block evaluation if unpublished. |
| 15 | **Submission Queue Manager** | New. Priority queue. Concurrency limits. File-based for POC, Redis for production. |
| 16 | **Plagiarism Tier 2** | Extend `plagiarism/detector.py`. Node label fingerprinting, script hashing, service mapping comparison. |

---

# Part 12 — Design Decisions

## 30. Resolved Open Questions

All design questions have been decided. These are final unless explicitly revisited.

| # | Question | Decision |
|---|----------|----------|
| **Q1** | How does the evaluator create a manifest? | **Form-based UI + templates.** Evaluator selects a manifest template (medical, travel, e-commerce) and customises via structured forms that generate JSON. JSON editor available for advanced use. AI-assisted builder is a future enhancement. |
| **Q2** | How are assignments distributed to candidates? | **Link-based.** Evaluator generates a unique submission link per assignment. Currently shared via email. Candidate clicks link, sees assignment, submits. No login required. `distribution.method: "link"` in assignment.json. |
| **Q3** | Multi-evaluator collaboration? | **POC:** single evaluator per assignment. **Production:** assignment has one primary evaluator + optional reviewers. Primary makes final calls. |
| **Q4** | Manifest versioning during live evaluations? | Once a manifest moves to SHADOW or PRODUCTION, it is **locked**. Edits require creating a new version. In-progress evaluations always use the version active at submission time (recorded in `attempt.manifestVersion`). |
| **Q5** | Error recovery if system crashes mid-evaluation? | **POC:** On restart, scan `active.json`. Any submission still marked active with no running process → move to `pending.json` with `retryReason: "system_restart"`. Evaluation restarts from the beginning. **Production:** BullMQ job persistence — only the failed Gate needs to re-run. |
| **Q6** | What if the bot has more tasks than the manifest? | Only evaluate tasks defined in the manifest. Extra tasks are noted as "Strengths observed beyond requirements" (informational only). Evaluator can award bonus points in manual review. |
| **Q7** | Manifest templates for common use cases? | **Yes.** Provide starter templates: medical appointment bot, travel booking bot, e-commerce support bot, banking assistant bot. Each includes pre-defined tasks, entity lists, scoring rules, persona pools, FAQ lists. |
| **Q8** | Bot responds in a different language than English? | **Multilingual support is a system-wide current requirement.** Candidates build multilingual bots — the bot may respond in any language. All evaluation components handle this: the Actor LLM interprets responses in any language; the Judge evaluates `lookFor` criteria against multilingual transcripts; FAQ evaluation uses a multilingual sentence-transformers model (`paraphrase-multilingual-mpnet-base-v2` or equivalent) comparing bot responses against English `expectedAnswer` fields across language boundaries. API verification is language-independent. `captureFromConversation` regex patterns must be designed as language-agnostic (numeric IDs, codes) — evaluators must not write language-specific text patterns. Manifest fields (`lookFor`, `semanticHints`, `expectedAnswer`) are written in English; the LLM and multilingual model bridge the language gap at runtime. |
| **Q9** | MockAPI schema changes between attempts? | Each attempt independently discovers the API schema. Manifest `expectedFieldMappings` defines the expected field names — if the candidate changes them, API checks will fail (correct behaviour, as the assignment specifies expected fields). |
| **Q10** | Scoring fairness across evaluators? | Scoring templates standardize weights for each assignment type. Admin can enforce: "All Medi-Assistant manifests must use scoring template MEDI-SCORING-V1." **Production:** assignment-level scoring rules shared across all evaluators. |
| **Q11** | Resubmit page when there is no previous feedback (system error)? | Show: *"Your previous submission encountered a processing issue. You may resubmit with fresh credentials."* No score comparison shown. No "issues from previous attempt" section. |
| **Q12** | Performance expectations per gate? | Gate 0: < 15s. Gate 1: < 30s. Gate 2: 3–10 min. Debug log collection: 0–10 hours. Gate 4: < 2 min. Target: results within 24 hours including evaluator review. |
| **Q13** | V1 vs V2 webhook — which is required? | **V2 required. V1 fails Gate 0.** V2 is mandatory because it provides `endOfTask` signals (required for task boundary detection) and structured template responses (required for button/form/carousel handling). Candidates must enable V2 in XO Platform: Channels → Webhook → Version 2.0. Gate 0 rejects any submission with a V1 webhook URL and returns an actionable error with setup instructions. |
| **Q14** | What happens when T1 fails to capture a required ID for T2–T4? | **Synthetic dependency injection.** GovernIQ calls the candidate's backend API directly to create a record, injects the returned ID into RuntimeContext, and continues T2–T4. The scorecard flags affected tasks as "evaluated with synthetic dependency." Each task is scored independently — a T1 failure does not collapse T2–T4 scores. See Challenge 11. |
| **Q15** | Is webhook the right channel for live testing, or is there a better approach? | **Webhook V2 is correct — chosen for signal quality, not session management.** Talk to Bot has no API surface (cannot be driven programmatically). Web Widget is driveable via Playwright but returns rendered HTML — structured signals (endOfTask, pollId, typed response arrays) are lost. Webhook V2 provides machine-readable conversation state no other channel matches: `endOfTask` + `completedTaskName` for task boundaries, `pollId` for async service nodes, typed `data[]` for response content. CBM validates structure; webhook validates behaviour — the dual pipeline is justified. See Section 6.1. |
| **Q16** | Should tasks be tested in one continuous session or isolated sessions? | **Isolated sessions — one session per task, by design.** Each task uses a unique `from.id` and a `SESSION_CLOSURE` event between tasks. A continuous session would allow session-level context from T1 (entity memory, NLP history) to bleed into T2, making T2 results dependent on T1 execution quality. Isolated sessions make each task independently reproducible and independently scoreable. The tradeoff — not replicating exact human evaluator session continuity — is accepted in exchange for grading isolation and test reliability. |
| **Q17** | How should rich UI elements (forms, carousels, buttons) be evaluated? | **Any task with `uiPolicy: "web_driver"` runs on the Web Driver, sequentially after all webhook tasks complete.** Webhook JSON payloads describe UI structure but cannot verify rendered behaviour. The Web Driver (Kore.ai Web SDK + Playwright) renders the actual widget and interacts as a real user — clicking buttons, filling forms by DOM label, matching carousels by title. T1-T5 and FAQ remain on the Webhook Driver. The two drivers run sequentially — webhook tasks first, web driver tasks after. Both write to the same evidence store. Web channel must be enabled — checked at Gate 0 (WARN not FAIL). DOM fragility is the primary risk: requires a DOM structure verification test in pre-build validation before any selectors are written. See Sections 31 and 35. |

---

---

# Part 13 — Rich UI Interaction Design

## 31. The Two-Driver Architecture

### The evaluation objective

The objective is to test whether learners can build real-world bot features — forms, buttons, carousels. This requires at least one task dedicated to rich UI, and a way to automate testing it accurately.

### Why webhook alone is insufficient for UI testing

The webhook channel receives the JSON *definition* of a form or carousel — not the rendered element. You can respond to it programmatically by parsing payloads, but you are testing the JSON payload, not the UI. You cannot verify that a carousel renders correctly, that buttons are clickable in the actual widget, or that a form presents fields in a coherent order to a real user.

### The solution: two drivers, sequential execution

GovernIQ runs two independent test drivers during Gate 2, executed sequentially:

| Driver | Channel | Tasks | What it tests |
|--------|---------|-------|---------------|
| **Webhook Driver** | Kore.ai V2 Webhook | All tasks with `uiPolicy: "prefer_webhook"`, FAQ | Data collection, API calls, NLP, dialog flow — via structured JSON |
| **Web Driver** | Kore.ai Web SDK + Playwright | All tasks with `uiPolicy: "web_driver"` | Rendered UI elements — buttons, inline forms, carousels, external forms — as a real user sees them |

The driver a task runs on is determined entirely by its `uiPolicy` field in the manifest. The evaluator assigns this per task. There is no fixed task ID or position — an assignment may have any number of tasks on either driver, in any order the evaluator defines.

**Execution order:** Webhook Driver tasks run first (in dependency order). Web Driver tasks run after all webhook tasks complete. Sequential by design for two reasons: (1) web driver tasks may depend on prior webhook tasks — for example, a CSAT/feedback task with rating buttons or satisfaction scales only makes sense after the main interaction is complete; (2) file-based storage in the POC cannot safely handle concurrent writes from two processes. Both drivers write to the same evidence store. Gate 3 and Gate 4 consume evidence regardless of which driver produced it.

### Web driver tasks — evaluator-defined, not fixed

The evaluator decides which tasks require web driver evaluation and names them freely. A rich UI task could be a CSAT feedback task (rating buttons, satisfaction scale), a product selection task (carousel), a complex data entry task (multi-field form), or any combination. It appears wherever the evaluator places it in the task sequence — first, last, or middle.

**What the evaluator defines in the manifest for any web driver task:**
- Which UI element types to expect (form, carousel, buttons)
- `labelHints` mapping form field labels to manifest entity IDs
- Carousel match strategy (exact / contains / semantic)
- Expected bot response after submission

**What the candidate provides:** Nothing additional. The web driver uses the same `clientId` and `clientSecret` already submitted at Gate 0. The only new requirement is that the Web SDK channel is enabled — checked at Gate 0 (Step 2c, WARN not FAIL).

### How the web driver session works

GovernIQ serves a minimal host page with a session token injected at runtime. Playwright navigates to it. A JWT endpoint on GovernIQ's server generates the session token from credentials held in server memory — the token, not the credentials, reaches the host page. Session identity follows the same isolation pattern: `eval-{submissionId}-{taskId}`.

**Credential handling — evaluation integrity requirement**

The clientSecret must never appear in the host page HTML or any browser-accessible resource. A candidate could open DevTools during their own evaluation session and extract it — then replay API calls or interfere with their evaluation run.

The correct flow: GovernIQ's server generates the JWT using credentials held in server memory. The host page receives only the resulting short-lived token. The token expires when the web driver task session ends. Credentials never leave the server.

**Host page URL security**

The host page URL is session-scoped and short-lived. The session token is generated immediately before the web driver task launches — not at overall evaluation start. This matters because webhook tasks may take 10–15 minutes before the web driver runs; a token generated at evaluation start could expire before the task begins. The 15-minute TTL runs from web driver task dispatch time.

Without session-scoped URLs, the host page is a persistent entry point. A candidate who discovers the URL could initiate a conversation with their own bot through GovernIQ's JWT generator — probing their bot's behaviour or learning persona values before the real evaluation runs.

**Token validity definition:** The session token is valid for one WebSocket session establishment. Once the Kore.ai Web SDK has successfully connected and the session is open, the token is consumed. Playwright makes multiple requests during a session (page load, SDK assets, JWT endpoint calls) — these continue through the established WebSocket, not through the host page URL. A second attempt to establish a new WebSocket session with the same token returns 404. Credentials are purged from memory after the web driver task completes, whether the task succeeded or not.

```
GovernIQ Web Driver
  │
  ├─ Generate session token (server-side, at web driver task dispatch)
  │    JWT signed with clientSecret — held in server memory, never exposed
  │    Short-lived token: 15-min TTL, consumed on first WebSocket connection
  │
  ├─ Serve host page (GovernIQ internal URL, not internet-facing)
  │    <script src="kore-web-sdk.js">
  │    botOptions.authToken = "{sessionToken}"   ← short-lived token only
  │    botOptions.userIdentity = "eval-{submissionId}-{taskId}"
  │
  ├─ Playwright navigates to host page
  ├─ Web SDK initialises, opens session with candidate's bot
  │
  └─ Playwright drives interaction:
       Type trigger message
       Wait for bot response (DOM polling)
       Detect UI element type (buttons / form / carousel)
       Interact (click / fill / select)
       Screenshot before and after
       Submit
       Capture bot's next response
```

The correct framing: different response types need different handlers — and the right handler for rendered UI is a real browser, not a smarter LLM prompt.

---

## 32. Response Type Detector

Every webhook `data[]` response passes through a type detector before the Actor is invoked. The detector classifies the response and routes it to the correct handler.

```
Webhook response received
          │
          ▼
    Response Type Detector
          │
    ┌─────┴──────────────────────────────────────────────────┐
    │                         │                              │
 text/conversational    structured UI element          external URL
    │                         │                              │
    ▼                         ▼                              ▼
Actor responds         Semantic Field Mapper         Playwright External
via LLM prompt         maps to entity, responds      Form Handler
(existing path)        via webhook JSON                    │
                       (no browser needed)           API snapshot confirms
                                                     uiInteraction evidence
```

### Webhook response classification rules

| Condition | Classified as | Handler |
|-----------|--------------|---------|
| `data[].type == "text"` | Text | Actor (LLM) |
| `data[].type == "template"` with `templateType: "quick_replies"` or `"buttons"` | Buttons | Semantic Field Mapper |
| `data[].type == "template"` with `templateType: "form"` and `componentIds` present | Inline Form | Semantic Field Mapper |
| `data[].type == "template"` with `templateType: "carousel"` | Carousel | Semantic Field Mapper |
| `data[].type == "template"` with `openInTab: true` or bare URL | External Form | Playwright External Form Handler |
| Response contains URL string with no associated `componentIds` or `payload` | Ambiguous URL | Playwright (screenshot + flag) |

---

## 33. Semantic Field Mapper (Buttons, Inline Forms, Carousels)

For buttons, inline forms, and carousels, the webhook response already contains the full machine-readable definition — button payloads, form component IDs, field labels, option lists. **No browser is needed.** The problem is mapping: form labels often don't match manifest entity names.

### How mapping works

**Step 1: Build a label index from the response**
Extract all human-readable labels from the response:
- Buttons: `button.title` and `button.payload`
- Form fields: `component.label`, `component.placeholder`, `component.type`, `component.options[].text`
- Carousel cards: `card.title`, `card.subtitle`, `card.buttons[].title`

**Step 2: Match labels to manifest entities**
For each response element, find the manifest entity it corresponds to. Match in priority order:
1. **Exact match** — `component.label == entity.uiMappingHints.formFieldLabels[n]`
2. **Case-insensitive contains** — label contains a hint word
3. **Semantic LLM match** — ask LLM: *"Given form field label '{label}', which entity does it correspond to? Options: {entityId list with their semanticHints}"*

**Step 3: Resolve the value**
- **Text input** → use `persona[entityId]` directly
- **Dropdown/select** → match `persona[entityId]` against `options[].text` using `buttonMatchStrategy` (exact / contains / semantic)
- **Button list** → match `persona[entityId]` against `button.title` using match strategy, respond with `button.payload`
- **Carousel** → match `persona[entityId]` against `card[uiMappingHints.carouselMatchField]`, respond with matched card's `button.payload`
- **Date/time input** → apply format from entity definition

**Step 4: Respond via webhook JSON**
```jsonc
// Inline form response
{
  "message": {
    "type": "formData",
    "val": {
      "formId": "form-xxx",
      "data": [
        { "componentId": "cmp-spec-001", "input": "Orthopedic" },
        { "componentId": "cmp-date-002", "input": "02-04-2026" },
        { "componentId": "cmp-name-003", "input": "Rajesh Kumar" }
      ]
    }
  }
}

// Button/carousel response — send the payload value, not the label
{
  "message": { "type": "text", "val": "cardiologist_payload_value" }
}
```

**Step 5: Log the mapping for evidence**
Every mapping decision goes into the entity tracking log:
```jsonc
{
  "turn": 7,
  "responseType": "inline_form",
  "formId": "form-xxx",
  "mappings": [
    {
      "componentId": "cmp-spec-001",
      "componentLabel": "Specialty Required",
      "matchedEntity": "doctorType",
      "matchStrategy": "semantic",
      "matchConfidence": 0.91,
      "valueProvided": "Orthopedic"
    }
  ],
  "unmappedComponents": []
}
```

### Unmapped form fields

If a form component cannot be matched to any manifest entity:
- Behaviour controlled by `executionConfig.formUnmappedFieldBehavior`:
  - `"leave_empty"` — submit component with empty string (default)
  - `"fill_placeholder"` — submit with "N/A" or similar generic value
- Log the unmapped component — feeds into Manifest Readiness Validator (Challenge 15)
- Flag for evaluator: "Form component '{label}' was not mapped to any manifest entity"

### Multi-entity forms

When a single form collects multiple entities at once (e.g. name + date + doctor type in one submit), all entities are resolved and submitted in a single `formData` response. The entity tracking log records all mappings with a `batchSubmit: true` flag.

---

## 34. `uiMappingHints` — Manifest Entity Extension

Add `uiMappingHints` to any entity that may be collected via a form, button list, or carousel. This is optional — entities without hints fall back to LLM semantic matching.

```jsonc
// Inside manifest.tasks[n].entityCollection[n]
{
  "entityId": "doctorType",
  "description": "Type of doctor required",
  "valuePool": "doctorType",
  "semanticHints": [
    "What type of doctor?",
    "Which specialty?",
    "Type of doctor needed"
  ],

  // NEW: how to find this entity in a form, button list, or carousel
  "uiMappingHints": {
    // Form field labels (exact or partial) that correspond to this entity
    "formFieldLabels": ["Doctor Type", "Specialist", "Specialty", "Specialty Required", "Type of Doctor"],

    // How to match persona value against button titles or dropdown options
    // "exact" | "contains" | "semantic"
    "buttonMatchStrategy": "semantic",

    // For carousels: which card field to compare against persona value
    // "title" | "subtitle" | "description"
    "carouselMatchField": "title",
    "carouselMatchStrategy": "semantic"
  }
}
```

Add `uiPolicy` at the task level to declare the expected interaction mode:

```jsonc
// Inside manifest.tasks[n]
{
  "taskId": "T1-BOOK",

  // "prefer_webhook"   — all interaction via webhook JSON (default, T1-T5)
  // "web_driver"       — task runs on full Playwright web driver (evaluator-defined task ID)
  // "untestable_flag"  — evaluator marks this task as requiring manual evaluation
  "uiPolicy": "prefer_webhook"
}
```

Add `formUnmappedFieldBehavior` to `executionConfig`:

```jsonc
{
  "executionConfig": {
    "formUnmappedFieldBehavior": "leave_empty"  // "leave_empty" | "fill_placeholder"
  }
}
```

---

## 35. Web Driver (web_driver tasks)

### Scope

The Web Driver handles any task with `uiPolicy: "web_driver"` in the manifest. It uses the Kore.ai Web SDK rendered inside a Playwright-controlled browser. It runs after all Webhook Driver tasks complete — sequentially, not concurrently. It does not share session state with the Webhook Driver. Both drivers write to the same evidence store. Each web driver task runs in its own isolated session using the same `eval-{submissionId}-{taskId}` pattern.

### How each UI element is handled

**Buttons and quick replies**

Playwright reads rendered button labels from the DOM, semantically matches the correct button against the current task goal, screenshots before and after, and clicks.

```
DOM: ["Cardiologist", "Dermatologist", "Orthopedic"]
Persona: doctorType = "Cardiologist"
Match: exact → click "Cardiologist"
```

**Inline forms**

Playwright reads field labels from the DOM, maps them to manifest entity IDs using `labelHints`, fills each field with the persona value, screenshots the filled form, and submits.

```
DOM field: label="Specialty Required", type=select
labelHints: doctorType → ["Doctor Type", "Specialty", "Specialty Required"]
Match: exact → fill with persona.doctorType = "Orthopedic"
```

**Carousels**

Playwright reads card titles from the DOM and matches against the persona value using a configurable strategy (`exact` / `contains` / `semantic`). Clicks the matching card.

```
Persona: doctorType = "Cardiologist"
Cards: ["Dr. Mehta – Cardiology", "Dr. Patel – Dermatology", "Dr. Singh – Orthopedics"]
Strategy: semantic → LLM confirms "Dr. Mehta – Cardiology" matches "Cardiologist"
Playwright clicks: "Dr. Mehta – Cardiology"
```

**External forms (new tab / external URL)**

Playwright intercepts the navigation, fills and submits the form in a controlled context. The API snapshot confirms the outcome.

### Web Driver interface

```python
class KoreWebDriver:
    """
    Full Playwright driver for any task with uiPolicy: "web_driver".
    Runs against the Kore.ai Web SDK rendered in a GovernIQ-hosted page.
    Independent session from the Webhook Driver.
    """

    def run_task(
        self,
        task_id: str,                  # evaluator-defined task ID
        trigger_message: str,          # from manifest
        entity_values: dict,           # { entityId: personaValue, ... }
        label_hints: dict,             # from manifest entity definitions
        expected_elements: list,       # ["form", "carousel", "buttons"]
        carousel_match_strategy: str   # "exact" | "contains" | "semantic"
    ) -> WebDriverTaskResult:
        """
        1. Navigate to GovernIQ host page (session token injected by JWT endpoint)
        2. Wait for Web SDK to initialise
        3. Send trigger message
        4. Wait for bot response (DOM polling)
        5. Detect UI element type
        6. Interact: click / fill / select / intercept external tab
        7. Screenshot before and after each interaction
        8. Capture bot's next response
        9. Return structured result + screenshots
        """

    def screenshot(self, label: str) -> bytes:
        """Capture current state with an evidence label."""
```

### WebDriverTaskResult schema

```jsonc
{
  "taskId": "{taskId}",
  "sessionId": "eval-{submissionId}-{taskId}",
  "elementsExpected": ["form", "carousel", "buttons"],
  "elementsDetected": [
    {
      "type": "carousel",
      "cardsFound": 3,
      "cardTitles": ["Dr. Mehta – Cardiology", "Dr. Patel – Dermatology", "Dr. Singh – Orthopedics"],
      "matchedCard": "Dr. Mehta – Cardiology",
      "matchStrategy": "semantic",
      "matchConfidence": 0.94,
      "clicked": true
    },
    {
      "type": "inline_form",
      "fieldsFound": 4,
      "fieldsMapped": 3,
      "fieldsUnmapped": 1,
      "unmappedLabels": ["Clinic Branch"],
      "submitted": true
    },
    {
      "type": "buttons",
      "buttonLabels": ["Confirm", "Cancel"],
      "matchedButton": "Confirm",
      "clicked": true
    }
  ],
  "screenshotsBefore": ["evidence/ATT-01/T6/carousel-before.png", "evidence/ATT-01/T6/form-before.png"],
  "screenshotsAfter":  ["evidence/ATT-01/T6/carousel-after.png",  "evidence/ATT-01/T6/form-after.png"],
  "botFinalResponse": "[bot confirmation message]",
  "apiSnapshotPost": { "recordId": "[reference ID]", "field1": "[value]" }
}
```

### Crash recovery

If the Playwright browser crashes or becomes unresponsive during a web driver task:

1. Save whatever partial screenshots and interaction logs exist to the evidence store
2. Terminate the browser process explicitly — do not leave it running and consuming memory on the evaluation server
3. Free the evaluation queue slot

**Retry policy — depends on when the crash occurred:**

- **Crash before any interaction** (browser failed to load, JWT endpoint unreachable, DOM never rendered, no bot turns sent) → retry once. No state was changed. Session is clean.
- **Crash mid-interaction** (at least one turn sent, bot may be in a partially completed dialog, API may have partial records) → do not retry. The API state is unknown. A retry would start a fresh session while partial records from the first attempt already exist in the backend. Proceed directly to partial evidence + manual review flag.

4. Mark the task as `SYSTEM_ERROR` with reason `WEB_DRIVER_CRASH`
5. Continue to Gate 3 and Gate 4 with whatever evidence exists
6. Flag for manual review: *"Web driver task {taskId} could not be completed — browser error. UI interaction evidence is partial or unavailable."*
7. Transition candidate-visible status to: *"We encountered an issue evaluating your submission. It has been flagged for review. You'll hear back within 24 hours."* — same as the existing `FAILED_SYSTEM_ERROR` state. Do not leave candidate on "evaluation in progress" once the error is confirmed.

### Scoring — per element, not per task

Web driver tasks follow the same per-check scoring model as webhook tasks. Each behavior check (carousel rendered, form fields mapped, buttons presented, API record created) is scored independently. A candidate who correctly implements the carousel but not the form receives carousel points and zero form points — not zero for the entire task.

This is enforced by the manifest: each `behaviorCheck` has its own `scoring` definition. The Judge verdicts each check independently based on the `uiInteraction` evidence for that element. There is no task-level pass/fail that collapses individual check scores.

**Per-element evidence assembly:** The `uiInteraction` evidence stream is assembled per element before the Judge sees it. The Judge receives only the evidence relevant to the check it is verdicting — carousel check gets carousel screenshots and card match log, form check gets field mapping log and form screenshot, button check gets button labels detected and selection log. This is the same focused evidence assembly principle defined for webhook checks in Section 14. Passing all uiInteraction evidence as one blob to every check reduces Judge accuracy — a form field mapping failure buried in a carousel screenshot log creates noise.

---

### SDK version pinning

GovernIQ locks the Kore.ai Web SDK to a specific version. A Kore.ai SDK release cannot silently change the widget's DOM structure mid-evaluation — upgrading is a deliberate, tested action. This makes DOM fragility a bounded, controlled risk rather than a continuous background threat.

### DOM fragility — managed risk, not eliminated

Version pinning controls *when* DOM changes arrive, not whether they arrive. When GovernIQ upgrades the pinned version, the DOM verification test (Section 28) must pass before the upgrade goes live.

**Required pre-build step (Section 28):** Before writing a single selector, inspect the rendered widget DOM against a live bot on the pinned SDK version. Document every class name and data attribute. The verification test runs once per version upgrade, not continuously.

---

## 36. `uiInteraction` — Sixth Evidence Stream

### Evidence model

| Stream | Source | Authority |
|--------|--------|-----------|
| API Snapshot | Backend API before/after | **Highest** |
| Debug Log | Kore.ai internal events | High |
| **uiInteraction** | Web Driver screenshots + interaction log | **Medium** |
| Transcript | Webhook conversation | Medium |
| Entity Tracking | Actor injection log + Semantic Field Mapper log | Medium |
| CBM Context | Bot export | Low |

**Authority rationale for uiInteraction (Medium):** Visual proof of what the rendered UI contained and what the Web Driver did. Cannot intercept the underlying API call from the browser — that is confirmed by the API snapshot. uiInteraction is evidence of *what was attempted and rendered*; the API snapshot is evidence of *what actually happened*.

### Evidence structure per element type

The `uiInteraction` stream covers all four element types the Web Driver handles. The Judge receives structured evidence for each:

**Buttons / quick replies**
```
Interaction type: buttons
Buttons rendered: ["Option A", "Option B", "Option C"]
Button selected: "Option A"
Selection method: semantic match
Screenshot before: evidence/ATT-01/T6/buttons-before.png
Screenshot after:  evidence/ATT-01/T6/buttons-after.png
Bot response after click: [bot confirmation message]
```

**Carousel**
```
Interaction type: carousel
Cards rendered: ["Item 1 — Category X", "Item 2 — Category Y", "Item 3 — Category Z"]
Card selected: "Item 1 — Category X"
Match target: persona.entityId = "Category X"
Match strategy: semantic
Match confidence: 0.94
Screenshot before: evidence/ATT-01/T6/carousel-before.png
Screenshot after:  evidence/ATT-01/T6/carousel-after.png
Bot response after selection: [bot confirmation message]
```

**Inline form**
```
Interaction type: inline_form
Fields detected: 4
Fields mapped: 3 (field1 ✓, field2 ✓, field3 ✓)
Fields unmapped: 1 (extraField — not in manifest)
Form submitted: YES
Screenshot before: evidence/ATT-01/T6/form-before.png
Screenshot after:  evidence/ATT-01/T6/form-after.png
Bot response after submit: [bot confirmation message]
```

**External form (new tab)**
```
Interaction type: external_form
URL: [external form URL from bot response]
Fields detected: 4
Fields mapped: 3 (field1 ✓, field2 ✓, field3 ✓)
Fields unmapped: 1 (extraField — not in manifest)
Form submitted: YES
Screenshot before: evidence/ATT-01/T6/ext-form-before.png
Screenshot after:  evidence/ATT-01/T6/ext-form-after.png
API record created: YES (confirmed by API snapshot)
```

### Cross-referencing rules for T6

```
All streams agree:
  UI element rendered (uiInteraction ✓), interaction completed,
  API record created with correct values (API ✓).
  → HIGH confidence PASS

UI interaction succeeded, API record missing:
  Interaction completed (uiInteraction ✓)
  but no new API record (API ✗), no service node in debug (debug ✗).
  → Bot wiring issue — interaction not connected to service node.
  → FAIL.

Element not rendered:
  Bot responded with plain text where carousel/form/buttons expected.
  uiInteraction: element type NOT DETECTED.
  → Candidate did not implement required UI element.
  → FAIL.

uiInteraction available, debug unavailable:
  Interaction completed (uiInteraction ✓), API record created (API ✓).
  Debug unavailable — cannot confirm service node path.
  → MEDIUM confidence PASS.
```

### Judge prompt additions for uiInteraction

The Judge receives one block per element type detected during the web driver task:

```
EVIDENCE STREAM 6 — UI INTERACTION ({taskId}):

  [1] CAROUSEL
      Cards rendered: [card list]
      Selected: [matched card] (semantic match for persona value, confidence: N)
      Screenshot: evidence/ATT-01/T6/carousel-before.png → carousel-after.png

  [2] INLINE FORM
      Fields detected: N | Mapped: N | Unmapped: N ([unmapped field labels])
      Submitted: YES
      Screenshot: evidence/ATT-01/T6/form-before.png → form-after.png

  [3] BUTTONS
      Buttons rendered: [button labels]
      Selected: [matched button] ([match method])
      Bot response after: [bot message]
      Screenshot: evidence/ATT-01/T6/buttons-before.png → buttons-after.png

  Elements expected: [from manifest expectedElements]
  Elements detected: carousel ✓/✗, inline_form ✓/✗, buttons ✓/✗
```

---

## 37. Updated Build Inventory (UI Interaction Components)

Replace the original Component 4 entry with this expanded definition:

**Component 4a — Semantic Field Mapper** *(new, replaces "Digital Form & Template Handler")*
Parses structured webhook responses (inline forms, buttons, carousels). Maps form component labels and button titles to manifest entities using `uiMappingHints` + semantic fallback. Responds via webhook JSON (`formData`, button payload). No browser required.

**Component 4b — Web Driver (KoreWebDriver)** *(new)*
Full Playwright driver for all `web_driver` tasks. Runs the Kore.ai Web SDK inside a Playwright-controlled browser hosted by GovernIQ. Handles buttons (DOM click), inline forms (label mapping + fill), carousels (semantic card matching), and external forms (tab interception). Produces `uiInteraction` evidence stream with before/after screenshots. Runs after all Webhook Driver tasks complete (sequential). Independent session from the Webhook Driver. DOM fragility is the primary maintenance risk — requires a DOM verification test in pre-build validation. Built on Playwright (already in `.playwright-mcp/`).

**Component 4c — Response Type Detector** *(new)*
Classifies each webhook `data[]` response and routes to the correct handler within the Webhook Driver: Actor (text), Semantic Field Mapper (buttons/forms/carousels via JSON). Single decision point at the top of the Gate 2 webhook conversation loop. Does not apply to the Web Driver — the Web Driver reads the rendered DOM directly.

**Component 4d — GovernIQ Web SDK Host Page** *(new)*
A minimal server-rendered page that embeds the Kore.ai Web SDK with a session token injected at runtime. Served internally — not internet-facing. Includes a JWT endpoint that generates short-lived tokens from credentials held in server memory — credentials never reach the host page. The Web Driver navigates to this page to establish the web channel session.

### When to invoke Playwright: decision table

```
Bot sends:                        Task uiPolicy:      Handler:
──────────────────────────────────────────────────────────────────
"text" response                   any                 Actor (LLM)
buttons / quick replies           any                 Semantic Field Mapper
inline form (componentIds)        any                 Semantic Field Mapper
carousel                          any                 Semantic Field Mapper
URL with openInTab: true          prefer_webhook      Playwright (auto-detected)
URL with openInTab: true          web_driver          Playwright (declared via uiPolicy)
URL with openInTab: true          untestable_flag     Skip + flag for manual review
Bare URL (ambiguous)              any                 Playwright screenshot + flag
```

---

*Architecture addendum complete. The Playwright tool is scoped to one job: external URL forms, self-contained, no session assumptions. All other rich UI elements are handled by the Semantic Field Mapper via webhook JSON with semantic entity matching.*

| Version | Date | Changes |
|---------|------|---------|
| v1.0 | 2026-03-25 | Complete rewrite. Added full Assignment Use Case and Evaluation Manifest JSON schemas. Reorganized into 12 parts. All open questions resolved. |

