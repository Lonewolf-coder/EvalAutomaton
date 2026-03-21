# UI Redesign + Platform URL Configurability — Design Spec

**Date:** 2026-03-21
**Status:** Approved
**Sprint:** Same sprint as bot pre-registration + eval observability

---

## Problem Statement

1. **Platform URL is hardcoded** — `KoreCredentials.platform_url` defaults to a string literal in `jwt_auth.py`. Any Kore.ai hostname change requires a code deploy.
2. **Credential form UX is broken** — the client_secret field is smushed into a half-width 2-column grid cell; the visibility toggle is a detached emoji button that misaligns on every OS.
3. **Design aesthetic is inconsistent** — the app's custom CSS design system works but has grown organically. Forms lack visual grouping, spacing is tight, and there is no coherent component pattern for input-with-action groups.

---

## Goals

- Admin can change the Kore.ai platform URL default at runtime without a code deploy.
- All credential/secret inputs have an inline, properly aligned visibility toggle using Lucide icons.
- All pages share a coherent visual system: dark background, gradient icon section headers, coloured status badges with pulsing dots, context-aware action buttons, and clear typographic hierarchy.
- Zero alignment issues in the rendered app — all alignment rules are stated explicitly in this spec.

## Non-Goals

- No switch to Tailwind, Bootstrap, or any external CSS framework.
- No changes to scoring logic, engine patterns, manifest schema, or any backend business logic.
- No new Python packages.

---

## Part 1 — Platform URL Configurability

### Data model

New file: `data/platform_config.json`

```json
{
  "kore_platform_url": "https://platform.kore.ai/",
  "updated_at": "2026-03-21T10:00:00+00:00"
}
```

**Load function** (`src/governiq/core/platform_config.py`, new file):

```python
# Absolute path derived from this file — safe regardless of Uvicorn working directory
PLATFORM_CONFIG_PATH = Path(__file__).parent.parent.parent.parent / "data" / "platform_config.json"
DEFAULT_KORE_PLATFORM_URL = "https://platform.kore.ai/"

def load_platform_config() -> dict:
    if PLATFORM_CONFIG_PATH.exists():
        try:
            return json.loads(PLATFORM_CONFIG_PATH.read_text())
        except Exception:
            pass
    return {"kore_platform_url": DEFAULT_KORE_PLATFORM_URL}

def save_platform_config(kore_platform_url: str) -> None:
    PLATFORM_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    PLATFORM_CONFIG_PATH.write_text(json.dumps({
        "kore_platform_url": kore_platform_url.strip(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }, indent=2))

def get_kore_platform_url() -> str:
    return load_platform_config().get("kore_platform_url", DEFAULT_KORE_PLATFORM_URL)
```

### KoreCredentials change

`jwt_auth.py`: `platform_url: str = ""` (empty default — callers must supply it from config). `validate()` already enforced non-empty after the bot pre-registration changes. Call sites use `get_kore_platform_url()` when no explicit override is provided.

### Admin settings — new section

`admin_settings.html` gains a **"Kore.ai Platform Defaults"** section (card, same visual pattern as the LLM provider card):

- Field: **Default Platform URL** — text input, pre-filled from `get_kore_platform_url()`
- Button: **Save** — POST to `POST /admin/settings/platform` with `kore_platform_url` form field
- Success: inline green confirmation banner ("Saved — candidates will see this default on their registration form")
- Hint text: "Pre-fills the Platform URL field on the candidate registration form. Candidates can still override it for their specific bot setup."

### Admin settings route addition

`POST /admin/settings/platform` — reads `kore_platform_url` from form, validates it is a non-empty URL string, calls `save_platform_config()`, redirects to `/admin/settings` with `?saved=platform`.

### Registration form

`GET /candidate/register` passes `kore_platform_url=get_kore_platform_url()` in template context. The `platform_url` input field in the form is pre-filled with this value. Candidates can edit it.

---

## Part 2 — Design System Updates (`base.html`)

### 2.1 Theme — Dark-first with inverted light palette

The existing `base.html` sets variables on `html[data-theme="light"]` / `html[data-theme="dark"]`. The new variables follow the same selector pattern — **do not change the selector** from `html` to `:root`, as existing templates reference `data-theme` on `<html>`.

New variables are **added alongside** existing ones. Old variables are **kept as aliases** pointing to the new ones during this sprint so that any template not yet updated continues to work. They are removed in a follow-up cleanup commit only after all templates are updated.

**Variable migration map** — old name → new name (aliases wired in the same `:root`/`html` block):

