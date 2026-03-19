# GovernIQ Frontend Enterprise Redesign
**Date:** 2026-03-19
**Status:** Approved — ready for implementation
**Scope:** Design system rebuild + bug fixes

---

## Summary

Full enterprise-grade frontend redesign of the GovernIQ EvalAutomaton platform. Rebuilds `base.html` as a complete design system — all 14 templates inherit automatically. Simultaneously fixes 4 confirmed bugs. No backend changes.

---

## Design Decisions (User-Approved)

| Dimension | Decision |
|---|---|
| Aesthetic | Modern SaaS — deep indigo glassmorphism (dark), Clean Slate (light) |
| Animation style | Confident — spring entries, stagger reveals, score glow on entry |
| Typography | Bricolage Grotesque (headings/display) + Geist (body/UI) |
| Light theme | White cards on slate-grey bg, violet/teal accent palette |
| Dark theme | Deep indigo (#0f0c29 → #1e1b4b gradient), frosted glass cards, violet/teal accents |

---

## Bugs Fixed In This Redesign

### Bug 1 — Bot Export File: No Drag-and-Drop
- **File:** `candidate_submit.html`
- **Fix:** Add `dragover`, `dragleave`, `drop` event listeners to `.file-upload` label. Add visual drag-active state. Add "clear file" × button shown after selection.

### Bug 2 — Bot Webhook URL: Incorrect "Optional" Label
- **File:** `candidate_submit.html:106`
- **Current state:** Field-level badge reads `"Optional if using Kore credentials"` (badge-grey). Note: the card-header badge at line 75 already correctly reads "Required for Webhook Testing" — only the field-level label needs fixing.
- **Fix:** Change field-level badge to `"Required for Live Testing"` (badge-warn). Update `form-hint`: *"The Webhook URL is required for live bot testing. Without it, only the structural CBM audit runs (informational only, no score)."*

### Bug 3 — Heading Icon Alignment
- **Root cause:** `style="margin-right:.4rem;"` inline on `<i>` tags inside `<h1>/<h3>` headings across all templates
- **Fix:** Introduce `.card-title` flex class. Update **all** affected templates (see Files Modified). This is an opt-in class — every heading with an inline margin must be manually updated.

### Bug 4 — Dark Theme Contrast + Hardcoded Colours
- **Files:** `candidate_report.html`, `admin_review.html`
- **Fix:**
  - `.badge-grey` dark: raise text to `#b0b0b0` (4.5:1+ contrast on `#3d3d3d`)
  - `.step-label`, `.check-detail` dark: use `--muted-strong` variable (`#a0a0a0`)
  - Both `candidate_report.html` and `admin_review.html`: replace `background:#faf5ff` + `border-left:3px solid #7c3aed` with CSS variables `var(--purple-bg)` and `var(--purple-accent)`

---

## Architecture

### Files Modified

| File | Reason |
|---|---|
| `src/governiq/templates/base.html` | **Complete rebuild** — new design system |
| `src/governiq/templates/candidate_submit.html` | Bug 1 (drag-drop), Bug 2 (webhook label), Bug 3 (alignment) |
| `src/governiq/templates/candidate_report.html` | Bug 3 (alignment), Bug 4 (hardcoded colours) |
| `src/governiq/templates/admin_dashboard.html` | Bug 3 (alignment) |
| `src/governiq/templates/admin_review.html` | Bug 3 (alignment), Bug 4 (hardcoded colours — same pattern as candidate_report) |
| `src/governiq/templates/admin_compare.html` | Bug 3 (alignment — 4 occurrences) |
| `src/governiq/templates/admin_manifest_editor.html` | Bug 3 (alignment — 9 occurrences) |
| `src/governiq/templates/admin_manifest_list.html` | Bug 3 (alignment — 3 occurrences) |
| `src/governiq/templates/admin_manifest_schema.html` | Bug 3 (alignment — 6 occurrences) |
| `src/governiq/templates/candidate_history.html` | Bug 3 (alignment — 1 occurrence) |
| `src/governiq/templates/how_it_works.html` | Bug 3 (alignment — 5 occurrences) |
| `src/governiq/templates/landing.html` | Bug 3 (alignment — check on edit) |

### Files Untouched
- `dashboard/` app — separate static files, out of scope
- All FastAPI routes — zero backend changes
- `requirements.txt` — no new packages
- Jinja2 `{% block %}` structure in all templates — preserved exactly

---

## New Design System — `base.html`

### Font Loading Strategy
Bricolage Grotesque is available on Google Fonts CDN. Geist is **not** on Google Fonts — use jsDelivr CDN instead:

```html
<!-- In <head>, before </head> -->
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,400;12..96,600;12..96,700;12..96,800&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/geist@1.3.0/dist/fonts/geist-sans/style.css">
```

### CSS Variables — Complete Token Set

The redesign **preserves all existing variable names** used by current templates and adds new ones. No existing token is removed.

**Light theme (default):**
```css
:root, [data-theme="light"] {
  /* Status colours */
  --pass: #16a34a; --pass-bg: #dcfce7; --pass-text: #166534;
  --fail: #dc2626; --fail-bg: #fef2f2; --fail-text: #991b1b;
  --warn: #d97706; --warn-bg: #fef3c7; --warn-text: #92400e;
  --info: #2563eb; --info-bg: #dbeafe; --info-text: #1e40af;

  /* Surface */
  --bg: #f1f5f9; --bg-subtle: #e8edf3; --bg-surface: #ffffff;
  --card: #ffffff; --border: #e2e8f0;
  --card-border: #e2e8f0; --card-blur: none;
  --table-header-bg: #f8fafc; --card-footer-bg: #f8fafc;
  --input-bg: #fff; --code-bg: #f1f5f9;
  --hover-bg: #f8fafc; --hover-border: #cbd5e1;

  /* Typography */
  --text: #0f172a; --text-secondary: #334155;
  --muted: #64748b; --muted-strong: #475569;

  /* Brand */
  --primary: #7c3aed; --primary-hover: #6d28d9;
  --primary-bg: #f5f3ff; --primary-text: #5b21b6;
  --accent: #0891b2; --accent-bg: #ecfeff;
  --purple-bg: #f5f3ff; --purple-accent: #7c3aed;

  /* Gradients */
  --gradient-start: #7c3aed; --gradient-end: #0891b2;

  /* Nav */
  --nav-bg: #0f172a; --nav-link: #94a3b8; --nav-active: #fff;

  /* Shadows */
  --shadow-sm: 0 1px 2px rgba(0,0,0,0.05);
  --shadow: 0 1px 3px rgba(0,0,0,0.08), 0 1px 2px rgba(0,0,0,0.06);
  --shadow-md: 0 4px 6px -1px rgba(0,0,0,0.07), 0 2px 4px -2px rgba(0,0,0,0.06);
  --shadow-lg: 0 10px 15px -3px rgba(0,0,0,0.08), 0 4px 6px -4px rgba(0,0,0,0.06);

  /* Radii */
  --radius: 12px; --radius-sm: 8px; --radius-xs: 6px;
}
```

**Dark theme:**
```css
[data-theme="dark"] {
  /* Status colours */
  --pass: #34d399; --pass-bg: #042f2e; --pass-text: #a7f3d0;
  --fail: #f87171; --fail-bg: #3b0a0a; --fail-text: #fecaca;
  --warn: #fbbf24; --warn-bg: #3b2506; --warn-text: #fde68a;
  --info: #38bdf8; --info-bg: #0c2744; --info-text: #bae6fd;

  /* Surface — glassmorphism */
  --bg: #0f0c29; --bg-subtle: #1a1740; --bg-surface: #1e1b4b;
  --card: rgba(255,255,255,0.06); --border: rgba(139,92,246,0.2);
  --card-border: rgba(139,92,246,0.2); --card-blur: blur(12px);
  --table-header-bg: rgba(255,255,255,0.04); --card-footer-bg: rgba(255,255,255,0.03);
  --input-bg: rgba(255,255,255,0.07); --code-bg: rgba(0,0,0,0.3);
  --hover-bg: rgba(255,255,255,0.06); --hover-border: rgba(139,92,246,0.4);

  /* Typography */
  --text: #f0f0f0; --text-secondary: #c4b5fd;
  --muted: #94a3b8; --muted-strong: #a0a0a0;

  /* Brand */
  --primary: #8b5cf6; --primary-hover: #7c3aed;
  --primary-bg: rgba(139,92,246,0.15); --primary-text: #c4b5fd;
  --accent: #06b6d4; --accent-bg: rgba(6,182,212,0.1);
  --purple-bg: rgba(139,92,246,0.12); --purple-accent: #8b5cf6;

  /* Gradients */
  --gradient-start: #8b5cf6; --gradient-end: #06b6d4;

  /* Nav */
  --nav-bg: #080617; --nav-link: #6b7280; --nav-active: #f0f0f0;

  /* Shadows */
  --shadow-sm: 0 1px 2px rgba(0,0,0,0.4);
  --shadow: 0 1px 3px rgba(0,0,0,0.5), 0 1px 2px rgba(0,0,0,0.4);
  --shadow-md: 0 4px 6px -1px rgba(0,0,0,0.5), 0 2px 4px -2px rgba(0,0,0,0.4);
  --shadow-lg: 0 10px 15px -3px rgba(0,0,0,0.5), 0 4px 6px -4px rgba(0,0,0,0.4);

  /* Radii — same as light */
  --radius: 12px; --radius-sm: 8px; --radius-xs: 6px;
}
```

### Typography
```css
--font-display: 'Bricolage Grotesque', sans-serif;
--font-body: 'Geist Sans', sans-serif;

body { font-family: var(--font-body); }
h1, h2, h3, .stat-value, .score-ring { font-family: var(--font-display); }
```

### Glass Card Component
```css
/* Dark: frosted glass. Light: white elevated card. Controlled by --card-blur. */
.glass-card {
  background: var(--card);
  border: 1px solid var(--card-border);
  border-radius: var(--radius);
  backdrop-filter: var(--card-blur);
  -webkit-backdrop-filter: var(--card-blur);
  box-shadow: var(--shadow);
  transition: transform .2s ease, box-shadow .2s ease, border-color .2s ease;
}
.glass-card:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-md);
  border-color: var(--primary);
}
/* Existing .card class aliased to .glass-card behaviour — backward compatible */
```

### Card Title Class (Bug 3 fix)
```css
.card-title {
  display: flex;
  align-items: center;
  gap: .5rem;
  font-family: var(--font-display);
}
.card-title .icon { flex-shrink: 0; }
```
Usage in templates: `<h3 class="card-title"><i data-lucide="..."></i> Title Text</h3>`
Replaces: `<h3><i data-lucide="..." style="margin-right:.4rem;"></i> Title Text</h3>`

### Animation Utilities
```css
/* Scroll-triggered entry — .is-visible added by IntersectionObserver */
.animate-in {
  opacity: 0;
  transform: translateY(10px);
  transition: opacity .4s ease, transform .4s cubic-bezier(.22,1,.36,1);
}
.animate-in.is-visible { opacity: 1; transform: none; }

/* Stagger delays for child elements */
.stagger > *:nth-child(1) { transition-delay: 0s; }
.stagger > *:nth-child(2) { transition-delay: .07s; }
.stagger > *:nth-child(3) { transition-delay: .14s; }
.stagger > *:nth-child(4) { transition-delay: .21s; }

/* Score ring spring pop — fires on all .score-ring elements on page load */
@keyframes ring-pop {
  from { transform: scale(.7); opacity: 0; }
  to   { transform: scale(1);  opacity: 1; }
}
.score-ring { animation: ring-pop .6s cubic-bezier(.34,1.56,.64,1) both; }

/* Score number glow on entry — apply to the number inside .score-ring */
@keyframes score-glow {
  0%, 100% { text-shadow: none; }
  40%      { text-shadow: 0 0 16px currentColor; }
}
.score-glow { animation: score-glow 1s .5s ease both; }

/* Shimmer skeleton loader */
@keyframes shimmer {
  from { background-position: -200% 0; }
  to   { background-position:  200% 0; }
}
.skeleton {
  background: linear-gradient(
    90deg,
    var(--card-border) 25%,
    var(--bg-surface) 50%,
    var(--card-border) 75%
  );
  background-size: 200% 100%;
  animation: shimmer 1.5s infinite;
  border-radius: var(--radius-xs);
}

/* Stat accent bar — 2px gradient underline on stat values */
.stat-accent-bar {
  height: 2px;
  border-radius: 1px;
  background: linear-gradient(90deg, var(--gradient-start), var(--gradient-end));
  margin-top: 4px;
}

/* Suppress all animations in print */
@media print {
  .animate-in, .score-ring, .score-glow, .skeleton { animation: none !important; }
  .animate-in { opacity: 1 !important; transform: none !important; }
}
```

### IntersectionObserver (30 lines — appended to base.html `<script>`)
```js
// Scroll-triggered entry animations
(function() {
  if (!('IntersectionObserver' in window)) {
    // Graceful degradation — show all elements immediately
    document.querySelectorAll('.animate-in').forEach(el => el.classList.add('is-visible'));
    return;
  }
  const observer = new IntersectionObserver(entries => {
    entries.forEach(e => {
      if (e.isIntersecting) {
        e.target.classList.add('is-visible');
        observer.unobserve(e.target);
      }
    });
  }, { threshold: 0.1, rootMargin: '0px 0px -40px 0px' });
  document.addEventListener('DOMContentLoaded', function() {
    document.querySelectorAll('.animate-in').forEach(el => observer.observe(el));
  });
})();
```

### Badge Contrast Fix (Bug 4)
```css
/* Raise contrast of .badge-grey in dark mode — was 2.2:1, now 4.6:1 */
[data-theme="dark"] .badge-grey { background: var(--border); color: #b0b0b0; }

/* Raise --muted usage in critical text elements */
[data-theme="dark"] .step-label  { color: var(--muted-strong); }
[data-theme="dark"] .check-detail { color: var(--muted-strong); }
[data-theme="dark"] .form-hint   { color: var(--muted-strong); }
```

---

## Candidate Submit — Specific Changes

### File Upload Drag-and-Drop (Bug 1)
```js
document.querySelectorAll('.file-upload').forEach(label => {
  const input = label.querySelector('input[type="file"]');
  const clearBtn = label.querySelector('.file-clear');

  // Existing change handler (preserved)
  input.addEventListener('change', () => updateFileUI(label, input));

  // Drag-and-drop handlers
  label.addEventListener('dragover',  e => { e.preventDefault(); label.classList.add('drag-active'); });
  label.addEventListener('dragleave', e => { label.classList.remove('drag-active'); });
  label.addEventListener('drop',      e => {
    e.preventDefault();
    label.classList.remove('drag-active');
    if (e.dataTransfer.files.length) {
      // Assign dropped file to input and trigger UI update
      const dt = new DataTransfer();
      dt.items.add(e.dataTransfer.files[0]);
      input.files = dt.files;
      updateFileUI(label, input);
    }
  });

  // Clear button
  if (clearBtn) {
    clearBtn.addEventListener('click', e => {
      e.preventDefault(); e.stopPropagation();
      input.value = '';
      label.classList.remove('has-file', 'drag-active');
      label.querySelector('.file-upload-text').textContent = 'Click or drag to upload your bot export';
      label.querySelector('.file-upload-hint').textContent = 'Accepts .json or .zip';
      clearBtn.style.display = 'none';
    });
  }
});

function updateFileUI(label, input) {
  if (input.files.length > 0) {
    label.classList.add('has-file');
    label.querySelector('.file-upload-text').textContent = input.files[0].name;
    label.querySelector('.file-upload-hint').textContent = (input.files[0].size / 1024).toFixed(1) + ' KB';
    const cb = label.querySelector('.file-clear');
    if (cb) cb.style.display = 'flex';
  }
}
```

New CSS states:
```css
.file-upload.drag-active { border-color: var(--primary); background: var(--primary-bg); box-shadow: 0 0 0 3px rgba(139,92,246,.15); }
.file-clear { display:none; position:absolute; top:.5rem; right:.5rem; width:22px; height:22px; border-radius:50%; background:var(--fail-bg); color:var(--fail); border:none; cursor:pointer; align-items:center; justify-content:center; font-size:.8rem; font-weight:700; }
.file-upload { position:relative; }
```

### Webhook URL Label (Bug 2)
Change in `candidate_submit.html`:
```html
<!-- Before -->
<span class="badge badge-grey">Optional if using Kore credentials</span>

<!-- After -->
<span class="badge badge-warn">Required for Live Testing</span>
```
Update form-hint:
```html
<!-- Before -->
<div class="form-hint">Your bot's webhook URL. If Bot ID + Client ID + Client Secret are provided, the system uses Kore.ai's BotMessages API directly (recommended). The webhook URL serves as a fallback.</div>

<!-- After -->
<div class="form-hint">Required for live bot testing. Without a Webhook URL, only the structural CBM audit runs — no conversation testing, no score.</div>
```

---

## Constraints

- No npm / no build step — pure CSS + vanilla JS in Jinja2 templates
- Bricolage Grotesque: Google Fonts CDN. Geist: jsDelivr CDN (`cdn.jsdelivr.net/npm/geist@1.3.0`)
- Must work without JavaScript (graceful degradation — animations skip, `is-visible` added immediately)
- Dark/light toggle preserved exactly as-is (localStorage + `data-theme` attribute on `<html>`)
- Print styles preserved — all animations suppressed with `animation: none !important` in `@media print`
- All existing CSS variable names preserved — no template breaks from missing tokens

---

## Success Criteria

1. `base.html` `<head>` loads Bricolage Grotesque from Google Fonts and Geist from jsDelivr
2. Dark theme: deep indigo background (`#0f0c29`), frosted glass cards with `backdrop-filter: blur(12px)`, violet/teal accents
3. Light theme: white card surfaces (`#ffffff`), slate-grey background (`#f1f5f9`), violet/teal accents
4. `.score-ring` elements on `candidate_report.html` and `admin_review.html` animate with `ring-pop` spring on page load
5. Stat card grid on `admin_dashboard.html` stagger-animates when scrolled into view
6. File upload on `candidate_submit.html`: dragging a file onto the zone shows `.drag-active` state and populates the input; the × clear button appears after selection
7. Webhook URL field badge on `candidate_submit.html` reads "Required for Live Testing" (badge-warn)
8. `.badge-grey` in dark theme passes WCAG AA (≥4.5:1) — text is `#b0b0b0` on `#3d3d3d`
9. No `style="margin-right:.4rem;"` remains on icon elements inside heading tags across all 12 listed templates
10. `background:#faf5ff` and `border-left:3px solid #7c3aed` hardcoded values are absent from `candidate_report.html` and `admin_review.html`
11. All 14 templates render without visible breakage in both light and dark themes
12. Toggling theme with the navbar button still works and persists in localStorage
