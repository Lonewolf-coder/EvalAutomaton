# EvalAutomaton — GovernIQ Universal Evaluation Platform

## What this project does
EvalAutomaton is an automated chatbot evaluation platform that scores 
candidate-built Kore.ai XO bot submissions for certification purposes.
It replaces manual QA testing with a consistent, repeatable, auditable 
process using a dual-pipeline architecture.


## Tech stack
- Python 3.14
- FastAPI + Uvicorn (web framework)
- Pydantic v2 (data validation)
- OpenAI API / Anthropic Claude / LM Studio (LLM driver)
- Jinja2 (HTML templates — Admin + Candidate portals)
- sentence-transformers (FAQ semantic similarity)
- Local JSON storage (PostgreSQL-migration-ready)
- pytest for testing

## Architecture
### Dual Pipeline
1. CBM Structural Audit — parses appDefinition.json from bot export ZIP
   - Checks dialog/node/FAQ compliance
   - Informational only, 0% scoring weight
2. Webhook Functional Testing — LLM-powered conversation driver
   - Talks to candidate's live bot webhook
   - Calls mock API to verify state
   - 80% scoring weight

### Engine Patterns (ever-growing, domain-free)
Patterns live in src/governiq/patterns/ — each extends PatternExecutor.
Current patterns: CREATE, CREATE_WITH_AMENDMENT, RETRIEVE, MODIFY, 
DELETE, EDGE_CASE, WELCOME, INTERRUPTION, LANGUAGE, FORM, SURVEY, CBM_ONLY
New patterns are added via the 7-step developer checklist in developer_guide.md.
A new pattern is only justified if existing ones genuinely cannot express 
the scenario. Most things can be expressed as variants of CREATE.
All domain knowledge lives in JSON manifests — never in code.

### Key Design Rules (all agents must respect these)
1. Engine is completely domain-free — no domain words in code ever
2. Cross-task state via RuntimeContext only — no session bleed
3. Plagiarism detection via SHA-256 fingerprinting (independent of CBM)
4. CBM audit is always informational — scores come only from webhook results
5. Scoring logic lives in scoring.py — it is intentionally modifiable
6. Never hardcode score weights anywhere outside scoring.py
7. Task weights declared in manifests must be respected by the engine
8. Dead code (compute_weighted_score) should be flagged but not deleted without explicit     instruction — it may be repurposed

## Project structure
- /tests — all test files
- /manifests — JSON domain manifests
- appDefinition.json — bot export structure

## Coding rules all agents must follow
- Always use the existing venv
- Never install packages without updating requirements.txt
- All new code must have a corresponding test
- Use python-dotenv for secrets — never hardcode API keys or URLs
- Keep engine completely domain-free — no domain words in source code
- RuntimeContext is the only way to pass state between tasks
- Keep functions small and focused

## Frontend design principles
- Brand: GovernIQ Universal Evaluation Platform
- Clean, professional, modern UI — dashboard feel
- Admin portal and Candidate portal are visually distinct
- Score breakdown must be clearly visualised (pipeline weights)
- Mobile-friendly layouts
- Use consistent colour palette across both portals

## Agent routing rules

**Use parallel agents when:**
- Frontend (Jinja2/CSS) and backend (FastAPI) changes are independent
- Running tests while writing new code
- CBM parser work is independent of webhook engine work

**Use sequential agents when:**
- Schema or RuntimeContext changes (other agents depend on this)
- New engine pattern added (manifests → engine → tests → frontend)
- Multiple agents would touch the same file

## Git rules
- Commit format: "type: description" (e.g. "feat: add EDGE_CASE pattern")
- Always run tests before committing
- Never commit .env files or API keys
- Never commit appDefinition.json with real candidate data

## Frontend improvement roadmap

### Admin portal priorities
- Score breakdown chart — visual pie/bar showing 80/10/10 pipeline weights
- Candidate submission table with live status badges
  (Pending / Running / Pass / Fail / Flagged)
- Plagiarism flag highlighting in submission list
- CBM audit results collapsible panel (clearly marked "informational only")

### Candidate portal priorities  
- Clean score reveal page — large score number, colour coded
  (green ≥ 80, amber 60–79, red < 60)
- Per-pipeline breakdown: Webhook / FAQ / Compliance scores shown separately
- Downloadable PDF report of their evaluation
- Clear pass/fail banner with certification status