| Old variable | Maps to new variable | Action |
|---|---|---|
| `--card` | → `--card-bg` | alias |
| `--border` | → `--card-border` | alias |
| `--nav-bg` | Keep as alias `var(--bg)` this sprint; update `.topnav` in `base.html` (line ~160) to use `.nav` class instead. Only remove `--nav-bg` from variables after `.topnav` references are gone | keep as alias then remove |
| `--bg-subtle` | → `--bg-surface` | alias |
| `--shadow-sm`, `--shadow-md`, `--shadow-lg` | kept as-is (not replaced this sprint) | keep |
| `--radius-xs` | kept as-is | keep |

```css
html[data-theme="dark"], html:not([data-theme="light"]) {
  /* New canonical variables */
  --bg:          #0f0f1a;
  --bg-surface:  rgba(255,255,255,.03);
  --card-bg:     rgba(255,255,255,.03);
  --card-border: rgba(255,255,255,.07);
  --text:        #e2e8f0;
  --text-secondary: #94a3b8;
  --muted:       #64748b;
  --input-bg:    rgba(255,255,255,.04);
  --primary:     #7c3aed;
  --accent:      #0891b2;
  --radius:      14px;
  --radius-sm:   8px;
  /* Backward-compat aliases — removed after all templates updated */
  --card:        var(--card-bg);
  --border:      var(--card-border);
  --bg-subtle:   var(--bg-surface);
  --nav-bg:      var(--bg);   /* kept until .topnav is migrated to .nav */
}
html[data-theme="light"] {
  --bg:          #f8fafc;
  --bg-surface:  #ffffff;
  --card-bg:     #ffffff;
  --card-border: #e2e8f0;
  --text:        #0f172a;
  --text-secondary: #475569;
  --muted:       #94a3b8;
  --input-bg:    #ffffff;
  --primary:     #7c3aed;
  --accent:      #0891b2;
  --radius:      14px;
  --radius-sm:   8px;
  /* Backward-compat aliases */
  --card:        var(--card-bg);
  --border:      var(--card-border);
  --bg-subtle:   var(--bg-surface);
  --nav-bg:      var(--bg);
}
```

### 2.2 Navigation

```css
.nav {
  background: rgba(15,15,26,.95);
  border-bottom: 1px solid rgba(124,58,237,.2);
  backdrop-filter: blur(12px);
  padding: .75rem 1.5rem;
  display: flex; align-items: center; justify-content: space-between;
  position: sticky; top: 0; z-index: 100;
}
.nav-brand { display: flex; align-items: center; gap: .6rem; }
.nav-logo {
  width: 30px; height: 30px; border-radius: 8px;
  background: linear-gradient(135deg, #7c3aed, #0891b2);
  display: flex; align-items: center; justify-content: center;
}
/* Alignment rule: nav-logo icon is always 16×16px SVG centred in 30×30px container */
.nav-links { display: flex; gap: .25rem; align-items: center; }
.nav-link {
  padding: .4rem .85rem; border-radius: 7px; font-size: .78rem;
  font-weight: 500; color: var(--text-secondary);
  transition: all .15s; cursor: pointer; text-decoration: none;
}
.nav-link.active { background: rgba(124,58,237,.15); color: #a78bfa; }
.nav-status-badge {
  display: flex; align-items: center; gap: .5rem;
  background: rgba(16,163,74,.1); border: 1px solid rgba(16,163,74,.3);
  border-radius: 20px; padding: .3rem .75rem;
  font-size: .72rem; color: #4ade80; white-space: nowrap;
}
```

### 2.3 Stat cards

```css
.stats-grid { display: grid; grid-template-columns: repeat(4,1fr); gap: 1rem; margin-bottom: 1.75rem; }
.stat-card {
  background: var(--card-bg); border: 1px solid var(--card-border);
  border-radius: var(--radius); padding: 1.1rem 1.25rem;
  display: flex; align-items: center; gap: 1rem;  /* alignment: always centre-aligned vertically */
  transition: border-color .2s, background .2s;
}
/* Alignment rule: stat-icon is always 42×42px, icon SVG always 18×18px */
.stat-icon {
  width: 42px; height: 42px; border-radius: 11px; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
}
.stat-val { font-size: 1.6rem; font-weight: 800; letter-spacing: -.5px; line-height: 1; }
.stat-label { font-size: .7rem; color: var(--muted); margin-top: .2rem; font-weight: 500;
              text-transform: uppercase; letter-spacing: .4px; }
```

### 2.4 Section headers (gradient icon pattern)

Used on all cards that group related content:

```css
/* Alignment rule: section-icon is always 36×36px container; SVG always 16×16px, stroke white, stroke-width 2 */
.section-icon {
  width: 36px; height: 36px; border-radius: 10px; flex-shrink: 0;
  background: linear-gradient(135deg, var(--primary), var(--accent));
  display: flex; align-items: center; justify-content: center;
}
.section-icon.green  { background: linear-gradient(135deg, #059669, #0891b2); }
.section-icon.amber  { background: linear-gradient(135deg, #d97706, #dc2626); }
.section-hdr { display: flex; align-items: center; gap: .75rem; margin-bottom: 1.25rem; }
.section-title { font-size: 1rem; font-weight: 700; letter-spacing: -.2px; }
.section-sub  { font-size: .72rem; color: var(--muted); margin-top: .1rem; }
```

### 2.5 Input-group pattern (new)

Replaces the detached emoji toggle. Required for all password/secret fields across the entire app:

```css
.input-group {
  display: flex;
  border: 1.5px solid var(--card-border);
  border-radius: var(--radius-sm);
  overflow: hidden;
  background: var(--input-bg);
  transition: border-color .15s, box-shadow .15s;
}
.input-group:focus-within {
  border-color: var(--primary);
  box-shadow: 0 0 0 3px rgba(124,58,237,.15);
}
/* Alignment rule: input and toggle button share the same height via flex stretch */
.input-group .form-input {
  flex: 1; border: none; border-radius: 0;
  background: transparent;
  /* Do NOT set padding-right — the button provides the right-side affordance */
}
.input-group .form-input:focus { box-shadow: none; border-color: transparent; }
.toggle-visibility-btn {
  padding: 0 .75rem;
  background: none; border: none; border-left: 1px solid var(--card-border);
  color: var(--muted); cursor: pointer; display: flex; align-items: center;
  transition: color .15s, background .15s; flex-shrink: 0;
}
.toggle-visibility-btn:hover { color: var(--text); background: rgba(255,255,255,.05); }
/* Alignment rule: toggle icon is always 15×15px Lucide SVG */
```

**`toggleVisibility` function** — updated in `base.html` to use Lucide icons instead of emoji:

```javascript
function toggleVisibility(inputId, btn) {
  const input = document.getElementById(inputId);
  if (!input) return;
  const isHidden = input.type === 'password';
  input.type = isHidden ? 'text' : 'password';
  btn.setAttribute('aria-label', isHidden ? 'Hide' : 'Show');
  // Replace innerHTML then rescan the whole document — lucide.createIcons() does not
  // accept a { nodes } option in the bundled browser build; a full rescan is cheap
  // (one button node) and is the documented safe approach.
  btn.innerHTML = `<i data-lucide="${isHidden ? 'eye-off' : 'eye'}" style="width:15px;height:15px;stroke:currentColor;stroke-width:2;"></i>`;
  if (window.lucide) lucide.createIcons();
}
```

### 2.6 Status badges

```css
/* Alignment rule: badge is always inline-flex, align-items:center, gap:.3rem */
.badge {
  display: inline-flex; align-items: center; gap: .3rem;
  padding: .22rem .6rem; border-radius: 6px;
  font-size: .65rem; font-weight: 700; letter-spacing: .3px; text-transform: uppercase;
}
.badge-dot { width: 5px; height: 5px; border-radius: 50%; flex-shrink: 0; }
/* pulse keyframe — generic opacity fade, used for running/live indicators */
@keyframes pulse { 0%,100% { opacity:1; } 50% { opacity:.35; } }

.badge.running { background: rgba(37,99,235,.15); color: #60a5fa; border: 1px solid rgba(37,99,235,.25); }
.badge.running .badge-dot { background: #60a5fa; animation: pulse 1.5s infinite; }
.badge.pass    { background: rgba(5,150,105,.15);  color: #34d399; border: 1px solid rgba(5,150,105,.25); }
.badge.fail    { background: rgba(220,38,38,.12);  color: #f87171; border: 1px solid rgba(220,38,38,.2); }
.badge.halted  { background: rgba(217,119,6,.12);  color: #fbbf24; border: 1px solid rgba(217,119,6,.2); }
```

### 2.7 Table layout

```css
/* Alignment rule: all td must have vertical-align:middle — no exceptions */
.tbl th, .tbl td { vertical-align: middle; }
.tbl th {
  padding: .6rem 1.1rem; text-align: left;
  font-size: .65rem; font-weight: 700; text-transform: uppercase; letter-spacing: .5px;
  color: var(--muted); border-bottom: 1px solid var(--card-border);
}
.tbl td { padding: .85rem 1.1rem; border-bottom: 1px solid rgba(255,255,255,.04); }
```

