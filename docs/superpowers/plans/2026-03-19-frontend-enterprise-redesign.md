# GovernIQ Frontend Enterprise Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild `base.html` as a Modern SaaS enterprise design system (deep indigo glassmorphism dark / clean slate light, Bricolage Grotesque + Geist fonts, Confident animations) and fix 4 confirmed bugs across 12 templates.

**Architecture:** Single design system rebuild in `base.html` — all 14 templates inherit automatically. Bug fixes applied file-by-file in subsequent tasks. No backend changes, no npm, no build step — pure CSS + vanilla JS in Jinja2 templates.

**Tech Stack:** Jinja2 HTML templates, embedded CSS (CSS custom properties), vanilla JS, Google Fonts CDN (Bricolage Grotesque), jsDelivr CDN (Geist), Lucide icons (existing).

**Spec:** `docs/superpowers/specs/2026-03-19-frontend-enterprise-redesign.md`

---

## File Map

| File | Task | Change |
|---|---|---|
| `src/governiq/templates/base.html` | Task 1 | Complete rebuild — design system |
| `src/governiq/templates/candidate_submit.html` | Task 2 | Bug 1 (drag-drop), Bug 2 (webhook label), Bug 3 (alignment) |
| `src/governiq/templates/candidate_report.html` | Task 3 | Bug 3 (alignment), Bug 4 (hardcoded colours) |
| `src/governiq/templates/admin_review.html` | Task 3 | Bug 3 (alignment), Bug 4 (hardcoded colours) |
| `src/governiq/templates/admin_review.html` | Task 3 | Bug 3 (alignment), Bug 4 (hardcoded colours) |
| `src/governiq/templates/admin_dashboard.html` | Task 4 | Bug 3 (alignment) + animate-in stat cards |
| `src/governiq/templates/candidate_history.html` | Task 4 | Bug 3 (alignment) |
| `src/governiq/templates/how_it_works.html` | Task 4 | Bug 3 (alignment) |
| `src/governiq/templates/landing.html` | Task 4 | Bug 3 (alignment) |
| `src/governiq/templates/admin_compare.html` | Task 5 | Bug 3 (alignment) |
| `src/governiq/templates/admin_manifest_list.html` | Task 5 | Bug 3 (alignment) |
| `src/governiq/templates/admin_manifest_schema.html` | Task 5 | Bug 3 (alignment) |
| `src/governiq/templates/admin_manifest_editor.html` | Task 5 | Bug 3 (alignment) |

---

## How to run the dev server

```bash
cd C:/Users/Kiran.Guttula/Documents/EvalAutomaton
source venv/Scripts/activate   # Windows Git Bash / venv activate
uvicorn src.governiq.main:app --reload --port 8000
```

Open `http://localhost:8000` to verify. Candidate portal: `/candidate/`. Admin portal: `/admin/`.

---

## Task 1: Rebuild `base.html` — Design System Foundation

**Files:**
- Modify: `src/governiq/templates/base.html` (full rewrite)

This is the foundation. All other tasks depend on it. Read the existing file first to understand the `{% block %}` structure — preserve it exactly.

- [ ] **Step 1: Read the existing file to understand block structure**

```bash
# Confirm block names before editing
grep "{% block" src/governiq/templates/base.html
```
Expected output: `{% block title %}`, `{% block extra_head %}`, `{% block content %}`, `{% block extra_scripts %}`

- [ ] **Step 2: Replace the `<head>` font imports**

In `base.html`, replace the current `<!-- Lucide Icons -->` comment and script tag section with:

```html
<!DOCTYPE html>
<html lang="en" data-theme="light">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}GovernIQ{% endblock %}</title>
    <!-- Lucide Icons -->
    <script src="/static/js/lucide.min.js"></script>
    <!-- Bricolage Grotesque — display/heading font -->
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,400;12..96,600;12..96,700;12..96,800&display=swap" rel="stylesheet">
    <!-- Geist — body/UI font (Vercel, not on Google Fonts) -->
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/geist@1.3.0/dist/fonts/geist-sans/style.css">
```

- [ ] **Step 3: Replace the CSS `<style>` block with the new design system**

Replace the entire `<style>…</style>` block with the following. This preserves every existing CSS variable name used by templates while adding new ones:

