# GovernIQ — Management Overview

## What is GovernIQ?

GovernIQ is an automated evaluation platform that scores candidate-built Kore.ai bots for certification purposes. Instead of an evaluator manually testing each bot submission, GovernIQ runs a complete set of scripted test scenarios automatically, produces a detailed scorecard, and flags the submission for evaluator review.

The platform replaces hours of manual testing with a consistent, repeatable, auditable process.

---

## How it Works — The Complete Flow

### 1. Assessment Setup (One-Time Per Assessment Type)

An administrator creates a **manifest** — a configuration file that defines the complete assessment:
- What scenarios the bot must handle (booking, retrieval, modification, cancellation)
- What entities the bot must collect from users
- What API calls the bot must make to the mock backend
- How many FAQ questions the bot must answer
- What compliance rules the bot must meet (e.g. DialogGPT must be enabled)
- The scoring weights for each component

This is done once per assessment type (Medical, Travel, Banking, etc.) through a guided form builder in the admin portal. No coding required.

### 2. Candidate Receives the Assignment

The administrator creates a candidate record in the system and shares a portal link. The candidate accesses their personalised portal, views the assignment brief, and downloads it as a PDF if needed.

The assignment brief describes what to build — the scenario, which entities to collect, which APIs to call, which FAQs to implement. It does not show how the bot will be scored.

### 3. Candidate Submits Their Bot

When ready, the candidate:
1. Exports their bot from the Kore.ai XO platform as a ZIP file
2. Uploads it to their portal along with their mock API webhook URL
3. Submits

### 4. Automated Evaluation (Runs Immediately)

GovernIQ evaluates the submission automatically:

**Pipeline 1 — CBM Structural Audit**
Reads the bot's internal structure — dialogs, nodes, AI Assist configuration, FAQ knowledge base — and produces a blueprint. This is informational and never affects the score.

**Pipeline 2 — Webhook Functional Test**
An LLM-powered conversation driver talks directly to the candidate's bot, simulating real user conversations. For each test scenario:
- The driver provides user inputs and injects realistic entity values
- After the conversation, the platform calls the candidate's mock API to verify the correct data was stored or retrieved
- Edge cases and invalid inputs are also tested to check error handling

**Plagiarism Detection**
Runs automatically on every submission. Compares the bot's structural fingerprint against all prior submissions for the same assessment. Flags potential copies at LOW, MEDIUM, or HIGH risk.

**Score Calculation**
```
Final Score = (Webhook functional score × 80%)
            + (FAQ handling score × 10%)
            + (Compliance check score × 10%)
```

### 5. Evaluator Reviews and Confirms

The evaluator sees the submission in the admin dashboard. They review:
- The overall score and per-scenario breakdown
- API evidence (what was actually stored in the mock backend)
- The conversation transcript for each scenario
- The CBM blueprint (structural audit)
- Plagiarism risk and any flagged matches

The evaluator confirms **Pass** or **Fail** with an optional note. The candidate sees the result immediately.

### 6. Candidate Can Resubmit

Candidates have up to 6 attempts by default. If they fail, they can view their feedback and resubmit an improved bot. Each resubmission is scored the same way. The attempt history shows their score progression and what changed between attempts.

---

## Scoring

| Component | Weight | What It Measures |
|-----------|--------|-----------------|
| Webhook functional | 80% | Did the bot correctly complete each scenario? Correct entities collected, correct API calls made, correct data in the backend. |
| FAQ handling | 10% | Did the bot answer the required FAQ questions accurately, with the required keywords, handling alternate phrasings? |
| Compliance | 10% | Does the bot meet the structural requirements? (e.g. DialogGPT enabled, required node types present) |

The CBM structural audit (reading the bot's internal structure) is **informational only** and does not affect the score. It gives the evaluator a blueprint of what the candidate built.

---

## Assessment Types

GovernIQ is domain-agnostic. Each assessment type is a separate configuration (manifest) with no shared code. Adding a new assessment type — HR leave management, banking services, legal intake — requires writing a new manifest configuration only. No engineering work.

Current assessment types:
- **Medical Appointment Bot** — book, retrieve, modify, and cancel appointments
- **Travel Assistant Bot (Basic)** — flight/hotel booking and management
- **Travel Assistant Bot (Advanced)** — more complex travel scenarios with compliance requirements
- **Banking / Account Services Bot** — account enquiries, transactions, modifications

---

## Attempt Limits and Exceptions

- Default: 6 attempts per candidate per assessment
- If a candidate has a valid reason for more attempts, an evaluator can grant an exception — the limit is lifted and the candidate can resubmit
- Exceptions are flagged in the admin view so all evaluators are aware

---

## Plagiarism Handling

GovernIQ automatically detects when two candidates submit identical or very similar bots:

| Risk Level | Meaning | Admin Action Required |
|------------|---------|----------------------|
| NONE | Bot not seen before | None |
| LOW | Service API URLs match a previous submission | Review recommended |
| MEDIUM | Bot structure matches a previous submission | Review required before confirming |
| HIGH | Both structure and APIs match | Auto-confirmation blocked; must review |

When a HIGH risk submission is detected, the evaluator can:
- **Mark as Original** — clear the flag and proceed normally
- **Request Fresh Work** — send an automated message to the candidate and hold the submission (does not count as a failed attempt)

---

## Communications

Evaluators and candidates can exchange messages within the platform. The full communication thread is always visible to the candidate after their first submission, regardless of their submission status. This ensures transparency and gives candidates the feedback they need to improve.

---

## Data and Privacy

- All data is stored locally on the GovernIQ server — no cloud services required
- Candidate data: email address, bot exports, conversation transcripts, scorecard
- No candidate authentication system — candidates access their portal by email address
- All submissions are retained for audit purposes; archiving a manifest does not delete historical data
- The system is designed to migrate to PostgreSQL when required — the current local JSON storage is PostgreSQL-migration-ready by design

---

## What the Evaluator Does (Summary)

Evaluators do not run tests — GovernIQ does that automatically. Evaluators:
1. Review flagged submissions (score available immediately after submission)
2. Confirm pass or fail with an optional note
3. Handle plagiarism flags
4. Grant attempt exceptions when appropriate
5. Communicate with candidates through the built-in messaging system
6. Create new assessment manifests when new assessment types are needed

---

## Roadmap

| Phase | Status | Description |
|-------|--------|-------------|
| Phase 1 | Complete | Bot export parser — accurate reading of all Kore.ai XO export formats |
| Phase 2 | Complete | CBM Blueprint module, Plagiarism detection module |
| Phase 3 | Complete | Manifest schema redesign, Manifest Builder UI |
| Phase 3b | In Progress | Manifest co-authoring session — creating the 4 assessment manifests |
| Phase 4 | Planned | Complete application build — submission portal, admin dashboard, communications |
| Phase 5 | Planned | Live testing against real candidate submissions |
| Phase 6 | Future | LMS integration, automated email notifications, PostgreSQL migration, reporting exports |