**Halt reason inline** — rendered as a separate `<div>` inside the status `<td>`, below the badge. NOT inline with the badge (avoids horizontal crowding):

```html
<!-- Alignment rule: badge and halt-reason are flex-direction:column, align-items:flex-start -->
<td>
  <div style="display:flex;flex-direction:column;align-items:flex-start;gap:.3rem;">
    <span class="badge halted"><span class="badge-dot"></span>Halted</span>
    <span class="halt-reason">LLM call failed after retry: timeout</span>
  </div>
</td>
```

```css
.halt-reason {
  font-size: .68rem; color: #fbbf24;
  background: rgba(217,119,6,.08); border: 1px solid rgba(217,119,6,.15);
  border-radius: 5px; padding: .15rem .5rem;
  max-width: 240px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
```

### 2.8 Action buttons

```css
/* Alignment rule: all .btn-action are inline-flex, align-items:center, gap:.3rem */
/* Icon SVG is always 11×11px, stroke:currentColor, stroke-width:2.5 */
.btn-action {
  display: inline-flex; align-items: center; gap: .3rem;
  padding: .28rem .65rem; border-radius: 6px;
  font-size: .68rem; font-weight: 600; border: 1px solid transparent;
  cursor: pointer; transition: all .15s; white-space: nowrap;
}
.btn-action.watch   { background: rgba(37,99,235,.15); color: #60a5fa; border-color: rgba(37,99,235,.2); }
.btn-action.review  { background: rgba(5,150,105,.12);  color: #34d399; border-color: rgba(5,150,105,.2); }
.btn-action.restart { background: rgba(124,58,237,.15); color: #a78bfa; border-color: rgba(124,58,237,.2); }
.btn-action.log     { background: rgba(255,255,255,.06); color: #94a3b8; border-color: rgba(255,255,255,.1); }
```

### 2.9 Score pill

```css
/* Alignment rule: score-pill is inline-flex, align-items:center */
.score-pill {
  display: inline-flex; align-items: center;
  padding: .25rem .7rem; border-radius: 20px; font-weight: 700; font-size: .8rem;
}
.score-pill.pass { background: rgba(5,150,105,.15); color: #34d399; }
.score-pill.fail { background: rgba(220,38,38,.12); color: #f87171; }
```

### 2.10 Form sections (credential form pattern — Option C)

Applied to all forms across the app:

```css
.form-section-hdr {
  display: flex; align-items: center; gap: .6rem;
  margin-bottom: 1rem; padding-bottom: .75rem;
  border-bottom: 1px solid var(--card-border);
}
/* Alignment rule: form-section-icon is 28×28px; SVG is 13×13px white */
.form-section-icon {
  width: 28px; height: 28px; border-radius: 7px; flex-shrink: 0;
  background: linear-gradient(135deg, var(--primary), var(--accent));
  display: flex; align-items: center; justify-content: center;
}
.form-section-title { font-size: .8rem; font-weight: 700; color: var(--text); }
.form-section-sub   { font-size: .68rem; color: var(--muted); margin-top: .1rem; }
```

---

## Part 3 — Templates Updated

Every template that extends `base.html` is updated to use the new component classes. No template introduces its own alignment CSS — all layout comes from `base.html` classes.

### Alignment rules that apply to every template

1. All flex containers that hold icons + text use `align-items: center`.
2. All grid cells use `align-items: start` unless the content is a single line (then `center`).
3. All table cells use `vertical-align: middle` via the `.tbl` rule — never override this.
4. All icon SVGs have explicit `width` and `height` attributes matching the size class they live in (never rely on CSS `width`/`height` alone on SVG — set both the attribute and CSS).
5. Input-group: the `.form-input` inside `.input-group` never has `border-radius` — the parent handles it.
6. Badges and pills: never add `margin` inside a badge — control spacing from the parent container.
7. Action buttons in tables: wrapped in `<div class="actions" style="display:flex;gap:.4rem;align-items:center;">` — never raw siblings.

### Pages updated

All 16 templates (13 existing + 3 new) plus `base.html` itself are listed below (17 rows total). Templates not requiring structural changes still inherit the updated CSS variables and component classes automatically — they are listed with scope "CSS only" so the implementer knows they were consciously evaluated and require no markup changes.