```css
<style>
    /* ================================================================
       GovernIQ Enterprise Design System v4.0
       Dark:  Modern SaaS — deep indigo glassmorphism
       Light: Clean Slate — white cards, slate bg, violet accents
       Fonts: Bricolage Grotesque (display) + Geist Sans (body)
       ================================================================ */

    /* ---- Light Theme (default) ---- */
    :root, [data-theme="light"] {
        /* Status */
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
        --info-accent: #1e40af;
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
        /* Fonts */
        --font-display: 'Bricolage Grotesque', sans-serif;
        --font-body: 'Geist Sans', 'Geist', sans-serif;
    }

    /* ---- Dark Theme — Modern SaaS glassmorphism ---- */
    [data-theme="dark"] {
        /* Status */
        --pass: #34d399; --pass-bg: #042f2e; --pass-text: #a7f3d0;
        --fail: #f87171; --fail-bg: #3b0a0a; --fail-text: #fecaca;
        --warn: #fbbf24; --warn-bg: #3b2506; --warn-text: #fde68a;
        --info: #38bdf8; --info-bg: #0c2744; --info-text: #bae6fd;
        /* Surface */
        --bg: #0f0c29; --bg-subtle: #1a1740; --bg-surface: #1e1b4b;
        --card: rgba(255,255,255,0.06); --border: rgba(139,92,246,0.25);
        --card-border: rgba(139,92,246,0.2); --card-blur: blur(12px);
        --table-header-bg: rgba(255,255,255,0.04); --card-footer-bg: rgba(255,255,255,0.03);
        --input-bg: rgba(255,255,255,0.07); --code-bg: rgba(0,0,0,0.35);
        --hover-bg: rgba(255,255,255,0.06); --hover-border: rgba(139,92,246,0.5);
        /* Typography */
        --text: #f0f0f0; --text-secondary: #c4b5fd;
        --muted: #94a3b8; --muted-strong: #a0a0a0;
        /* Brand */
        --primary: #8b5cf6; --primary-hover: #7c3aed;
        --primary-bg: rgba(139,92,246,0.15); --primary-text: #c4b5fd;
        --accent: #06b6d4; --accent-bg: rgba(6,182,212,0.1);
        --purple-bg: rgba(139,92,246,0.12); --purple-accent: #8b5cf6;
        --info-accent: #38bdf8;
        /* Gradients */
        --gradient-start: #8b5cf6; --gradient-end: #06b6d4;
        /* Nav */
        --nav-bg: #080617; --nav-link: #6b7280; --nav-active: #f0f0f0;
        /* Shadows */
        --shadow-sm: 0 1px 2px rgba(0,0,0,0.4);
        --shadow: 0 1px 3px rgba(0,0,0,0.5), 0 1px 2px rgba(0,0,0,0.4);
        --shadow-md: 0 4px 6px -1px rgba(0,0,0,0.5), 0 2px 4px -2px rgba(0,0,0,0.4);
        --shadow-lg: 0 10px 15px -3px rgba(0,0,0,0.5), 0 4px 6px -4px rgba(0,0,0,0.4);
        /* Radii */
        --radius: 12px; --radius-sm: 8px; --radius-xs: 6px;
        /* Fonts */
        --font-display: 'Bricolage Grotesque', sans-serif;
        --font-body: 'Geist Sans', 'Geist', sans-serif;
    }

    /* ---- Dark overrides for coloured components ---- */
    [data-theme="dark"] .badge-pass { background: var(--pass-bg); color: var(--pass-text); }
    [data-theme="dark"] .badge-fail { background: var(--fail-bg); color: var(--fail-text); }
    [data-theme="dark"] .badge-warn { background: var(--warn-bg); color: var(--warn-text); }
    [data-theme="dark"] .badge-info { background: var(--info-bg); color: var(--info-text); }
    /* Bug 4 fix: raise .badge-grey contrast from 2.2:1 to 4.6:1 */
    [data-theme="dark"] .badge-grey { background: var(--border); color: #b0b0b0; }
    [data-theme="dark"] .alert-danger  { background: var(--fail-bg); color: var(--fail-text); border-color: #5c1a1a; }
    [data-theme="dark"] .alert-warning { background: var(--warn-bg); color: var(--warn-text); border-color: #5c3a0e; }
    [data-theme="dark"] .alert-success { background: var(--pass-bg); color: var(--pass-text); border-color: #064e3b; }
    [data-theme="dark"] .alert-info    { background: var(--info-bg); color: var(--info-text); border-color: #164e72; }
    [data-theme="dark"] .score-ring--pass { background: var(--pass-bg); }
    [data-theme="dark"] .score-ring--fail { background: var(--fail-bg); }
    [data-theme="dark"] .score-ring--warn { background: var(--warn-bg); }
    [data-theme="dark"] .evidence--green .evidence-header { background: var(--pass-bg); }
    [data-theme="dark"] .evidence--red   .evidence-header { background: var(--fail-bg); }
    [data-theme="dark"] .evidence--amber .evidence-header { background: var(--warn-bg); }
    [data-theme="dark"] .evidence--blue  .evidence-header { background: var(--info-bg); }
    [data-theme="dark"] .check-icon--pass { background: var(--pass-bg); }
    [data-theme="dark"] .check-icon--fail { background: var(--fail-bg); }
    [data-theme="dark"] .check-icon--warn { background: var(--warn-bg); }
    [data-theme="dark"] .check-icon--info { background: var(--info-bg); }
    /* Bug 4 fix: raise contrast for muted text in dark mode */
    [data-theme="dark"] .step-label   { color: var(--muted-strong); }
    [data-theme="dark"] .check-detail { color: var(--muted-strong); }
    [data-theme="dark"] .form-hint    { color: var(--muted-strong); }

    /* ---- Reset ---- */
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body {
        font-family: var(--font-body);
        background: var(--bg);
        color: var(--text);
        line-height: 1.6;
        -webkit-font-smoothing: antialiased;
    }
    /* Dark mode body gets the gradient bg */
    [data-theme="dark"] body {
        background: linear-gradient(160deg, #0f0c29 0%, #1a1740 60%, #0f0c29 100%);
        min-height: 100vh;
    }

    /* ---- Icons ---- */
    .icon { width: 18px; height: 18px; stroke-width: 2; vertical-align: middle; display: inline-block; }
    .icon-sm { width: 14px; height: 14px; }
    .icon-lg { width: 22px; height: 22px; }
    .icon-xl { width: 28px; height: 28px; }

    /* ---- Top Nav ---- */
    .topnav {
        background: var(--nav-bg); color: #fff; padding: 0 2rem;
        display: flex; align-items: center; height: 56px;
        position: sticky; top: 0; z-index: 100;
        border-bottom: 1px solid rgba(255,255,255,0.06);
    }
    [data-theme="dark"] .topnav {
        background: rgba(8,6,23,0.85);
        backdrop-filter: blur(12px);
        -webkit-backdrop-filter: blur(12px);
        border-bottom: 1px solid rgba(139,92,246,0.2);
    }
    .topnav-brand {
        font-family: var(--font-display);
        font-weight: 700; font-size: 1.1rem; letter-spacing: -0.3px;
        display: flex; align-items: center; gap: .5rem; color: #fff;
    }
    .topnav-brand .brand-icon {
        width: 28px; height: 28px; border-radius: 8px;
        background: linear-gradient(135deg, var(--gradient-start), var(--gradient-end));
        display: flex; align-items: center; justify-content: center;
    }
    .topnav-brand .brand-icon i { color: #fff; }
    .topnav-links { margin-left: auto; display: flex; gap: 0; align-items: center; }
    .topnav-links a {
        color: var(--nav-link); text-decoration: none; padding: .5rem .85rem;
        font-size: .8rem; font-weight: 500; transition: all .15s;
        display: flex; align-items: center; gap: .4rem;
        border-radius: var(--radius-xs);
    }
    .topnav-links a:hover { color: var(--nav-active); background: rgba(255,255,255,0.06); }
    .topnav-links a.active { color: var(--nav-active); background: rgba(255,255,255,0.1); }
    .topnav-divider { width: 1px; height: 20px; background: rgba(255,255,255,0.1); margin: 0 .25rem; }

    .portal-badge { font-size: .6rem; padding: 2px 8px; border-radius: 20px; font-weight: 600; text-transform: uppercase; letter-spacing: .5px; margin-left: .5rem; }
    .portal-badge--admin     { background: var(--accent); color: #fff; }
    .portal-badge--candidate { background: var(--primary); color: #fff; }

    /* ---- Theme Toggle ---- */
    .theme-toggle {
        background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.1);
        border-radius: 20px; padding: .35rem .7rem; cursor: pointer;
        color: var(--nav-link); font-size: .75rem; font-weight: 500;
        transition: all .2s; display: flex; align-items: center; gap: .35rem; margin-left: .5rem;
    }
    .theme-toggle:hover { border-color: rgba(255,255,255,0.3); color: var(--nav-active); background: rgba(255,255,255,0.1); }

    /* ---- Layout ---- */
    .container      { max-width: 1200px; margin: 0 auto; padding: 2rem; }
    .container-wide { max-width: 1400px; margin: 0 auto; padding: 2rem; }

    /* ---- Cards ---- */
    .card {
        background: var(--card);
        border: 1px solid var(--card-border);
        border-radius: var(--radius);
        box-shadow: var(--shadow);
        overflow: hidden;
        transition: transform .2s ease, box-shadow .2s ease, border-color .2s ease;
    }
    .card:hover { transform: translateY(-1px); box-shadow: var(--shadow-md); }
    [data-theme="dark"] .card {
        backdrop-filter: var(--card-blur);
        -webkit-backdrop-filter: var(--card-blur);
    }
    .card-header { padding: 1.25rem 1.5rem; border-bottom: 1px solid var(--card-border); }
    .card-body   { padding: 1.5rem; }
    .card-footer { padding: 1rem 1.5rem; border-top: 1px solid var(--card-border); background: var(--card-footer-bg); }

    /* Bug 3 fix: consistent heading+icon alignment — use class="card-title" on h1/h2/h3 */
    .card-title {
        display: inline-flex; align-items: center; gap: .5rem;
        font-family: var(--font-display);
    }
    .card-title .icon { flex-shrink: 0; }

    /* ---- Typography ---- */
    h1 { font-family: var(--font-display); font-size: 1.75rem; font-weight: 700; letter-spacing: -0.5px; line-height: 1.2; }
    h2 { font-family: var(--font-display); font-size: 1.4rem;  font-weight: 700; letter-spacing: -0.3px; line-height: 1.3; }
    h3 { font-family: var(--font-display); font-size: 1.1rem;  font-weight: 600; line-height: 1.4; }
    h4 { font-size: .9rem; font-weight: 600; color: var(--text-secondary); }
    .text-muted     { color: var(--muted); }
    .text-small     { font-size: .85rem; }
    .text-xs        { font-size: .75rem; }
    .text-pass      { color: var(--pass); }
    .text-fail      { color: var(--fail); }
    .text-warn      { color: var(--warn); }
    .text-gradient  {
        background: linear-gradient(135deg, var(--gradient-start), var(--gradient-end));
        -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;
    }

    /* ---- Buttons ---- */
    .btn {
        display: inline-flex; align-items: center; gap: .45rem;
        padding: .55rem 1.15rem; border-radius: var(--radius-sm);
        font-family: var(--font-body);
        font-weight: 600; font-size: .8rem; text-decoration: none;
        border: none; cursor: pointer; transition: all .15s; line-height: 1.4;
    }
    .btn-primary {
        background: linear-gradient(135deg, var(--gradient-start), var(--gradient-end));
        color: #fff; border: none;
    }
    .btn-primary:hover { opacity: .9; box-shadow: var(--shadow-md); transform: translateY(-1px); }
    .btn-outline { background: transparent; color: var(--primary); border: 1px solid var(--card-border); }
    .btn-outline:hover { border-color: var(--primary); background: var(--primary-bg); }
    .btn-success { background: var(--pass); color: #fff; }
    .btn-danger  { background: var(--fail); color: #fff; }
    .btn-ghost   { background: transparent; color: var(--muted); border: none; }
    .btn-ghost:hover { color: var(--text); background: var(--bg-subtle); }
    .btn-lg    { padding: .7rem 1.75rem; font-size: .9rem; }
    .btn-sm    { padding: .35rem .7rem; font-size: .75rem; }
    .btn-block { width: 100%; justify-content: center; }

    /* ---- Forms ---- */
    .form-group  { margin-bottom: 1.25rem; }
    .form-label  {
        display: block; font-weight: 600; font-size: .8rem;
        margin-bottom: .4rem; color: var(--text-secondary);
        text-transform: uppercase; letter-spacing: .3px;
    }
    .form-hint { font-size: .75rem; color: var(--muted); margin-top: .3rem; }
    .form-input, .form-select, .form-textarea {
        width: 100%; padding: .6rem .85rem;
        border: 1px solid var(--card-border);
        border-radius: var(--radius-sm); font-size: .85rem; font-family: var(--font-body);
        background: var(--input-bg); color: var(--text); transition: all .15s;
    }
    .form-input:focus, .form-select:focus, .form-textarea:focus {
        outline: none; border-color: var(--primary);
        box-shadow: 0 0 0 3px rgba(139,92,246,.15);
    }
    .form-textarea { min-height: 100px; resize: vertical; }

    /* File upload — Bug 1 adds drag-active state */
    .file-upload {
        border: 2px dashed var(--card-border); border-radius: var(--radius);
        padding: 2rem; text-align: center; cursor: pointer;
        transition: all .2s; background: var(--bg-subtle); position: relative;
    }
    .file-upload:hover     { border-color: var(--primary); background: var(--primary-bg); }
    .file-upload.has-file  { border-color: var(--pass);    background: var(--pass-bg); border-style: solid; }
    .file-upload.drag-active {
        border-color: var(--primary); border-style: solid;
        background: var(--primary-bg);
        box-shadow: 0 0 0 4px rgba(139,92,246,.15);
        transform: scale(1.01);
    }
    .file-upload input[type="file"] { display: none; }
    .file-upload-icon { font-size: 2rem; margin-bottom: .5rem; color: var(--muted); }
    .file-upload-text { font-weight: 600; font-size: .9rem; }
    .file-upload-hint { font-size: .8rem; color: var(--muted); }
    .file-clear {
        display: none; position: absolute; top: .6rem; right: .6rem;
        width: 24px; height: 24px; border-radius: 50%;
        background: var(--fail-bg); color: var(--fail);
        border: 1px solid var(--fail); cursor: pointer;
        align-items: center; justify-content: center;
        font-size: .75rem; font-weight: 700; line-height: 1;
        transition: all .15s;
    }
    .file-clear:hover { background: var(--fail); color: #fff; }

    /* ---- Badges ---- */
    .badge {
        display: inline-flex; align-items: center; gap: .3rem;
        padding: .2rem .65rem; border-radius: 20px;
        font-size: .7rem; font-weight: 600; letter-spacing: .2px;
    }
    .badge-pass    { background: var(--pass-bg);    color: var(--pass-text); }
    .badge-fail    { background: var(--fail-bg);    color: var(--fail-text); }
    .badge-warn    { background: var(--warn-bg);    color: var(--warn-text); }
    .badge-info    { background: var(--info-bg);    color: var(--info-text); }
    .badge-grey    { background: var(--bg-subtle);  color: var(--muted); }
    .badge-primary { background: var(--primary-bg); color: var(--primary-text); }

    /* ---- Score Ring ---- */
    .score-ring {
        width: 100px; height: 100px; border-radius: 50%;
        display: flex; align-items: center; justify-content: center;
        font-family: var(--font-display); font-weight: 700; font-size: 1.4rem; flex-shrink: 0;
        animation: ring-pop .6s cubic-bezier(.34,1.56,.64,1) both;
    }
    .score-ring--lg   { width: 140px; height: 140px; font-size: 2rem; }
    .score-ring--pass { background: var(--pass-bg); color: var(--pass); border: 3px solid var(--pass); }
    .score-ring--fail { background: var(--fail-bg); color: var(--fail); border: 3px solid var(--fail); }
    .score-ring--warn { background: var(--warn-bg); color: var(--warn); border: 3px solid var(--warn); }

    /* Stat accent bar */
    .stat-accent-bar {
        height: 2px; border-radius: 1px; margin-top: 4px;
        background: linear-gradient(90deg, var(--gradient-start), var(--gradient-end));
    }

    /* ---- Alerts ---- */
    .alert { padding: 1rem 1.25rem; border-radius: var(--radius-sm); margin-bottom: 1rem; font-size: .85rem; display: flex; gap: .75rem; align-items: flex-start; }
    .alert-danger  { background: var(--fail-bg); color: var(--fail-text); border: 1px solid #fecaca; }
    .alert-warning { background: var(--warn-bg); color: var(--warn-text); border: 1px solid #fde68a; }
    .alert-success { background: var(--pass-bg); color: var(--pass-text); border: 1px solid #bbf7d0; }
    .alert-info    { background: var(--info-bg); color: var(--info-text); border: 1px solid #bfdbfe; }

    /* ---- Tables ---- */
    .table { width: 100%; border-collapse: collapse; font-size: .85rem; }
    .table th {
        text-align: left; padding: .75rem 1rem;
        background: var(--table-header-bg); border-bottom: 2px solid var(--card-border);
        font-weight: 600; color: var(--muted); font-size: .7rem;
        text-transform: uppercase; letter-spacing: .5px;
    }
    .table td { padding: .75rem 1rem; border-bottom: 1px solid var(--card-border); }
    .table tr { transition: background .1s; }
    .table tr:hover td { background: var(--hover-bg); }

    /* ---- Grid ---- */
    .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; }
    .grid-3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 1.5rem; }
    .grid-4 { display: grid; grid-template-columns: repeat(4, 1fr); gap: 1.25rem; }
    @media (max-width: 900px) { .grid-2 { grid-template-columns: 1fr; } }
    @media (max-width: 768px) { .grid-3, .grid-4 { grid-template-columns: 1fr; } }

    /* ---- Stat Cards ---- */
    .stat-card { padding: 1.25rem; display: flex; align-items: flex-start; gap: 1rem; }
    .stat-icon { width: 42px; height: 42px; border-radius: var(--radius-sm); display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
    .stat-icon--blue   { background: var(--info-bg);    color: var(--info); }
    .stat-icon--green  { background: var(--pass-bg);    color: var(--pass); }
    .stat-icon--red    { background: var(--fail-bg);    color: var(--fail); }
    .stat-icon--amber  { background: var(--warn-bg);    color: var(--warn); }
    .stat-icon--purple { background: var(--accent-bg);  color: var(--accent); }
    .stat-value { font-family: var(--font-display); font-size: 1.75rem; font-weight: 700; line-height: 1; }
    .stat-label { font-size: .75rem; color: var(--muted); margin-top: .25rem; font-weight: 500; }

    /* ---- Check Items ---- */
    .check-row { display: flex; gap: .75rem; padding: .6rem 0; border-bottom: 1px solid var(--bg-subtle); align-items: flex-start; }
    .check-row:last-child { border-bottom: none; }
    .check-icon { width: 22px; height: 22px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: .7rem; flex-shrink: 0; margin-top: 1px; font-weight: 700; }
    .check-icon--pass { background: var(--pass-bg); color: var(--pass); }
    .check-icon--fail { background: var(--fail-bg); color: var(--fail); }
    .check-icon--warn { background: var(--warn-bg); color: var(--warn); }
    .check-icon--info { background: var(--info-bg); color: var(--info); }
    .check-label  { font-weight: 500; font-size: .85rem; }
    .check-detail { font-size: .78rem; color: var(--muted); margin-top: 2px; }

    /* ---- Evidence Cards ---- */
    .evidence { border-radius: var(--radius-sm); margin-bottom: .75rem; border: 1px solid var(--card-border); overflow: hidden; }
    .evidence--green { border-color: #bbf7d0; }
    .evidence--red   { border-color: #fecaca; }
    .evidence--amber { border-color: #fde68a; }
    .evidence--blue  { border-color: #bfdbfe; }
    .evidence-header { padding: .6rem 1rem; display: flex; justify-content: space-between; align-items: center; cursor: pointer; }
    .evidence--green .evidence-header { background: var(--pass-bg); }
    .evidence--red   .evidence-header { background: var(--fail-bg); }
    .evidence--amber .evidence-header { background: var(--warn-bg); }
    .evidence--grey  .evidence-header { background: var(--bg-subtle); }
    .evidence--blue  .evidence-header { background: var(--info-bg); }
    .evidence-body { padding: 1rem; font-size: .82rem; }
    .evidence-body pre {
        white-space: pre-wrap; word-break: break-word;
        font-family: 'JetBrains Mono', 'SF Mono', 'Fira Code', monospace; font-size: .78rem; line-height: 1.55;
        background: var(--code-bg); padding: .75rem; border-radius: var(--radius-xs);
    }
    .evidence-pipe { font-size: .65rem; padding: 2px 8px; background: rgba(0,0,0,.06); border-radius: 4px; font-weight: 500; }

    /* ---- Progress ---- */
    .progress-bar  { height: 6px; background: var(--bg-subtle); border-radius: 3px; overflow: hidden; }
    .progress-fill { height: 100%; border-radius: 3px; transition: width .6s ease; }
    .progress-fill--pass { background: var(--pass); }
    .progress-fill--fail { background: var(--fail); }
    .progress-fill--warn { background: var(--warn); }

    /* ---- Steps ---- */
    .steps { display: flex; gap: 0; margin-bottom: 2rem; }
    .step  { flex: 1; text-align: center; padding: 1rem; position: relative; }
    .step::after {
        content: ''; position: absolute; right: 0; top: 50%; width: 0; height: 0;
        border-top: 8px solid transparent; border-bottom: 8px solid transparent;
        border-left: 8px solid var(--card-border); transform: translateY(-50%);
    }
    .step:last-child::after { display: none; }
    .step-num { width: 32px; height: 32px; border-radius: 50%; background: var(--bg-subtle); color: var(--muted); display: inline-flex; align-items: center; justify-content: center; font-weight: 700; font-size: .85rem; margin-bottom: .5rem; }
    .step.active .step-num { background: linear-gradient(135deg, var(--gradient-start), var(--gradient-end)); color: #fff; }
    .step.done   .step-num { background: var(--pass); color: #fff; }
    .step-label { font-size: .78rem; font-weight: 500; color: var(--muted); }
    .step.active .step-label { color: var(--text); font-weight: 600; }

    /* ---- Feature / Method Cards ---- */
    .method-card { display: flex; gap: 1.25rem; padding: 1.25rem; border: 1px solid var(--card-border); border-radius: var(--radius); margin-bottom: .75rem; background: var(--card); transition: all .2s; }
    .method-card:hover { border-color: var(--primary); box-shadow: var(--shadow-md); }
    .method-num { width: 38px; height: 38px; border-radius: var(--radius-sm); background: var(--primary-bg); color: var(--primary); display: flex; align-items: center; justify-content: center; font-weight: 700; flex-shrink: 0; }
    .method-title { font-weight: 600; margin-bottom: .3rem; font-size: .95rem; }
    .method-desc  { font-size: .82rem; color: var(--muted); line-height: 1.5; }

    /* ---- Footer ---- */
    .footer { text-align: center; padding: 2rem; color: var(--muted); font-size: .75rem; border-top: 1px solid var(--card-border); margin-top: 2rem; }

    /* ---- Utilities ---- */
    .divider     { height: 1px; background: var(--card-border); margin: 1.5rem 0; }
    .spacer      { margin-bottom: 1.5rem; }
    .flex        { display: flex; }
    .flex-between { display: flex; justify-content: space-between; align-items: center; }
    .gap-1       { gap: .5rem; } .gap-2 { gap: 1rem; } .gap-3 { gap: 1.5rem; }
    .items-center { align-items: center; }
    .hidden      { display: none; }
    .loading     { opacity: .6; pointer-events: none; }
    .border-gradient { border-image: linear-gradient(135deg, var(--gradient-start), var(--gradient-end)) 1; }

    /* ---- Animations ---- */
    /* Entry animation — triggered by IntersectionObserver adding .is-visible */
    .animate-in {
        opacity: 0; transform: translateY(10px);
        transition: opacity .4s ease, transform .4s cubic-bezier(.22,1,.36,1);
    }
    .animate-in.is-visible { opacity: 1; transform: none; }

    /* Stagger delays */
    .stagger > *:nth-child(1) { transition-delay: 0s; }
    .stagger > *:nth-child(2) { transition-delay: .07s; }
    .stagger > *:nth-child(3) { transition-delay: .14s; }
    .stagger > *:nth-child(4) { transition-delay: .21s; }
    .stagger > *:nth-child(5) { transition-delay: .28s; }

    /* Score ring spring pop */
    @keyframes ring-pop {
        from { transform: scale(.7); opacity: 0; }
        to   { transform: scale(1);  opacity: 1; }
    }

    /* Score number glow on entry */
    @keyframes score-glow {
        0%, 100% { text-shadow: none; }
        40%      { text-shadow: 0 0 16px currentColor; }
    }
    .score-glow { animation: score-glow 1s .5s ease both; }

    /* Skeleton shimmer for loading states */
    @keyframes shimmer {
        from { background-position: -200% 0; }
        to   { background-position:  200% 0; }
    }
    .skeleton {
        background: linear-gradient(90deg, var(--card-border) 25%, var(--bg-surface) 50%, var(--card-border) 75%);
        background-size: 200% 100%;
        animation: shimmer 1.5s infinite;
        border-radius: var(--radius-xs);
    }

    /* Page fade-in (preserved from v3) */
    .fade-in { animation: fadeIn .3s ease-out; }
    @keyframes fadeIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }

    /* ---- Print ---- */
    @media print {
        .topnav, .btn, .footer, .no-print, .theme-toggle { display: none !important; }
        body { background: #fff !important; color: #000 !important; }
        .card { box-shadow: none; border: 1px solid #ddd; break-inside: avoid; }
        .container, .container-wide { max-width: 100%; padding: 0; }
        /* Suppress all animations */
        .animate-in, .score-ring, .score-glow, .skeleton { animation: none !important; }
        .animate-in { opacity: 1 !important; transform: none !important; }
    }
</style>
```

