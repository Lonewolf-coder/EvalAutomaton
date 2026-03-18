# GovernIQ — Admin / Evaluator Guide

## Overview

This guide is for **evaluators** — the people who review bot submissions, confirm scores, communicate with candidates, and manage assessment manifests.

As an evaluator you use the **Admin Portal** (`/admin`). Candidates use a separate portal (`/candidate`). You never need to touch code.

---

## Accessing the Admin Portal

Navigate to `http://<server-address>/admin` in your browser.

The admin portal has three main sections:
- **Manifests** — create, edit, archive, and restore assessment configurations
- **Submissions** — review all candidate submissions, confirm or reject, manage communications
- **Candidates** — create submission records for new candidates

---

## Managing Manifests

Manifests are the complete specification for an assessment. They define what the bot must do, how it is scored, and what the candidate sees.

### Creating a New Manifest

1. Go to **Admin → Manifests → New Manifest**
2. Use the **Form Builder** tab to fill in all sections (see `docs/manifest_builder_guide.md` for a full walkthrough)
3. Click **Validate** to check for errors (the validation panel shows MD-01–MD-12 results)
4. Click **Save** — the manifest becomes immediately available for candidate submissions

### Editing a Manifest

1. Go to **Admin → Manifests**
2. Find the manifest and click **Edit**
3. Make your changes and re-validate before saving
4. Save — changes take effect for new submissions (existing submissions are not affected)

### Archiving a Manifest

Archiving removes a manifest from the active list and moves it to `manifests/archived/`. Archived manifests cannot be assigned to new candidates but their historical data is preserved.

1. Go to **Admin → Manifests**
2. Click **Archive** next to the manifest
3. Confirm the action

### Restoring an Archived Manifest

1. Go to **Admin → Manifests → Archived**
2. Click **Restore** next to the manifest

---

## Reviewing Submissions

### The Submission List

**Admin → Submissions** shows all candidate submissions across all assessment types.

Each row shows:
- **Candidate email** — the sole identifier
- **Assessment type** — which manifest was used
- **Status badge** — one of: `pending_review`, `confirmed_pass`, `confirmed_fail`, `exhausted`, `on_hold`
- **Attempt count** — e.g. "2 / 6"
- **Latest score** — percentage
- **Plagiarism risk** — `NONE`, `LOW`, `MEDIUM`, or `HIGH`

### Status Meanings

| Status | Meaning |
|--------|---------|
| `pending_review` | Evaluation complete, awaiting evaluator confirmation |
| `confirmed_pass` | Evaluator confirmed the candidate passed |
| `confirmed_fail` | Evaluator confirmed the candidate failed |
| `exhausted` | Candidate used all allowed attempts without passing |
| `on_hold` | Held for plagiarism investigation |

### Per-Submission Review Page

Click any submission to open the full review view. It has the following panels:

#### Plagiarism Panel (top)

Shows the plagiarism risk for the most recent attempt:
- **Risk badge**: NONE / LOW / MEDIUM / HIGH
- **What matched**: dialog names, service API URLs, or bot structure
- **Matching submissions**: links to other submissions with similar fingerprints

HIGH risk automatically blocks auto-confirmation — you must review before confirming.

#### CBM Blueprint Panel

A structural audit of the candidate's bot:
- **Bot Overview**: bot name, version, DialogGPT status, node type counts, FAQ count
- **Per-dialog breakdown**: which dialogs exist, which node types they contain (aiassist, service, entity, etc.), service methods used
- **Compliance checks**: pass/fail for each compliance rule in the manifest (e.g. DialogGPT must be enabled)

> CBM is informational only — it does not affect the score.

#### Scoring Breakdown

- **Webhook score** (80% weight): how many tasks the bot completed correctly
- **FAQ score** (10% weight): how many FAQ questions the bot answered correctly
- **Compliance score** (10% weight): how many compliance checks passed
- **Task-by-task result**: each task shows pass/fail, evidence cards (API snapshots), and transcript

#### Attempt History

A timeline of all submission attempts, showing:
- Attempt number and submission date
- Score for that attempt
- Bot diff from previous attempt (new dialogs, removed dialogs, node count delta)

#### Communications Thread

Full message history between evaluator and candidate. Always visible after the candidate's first submission.

---

## Confirming or Rejecting a Submission

Once you have reviewed the submission:

1. Scroll to the **Confirm** section at the bottom of the review page
2. Add an **evaluator note** (required for fails, optional for passes)
3. Click **Confirm Pass** or **Confirm Fail**

The candidate's status updates immediately and they can see the result in their portal.

### What happens after confirmation

- **Confirmed Pass**: submission marked as complete. No further attempts needed.
- **Confirmed Fail**: attempt counted. Candidate can resubmit if they have attempts remaining.

---

## Granting Attempt Exceptions

By default candidates have 6 attempts. If a candidate has exhausted their attempts but has a valid reason for more:

1. Open the submission review page
2. Click **Grant Exception**
3. Confirm — the candidate's attempt limit is lifted and they can resubmit

The attempt continues from where it left off. Exceptions are flagged visually in the review view so all evaluators can see them.

---

## Holding for Plagiarism Investigation

If you suspect plagiarism but need more time to investigate:

1. Open the submission review page
2. Click **Hold for Investigation**
3. The submission status changes to `on_hold`
4. The attempt does NOT count against the candidate's limit while on hold

When investigation is complete, you have two options:
- **Mark as Original + Continue** — clears the hold, move to normal confirmation flow
- **Request Fresh Work** — system sends an automated message to the candidate, the submission remains on hold until they resubmit

---

## Communications

### Sending a Message to a Candidate

1. Open the submission review page
2. Scroll to the **Communications** section
3. Type your message and click **Send**

Candidates see the message in their portal. Communications are always visible after the first submission, regardless of submission status.

### Viewing Candidate Messages

Incoming messages from candidates appear in the Communications section on the submission review page. New messages are highlighted.

---

## Managing Candidates

### Creating a Submission Record for a New Candidate

Before a candidate can submit, a submission record must exist for them:

1. Go to **Admin → Candidates → New Candidate**
2. Enter the candidate's email address and select the assessment type
3. Click **Create** — a `submission_id` is generated
4. Share the candidate portal link with the candidate: `http://<server>/candidate` (they enter their email to access it)

### Viewing All Candidates

**Admin → Candidates** shows all submission records. Click any record to go to the submission review page.

---

## Common Tasks Quick Reference

| Task | Where |
|------|-------|
| Review a new submission | Admin → Submissions → click submission |
| Confirm pass/fail | Bottom of submission review page |
| Send a message to candidate | Submissions → review page → Communications |
| Check plagiarism | Submissions → review page → Plagiarism Panel |
| Grant extra attempts | Submissions → review page → Grant Exception |
| Create a new manifest | Admin → Manifests → New Manifest |
| Edit an existing manifest | Admin → Manifests → Edit |
| Create a new candidate record | Admin → Candidates → New Candidate |