| Template | Scope | Key changes |
|----------|-------|-------------|
| `base.html` | Full | Theme variables + migration aliases, nav, all component CSS classes above, updated `toggleVisibility()`, `@keyframes pulse` |
| `admin_dashboard.html` | Full | Stats grid, submissions table with new badge/button/halt-reason pattern, filter bar |
| `admin_settings.html` | Full | New "Kore.ai Platform Defaults" section card; LLM section gets section-icon header |
| `admin_bots.html` (new) | Full | Bot registry table — route `GET /admin/bots` defined in bot pre-registration spec |
| `admin_review.html` | Full | Section-icon headers for score breakdown, task list, compliance panel; safe-defaulted context variables (from restart/review bug fix spec) |
| `admin_conversation.html` (new) | Full | Chat timeline UI — route `GET /admin/evaluation/{id}/conversation` defined in eval observability spec |
| `admin_compare.html` | Full | Update card and table markup to use `.tbl`, `.section-icon`, new badge classes |
| `admin_manifest_list.html` | Full | Table updated to use `.tbl` with `vertical-align:middle` |
| `admin_manifest_editor.html` | Full | Form sections get `.form-section-hdr` pattern; any secret-style fields get input-group |
| `admin_manifest_schema.html` | CSS only | No markup changes; inherits updated variables |
| `candidate_register.html` (new) | Full | Option C sectioned form: credentials section + platform connection section; input-group for client_secret |
| `candidate_submit.html` | Full | Sectioned form pattern on credential block; input-group for client_secret; platform_url removed (from registration) |
| `candidate_history.html` | Full | Submissions table updated to `.tbl` with badge/score-pill pattern |
| `candidate_report.html` | Full | Score reveal page — large score number, pipeline breakdown, pass/fail banner |
| `landing.html` | Full | Landing page updated to dark theme; hero and feature cards use new card CSS |
| `error.html` | CSS only | Inherits base; no markup changes needed |
| `how_it_works.html` | CSS only | Informational; no markup changes needed |

---

## Part 4 — Files Affected

### New files
| File | Responsibility |
|------|---------------|
| `src/governiq/core/platform_config.py` | `load_platform_config`, `save_platform_config`, `get_kore_platform_url` |

### Modified files
| File | What changes |
|------|-------------|
| `src/governiq/webhook/jwt_auth.py` | `platform_url` default → `""` (callers supply from `get_kore_platform_url()`) |
| `src/governiq/admin/routes.py` | Add `POST /admin/settings/platform`; pass `kore_platform_url` to settings template context |
| `src/governiq/candidate/routes.py` | Pass `kore_platform_url=get_kore_platform_url()` to register template context |
| `src/governiq/templates/base.html` | All CSS updates (sections 2.1–2.10 above); updated `toggleVisibility()` |
| `src/governiq/api/routes.py` | Replace `os.environ.get("KORE_PLATFORM_URL", "https://bots.kore.ai")` with `get_kore_platform_url()` from `platform_config.py`; remove the env-var fallback |
| All templates listed in Part 3 | Updated to use new component classes — no per-template alignment CSS |

### KoreCredentials construction — all call sites

Setting `platform_url: str = ""` in `jwt_auth.py` means every call site that constructs `KoreCredentials` must supply `platform_url` explicitly. The three call sites and their required fix:

| File | Current | Fix |
|------|---------|-----|
| `candidate/routes.py` submit handler (line ~445) | Constructs `KoreCredentials(bot_id, client_id, client_secret, bot_name)` — no `platform_url`, relies on dataclass default (will become `""`) | Read `platform_url` from the submitted form field; fallback to `get_kore_platform_url()` if blank |
| `api/routes.py` (line ~329) | `os.environ.get("KORE_PLATFORM_URL", "https://bots.kore.ai")` hardcoded env-var call | Replace with `get_kore_platform_url()` |

Note: `admin/routes.py` restart handler passes `kore_creds=None` to `_run_evaluation_background` — it does **not** construct `KoreCredentials` itself. The bot pre-registration spec adds credential loading there from the bot registration record (which already includes `platform_url`). No additional change is needed in `admin/routes.py` for this spec.

`platform_url` validation (non-empty check) is enforced **at the route level only** in `POST /admin/settings/platform`. `KoreCredentials.validate()` is not touched — it does not validate `platform_url` and must not be changed to do so, as some callers construct `KoreCredentials` before a platform URL is available.

### Tests
| File | What's tested |
|------|--------------|
| `tests/test_platform_config.py` (new) | `load_platform_config` returns default when no file exists; `load_platform_config` returns default when JSON is corrupt; `save_platform_config` writes correct JSON; `get_kore_platform_url` reads persisted value; `POST /admin/settings/platform` with valid URL → saves + redirects to `/admin/settings?saved=platform`; `POST /admin/settings/platform` with empty body → 422 or redirect with error (validates non-empty URL guard) |