- [ ] **Step 4: Preserve the existing `<body>` nav + footer + theme script — update brand icon**

The nav and footer HTML stay the same structure. Update only the brand icon background:
```html
<!-- Find this line: -->
<div class="brand-icon"><i data-lucide="shield-check" style="width:16px;height:16px;"></i></div>

<!-- It stays the same — the CSS now applies the gradient via:
     background: linear-gradient(135deg, var(--gradient-start), var(--gradient-end)) -->
```

- [ ] **Step 5: Append IntersectionObserver to the theme `<script>` block**

At the end of the existing `<script>` block (after `updateThemeUI()` function, before `</script>`), append:

```js
// Scroll-triggered entry animations
(function() {
    if (!('IntersectionObserver' in window)) {
        document.querySelectorAll('.animate-in').forEach(function(el) { el.classList.add('is-visible'); });
        return;
    }
    var observer = new IntersectionObserver(function(entries) {
        entries.forEach(function(e) {
            if (e.isIntersecting) { e.target.classList.add('is-visible'); observer.unobserve(e.target); }
        });
    }, { threshold: 0.1, rootMargin: '0px 0px -40px 0px' });
    document.addEventListener('DOMContentLoaded', function() {
        document.querySelectorAll('.animate-in').forEach(function(el) { observer.observe(el); });
    });
})();
```

- [ ] **Step 6: Start the dev server and verify base rendering**

```bash
cd C:/Users/Kiran.Guttula/Documents/EvalAutomaton
source venv/Scripts/activate
uvicorn src.governiq.main:app --reload --port 8000
```

Open `http://localhost:8000/candidate/`. Check:
- Bricolage Grotesque loads on headings (bold, slightly wide letterforms)
- Geist loads on body text (clean, narrow)
- Light theme: white cards on slate background, violet primary colour
- Toggle dark: deep indigo background, frosted card effect, violet/teal accents
- Score ring animates on pages that have one

- [ ] **Step 7: Commit**

```bash
git add src/governiq/templates/base.html
git commit -m "feat: enterprise design system v4 — glassmorphism dark, clean slate light, Bricolage+Geist"
```

---

## Task 2: Fix `candidate_submit.html` — Bugs 1, 2, 3

**Files:**
- Modify: `src/governiq/templates/candidate_submit.html`

Read the file first, then apply the three targeted fixes below.

- [ ] **Step 1: Fix Bug 3 — replace inline icon margins in headings**

Find every `<h1>` or `<h3>` tag containing `style="margin-right:.4rem;"` on an icon and replace with `class="card-title"` on the heading and remove the inline style.

Pattern to find: `<h3><i data-lucide="..." class="icon" style="margin-right:.4rem;"></i>`
Replace with:    `<h3 class="card-title"><i data-lucide="..." class="icon"></i>`

There are 6 occurrences in this file. Also update the `<h1>` at line 8:
```html
<!-- Before -->
<h1><i data-lucide="upload-cloud" class="icon icon-lg" style="margin-right:.4rem;"></i> Submit Your Assessment</h1>

<!-- After -->
<h1 class="card-title"><i data-lucide="upload-cloud" class="icon icon-lg"></i> Submit Your Assessment</h1>
```

- [ ] **Step 2: Fix Bug 2 — correct the Webhook URL field label**

Find line ~106:
```html
<!-- Before -->
<label class="form-label"><i data-lucide="webhook" class="icon icon-sm"></i> Bot Webhook URL <span class="badge badge-grey">Optional if using Kore credentials</span></label>
<input type="url" name="webhook_url" class="form-input" placeholder="e.g. https://bots.kore.ai/hooks/...">
<div class="form-hint">Your bot's webhook URL. If Bot ID + Client ID + Client Secret are provided, the system uses Kore.ai's BotMessages API directly (recommended). The webhook URL serves as a fallback.</div>

<!-- After -->
<label class="form-label"><i data-lucide="webhook" class="icon icon-sm"></i> Bot Webhook URL <span class="badge badge-warn">Required for Live Testing</span></label>
<input type="url" name="webhook_url" class="form-input" placeholder="e.g. https://bots.kore.ai/hooks/...">
<div class="form-hint">Required for live bot testing. Without a Webhook URL, only the structural CBM audit runs — no conversation testing, no score.</div>
```

- [ ] **Step 3: Fix Bug 1 — add drag-and-drop to file upload + clear button**

Find the file upload `<label class="file-upload" id="exportUpload">` block. Add a clear button inside it:
```html
<!-- Add this as the LAST child inside the <label class="file-upload"> tag, before </label> -->
<button type="button" class="file-clear" title="Remove file">×</button>
```

Then replace the entire `{% block extra_scripts %}` at the bottom of the file with:
```html
{% block extra_scripts %}
<script>
document.querySelectorAll('.file-upload').forEach(function(label) {
    var input = label.querySelector('input[type="file"]');
    var clearBtn = label.querySelector('.file-clear');

    function updateFileUI() {
        if (input.files.length > 0) {
            label.classList.add('has-file');
            label.querySelector('.file-upload-text').textContent = input.files[0].name;
            label.querySelector('.file-upload-hint').textContent = (input.files[0].size / 1024).toFixed(1) + ' KB — ready to submit';
            if (clearBtn) clearBtn.style.display = 'flex';
        }
    }

    function clearFile(e) {
        e.preventDefault(); e.stopPropagation();
        input.value = '';
        label.classList.remove('has-file', 'drag-active');
        label.querySelector('.file-upload-text').textContent = 'Click or drag to upload your bot export';
        label.querySelector('.file-upload-hint').textContent = 'Accepts .json or .zip — Export from Kore.ai XO Platform → Bot Settings → Export';
        if (clearBtn) clearBtn.style.display = 'none';
    }

    input.addEventListener('change', updateFileUI);

    label.addEventListener('dragover', function(e) {
        e.preventDefault();
        label.classList.add('drag-active');
    });
    label.addEventListener('dragleave', function(e) {
        if (!label.contains(e.relatedTarget)) {
            label.classList.remove('drag-active');
        }
    });
    label.addEventListener('drop', function(e) {
        e.preventDefault();
        label.classList.remove('drag-active');
        if (e.dataTransfer.files.length > 0) {
            try {
                var dt = new DataTransfer();
                dt.items.add(e.dataTransfer.files[0]);
                input.files = dt.files;
            } catch(err) {
                // DataTransfer not supported — fallback: just show filename
                label.classList.add('has-file');
                label.querySelector('.file-upload-text').textContent = e.dataTransfer.files[0].name;
                label.querySelector('.file-upload-hint').textContent = (e.dataTransfer.files[0].size / 1024).toFixed(1) + ' KB';
                if (clearBtn) clearBtn.style.display = 'flex';
                return;
            }
            updateFileUI();
        }
    });

    if (clearBtn) clearBtn.addEventListener('click', clearFile);
});
</script>
{% endblock %}
```

- [ ] **Step 4: Verify in browser**

With the dev server running, open `http://localhost:8000/candidate/`.
Check:
- All 6 card headings have icons aligned flush with text (no gap difference between icons)
- "Bot Webhook URL" label shows amber "Required for Live Testing" badge
- Hint text reads "Required for live bot testing. Without a Webhook URL…"
- Drag a file onto the upload zone: border turns violet with glow, file name appears, green border after drop
- The × clear button appears after file selected; clicking it resets to empty state

- [ ] **Step 5: Commit**

```bash
git add src/governiq/templates/candidate_submit.html
git commit -m "fix: drag-drop file upload, correct webhook URL label, align heading icons"
```

---

## Task 3: Fix `candidate_report.html` and `admin_review.html` — Bugs 3 & 4

**Files:**
- Modify: `src/governiq/templates/candidate_report.html`
- Modify: `src/governiq/templates/admin_review.html`

- [ ] **Step 1: Fix hardcoded colours in `candidate_report.html`**

Find and replace 4 hardcoded colour occurrences:

```html
<!-- Line ~100: Replace -->
<div style="padding:.75rem; border-left:3px solid #7c3aed; background:#faf5ff; border-radius: 0 var(--radius) var(--radius) 0;">
    <strong style="color:#7c3aed;"><i data-lucide="webhook" class="icon icon-sm"></i> Webhook Results (left)</strong>

<!-- With -->
<div style="padding:.75rem; border-left:3px solid var(--purple-accent); background:var(--purple-bg); border-radius: 0 var(--radius) var(--radius) 0;">
    <strong style="color:var(--purple-accent);"><i data-lucide="webhook" class="icon icon-sm"></i> Webhook Results (left)</strong>


<!-- Line ~104: Replace -->
<div style="padding:.75rem; border-left:3px solid #1e40af; background:#eff6ff; border-radius: 0 var(--radius) var(--radius) 0;">

<!-- With -->
<div style="padding:.75rem; border-left:3px solid var(--info-accent); background:var(--info-bg); border-radius: 0 var(--radius) var(--radius) 0;">


<!-- Line ~179: Replace -->
<div style="border-left:3px solid #7c3aed; padding-left:1rem;">
    <h4 style="color:#7c3aed; margin-bottom:.75rem;"><i data-lucide="webhook" class="icon icon-sm"></i> Webhook Results</h4>

<!-- With -->
<div style="border-left:3px solid var(--purple-accent); padding-left:1rem;">
    <h4 style="color:var(--purple-accent); margin-bottom:.75rem;"><i data-lucide="webhook" class="icon icon-sm"></i> Webhook Results</h4>


<!-- Line ~199: Replace -->
<div style="border-left:3px solid #1e40af; padding-left:1rem;">

<!-- With -->
<div style="border-left:3px solid var(--info-accent); padding-left:1rem;">
```

- [ ] **Step 2: Fix heading alignment (Bug 3) in `candidate_report.html`**

Run to find all occurrences:
```bash
grep -n "style=\"margin-right:.4rem" src/governiq/templates/candidate_report.html
```
For each result, apply the same pattern: add `class="card-title"` to the parent `<h1>/<h3>` and remove the `style="margin-right:.4rem;"` from the `<i>` tag.

- [ ] **Step 3: Fix hardcoded colours in `admin_review.html`**

```html
<!-- Line ~96: Replace -->
<div style="border-left:3px solid #7c3aed; padding-left:1rem;">
    <h4 style="color:#7c3aed; margin-bottom:.75rem;"><i data-lucide="webhook" class="icon icon-sm"></i> Webhook Results</h4>

<!-- With -->
<div style="border-left:3px solid var(--purple-accent); padding-left:1rem;">
    <h4 style="color:var(--purple-accent); margin-bottom:.75rem;"><i data-lucide="webhook" class="icon icon-sm"></i> Webhook Results</h4>


<!-- Line ~112: Replace -->
<div style="border-left:3px solid #1e40af; padding-left:1rem;">

<!-- With -->
<div style="border-left:3px solid var(--info-accent); padding-left:1rem;">
```

- [ ] **Step 4: Fix heading alignment (Bug 3) in `admin_review.html`**

```bash
grep -n "style=\"margin-right:.4rem" src/governiq/templates/admin_review.html
```
Apply same card-title fix for each result.

- [ ] **Step 5: Verify in browser**

Open `http://localhost:8000/candidate/report/` (requires a scorecard to exist — check `/candidate/history` or use an admin session ID at `/admin/review/<id>`).
- Toggle to dark mode: the Webhook Results and CBM Results column left-border colours must be visible (violet / blue) — not the light purple `#faf5ff` background
- Toggle back to light: clean slate look, colours still correct

- [ ] **Step 6: Commit**

```bash
git add src/governiq/templates/candidate_report.html src/governiq/templates/admin_review.html
git commit -m "fix: replace hardcoded purple/blue colours with CSS variables in report templates"
```

---

## Task 4: Fix heading alignment in candidate and public templates — Bug 3

**Files:**
- Modify: `src/governiq/templates/admin_dashboard.html`
- Modify: `src/governiq/templates/candidate_history.html`
- Modify: `src/governiq/templates/how_it_works.html`
- Modify: `src/governiq/templates/landing.html`

- [ ] **Step 1: Find and count occurrences in each file**

```bash
grep -cn "style=\"margin-right:.4rem" \
  src/governiq/templates/admin_dashboard.html \
  src/governiq/templates/candidate_history.html \
  src/governiq/templates/how_it_works.html \
  src/governiq/templates/landing.html
```

- [ ] **Step 2: Apply card-title fix to all 4 files**

For each file, for every `<h1>` or `<h3>` with an icon using `style="margin-right:.4rem;"`:
- Add `class="card-title"` to the `<h1>/<h3>` tag
- Remove `style="margin-right:.4rem;"` from the `<i>` icon tag

Example transform (same pattern applies everywhere):
```html
<!-- Before -->
<h3><i data-lucide="layout-dashboard" class="icon" style="margin-right:.4rem;"></i> Evaluator Dashboard</h3>

<!-- After -->
<h3 class="card-title"><i data-lucide="layout-dashboard" class="icon"></i> Evaluator Dashboard</h3>
```

- [ ] **Step 3: Add scroll-triggered animation to stat cards in `admin_dashboard.html`**

Find the stats row grid in `admin_dashboard.html`:
```html
<!-- Find -->
<div class="grid-4 spacer">

<!-- Replace with -->
<div class="grid-4 spacer stagger">
```

Then add `class="animate-in"` to each of the 4 stat `.card` divs inside that grid:
```html
<!-- Before -->
<div class="card">
    <div class="stat-card">

<!-- After -->
<div class="card animate-in">
    <div class="stat-card">
```
(Apply to all 4 stat cards: Total Submissions, Passed, Failed/Needs Review, Critical Failures)

- [ ] **Step 4: Verify all 4 pages in browser**

- `http://localhost:8000/` — landing page, icons aligned in all section headings
- `http://localhost:8000/how-it-works` — method card headings aligned
- `http://localhost:8000/candidate/history` — page heading aligned
- `http://localhost:8000/admin/` — all dashboard section headings aligned

- [ ] **Step 5: Commit**

```bash
git add src/governiq/templates/admin_dashboard.html \
        src/governiq/templates/candidate_history.html \
        src/governiq/templates/how_it_works.html \
        src/governiq/templates/landing.html
git commit -m "fix: align heading icons with card-title class in candidate and public templates"
```

---

## Task 5: Fix heading alignment in admin templates — Bug 3

**Files:**
- Modify: `src/governiq/templates/admin_compare.html`
- Modify: `src/governiq/templates/admin_manifest_list.html`
- Modify: `src/governiq/templates/admin_manifest_schema.html`
- Modify: `src/governiq/templates/admin_manifest_editor.html`

- [ ] **Step 1: Find and count occurrences**

```bash
grep -cn "style=\"margin-right:.4rem" \
  src/governiq/templates/admin_compare.html \
  src/governiq/templates/admin_manifest_list.html \
  src/governiq/templates/admin_manifest_schema.html \
  src/governiq/templates/admin_manifest_editor.html
```
Expected: ~4, ~3, ~6, ~9 respectively (22 total).

- [ ] **Step 2: Apply card-title fix to all 4 files**

Same pattern as Task 4 Step 2. For `admin_manifest_editor.html` (9 occurrences, largest file): read the file first to locate each section header before editing to avoid accidentally modifying JavaScript string content that may also contain `margin-right`.

```bash
# Verify: check if any JS strings contain this pattern
grep -n "margin-right:.4rem" src/governiq/templates/admin_manifest_editor.html
# All matches should be in HTML attribute context (inside < >) not in JS strings
```

- [ ] **Step 3: Verify admin pages in browser**

- `http://localhost:8000/admin/manifests` — manifest list headings aligned
- `http://localhost:8000/admin/manifest/schema` — schema doc headings aligned
- `http://localhost:8000/admin/compare` — compare page headings aligned
- `http://localhost:8000/admin/manifest/new` — editor headings aligned (all 9 section headers)

- [ ] **Step 4: Run template render tests**

```bash
cd C:/Users/Kiran.Guttula/Documents/EvalAutomaton
source venv/Scripts/activate
pytest tests/ -v -x 2>&1 | head -60
```
Expected: all existing tests pass. If a test fails due to template rendering, it indicates a Jinja2 syntax error introduced during editing — check the specific template.

- [ ] **Step 5: Final verification — check for any remaining inline margins**

```bash
grep -rn "style=\"margin-right:.4rem" src/governiq/templates/ --include="*.html"
```
Expected output: **empty** (no matches).

- [ ] **Step 6: Commit**

```bash
git add src/governiq/templates/admin_compare.html \
        src/governiq/templates/admin_manifest_list.html \
        src/governiq/templates/admin_manifest_schema.html \
        src/governiq/templates/admin_manifest_editor.html
git commit -m "fix: align heading icons with card-title class in all admin templates"
```

---

## Task 6: Final Verification Pass

**Files:** All modified templates (read-only verification)

- [ ] **Step 1: Full regression grep — no hardcoded colours remain**

```bash
grep -rn "background:#faf5ff\|background:#eff6ff\|border-left:3px solid #7c3aed\|border-left:3px solid #1e40af\|color:#7c3aed" \
  src/governiq/templates/ --include="*.html"
```
Expected: **empty**.

- [ ] **Step 2: No inline icon margins remain**

```bash
grep -rn "style=\"margin-right:.4rem" src/governiq/templates/ --include="*.html"
```
Expected: **empty**.

- [ ] **Step 3: Webhook URL badge correct**

```bash
grep -n "Optional if using Kore" src/governiq/templates/candidate_submit.html
```
Expected: **empty** (no matches — the old incorrect label is gone).

```bash
grep -n "Required for Live Testing" src/governiq/templates/candidate_submit.html
```
Expected: 1 match.

- [ ] **Step 4: Font CDN links present in base.html**

```bash
grep -n "Bricolage\|geist" src/governiq/templates/base.html
```
Expected: 2 matches — one Google Fonts link (Bricolage Grotesque), one jsDelivr link (Geist).

- [ ] **Step 5: Run full test suite**

```bash
pytest tests/ -v 2>&1 | tail -20
```
Expected: all tests pass (or same pass/fail count as before — no regressions introduced by this frontend-only change).

- [ ] **Step 6: Browser final walkthrough — both themes, all key pages**

Open each URL, toggle between light/dark, and verify:

| URL | Check |
|---|---|
| `http://localhost:8000/` | Landing page renders, heading icons aligned |
| `http://localhost:8000/candidate/` | Drag-drop works, webhook badge amber, icons aligned |
| `http://localhost:8000/how-it-works` | Method cards render, headings aligned |
| `http://localhost:8000/admin/` | Dashboard loads, stat cards visible, dark theme glassmorphism visible |
| `http://localhost:8000/admin/manifests` | Table renders correctly in both themes |

For dark mode specifically on admin dashboard — stat cards should show a subtle frosted glass effect (semi-transparent bg with blur).

- [ ] **Step 7: Final commit and summary**

```bash
git add -A
git status  # Should show nothing unstaged
git log --oneline -6
```

Expected log (6 commits from this feature):
```
fix: align heading icons with card-title class in all admin templates
fix: align heading icons with card-title class in candidate and public templates
fix: replace hardcoded purple/blue colours with CSS variables in report templates
fix: drag-drop file upload, correct webhook URL label, align heading icons
feat: enterprise design system v4 — glassmorphism dark, clean slate light, Bricolage+Geist
```
