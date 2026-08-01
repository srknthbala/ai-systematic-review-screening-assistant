# AI Systematic Review Screening Assistant

---

```diff
- SECOND CHECK ONLY. NOT A STANDALONE SCREENING PROCEDURE.
- Screen your records yourself first, then run this and compare.
```

> [!CAUTION]
> **This tool should be used as a SECOND CHECK on INDIVIDUAL screening you have
> already done yourself. It should NOT be a standalone screening procedure.**
>
> Every major reporting standard expects screening to be done by humans, in
> duplicate. This tool does not satisfy that and should only be used for
> supplementary support.

---

## Download

From the [Releases page](../../releases).

| | | |
|---|---|---|
| **macOS 11+** | `AI-Systematic-Review-Screening-Assistant.dmg` | Open it, drag the app to Applications |
| **Windows 10+ (64-bit)** | `AI-Systematic-Review-Screening-Assistant.msi` | Run it |

Both are unsigned, so the OS complains once:

- **macOS:** right-click the app in Applications, choose **Open**, confirm. Once only.
- **Windows:** SmartScreen warning, choose **More info**, then **Run anyway**.

### What you still need

- **An Anthropic API key.** Required. The app does nothing without it. Get one
  at [console.anthropic.com](https://console.anthropic.com) and paste it into
  Settings. You are billed for usage. A Claude.ai or Claude Code subscription
  does **not** give you API access.
- **Internet**, but only while screening.
- **Windows only:** the [Edge WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/).
  Already on Windows 11 and current Windows 10. Only install it if the app opens
  to a blank window.

Everything else is bundled. No Python install needed.

Your data stays on your machine and is never uploaded. The only outbound traffic
is the screening calls you trigger.

- macOS: `~/Library/Application Support/AI Systematic Review Screening Assistant/`
- Windows: `%APPDATA%\AI Systematic Review Screening Assistant\`

## How it works

Each record is sent to the API on its own, with only your criteria and that one
title and abstract. No other study, no earlier decision, no history. Decisions
are independent and reproducible instead of drifting down a list.

Every record comes back as **INCLUDE**, **EXCLUDE** or **MAYBE**, with a
confidence score and a one-line reason. MAYBE is common by design: it is
returned whenever the abstract is missing, the population or intervention is
ambiguous, or anything that would need the full text to settle.

**Use it like this:**

1. Screen by hand, record your decisions
2. Import the same records, run the tool
3. Export and compare row by row
4. Re-decide every disagreement yourself
5. Report your decisions

A run where you agree with everything told you nothing.

## Walkthrough

Six steps in the sidebar. Each shows a tick once complete.

### 1. Projects

Name your review and set its type. Everything else is scoped to the active
project, switchable from the bottom of the sidebar.

![Projects screen](pics/Projects_Screen.png)

### 2. Criteria

Six PICOS categories, paired include and exclude, twelve boxes. Auto-saves.

![Criteria screen](pics/Criteria_Screen.png)

These boxes are the **only** basis for every decision. Vague criteria produce
vague screening.

![All six PICOS categories](pics/full_pico_screenshot_in_criteria_screen.png)

Optional: add exclusion reason categories. If the list is non-empty, every
EXCLUDE and MAYBE gets tagged with one of them, which is what a PRISMA diagram
needs. Leave it empty and the model writes free text instead.

![Full-text exclusion reasons](pics/full_text_exclusion_reasons_screenshot_in_criteria_screen.png)

### 3. Import

Drop in `.ris` and `.txt` (PubMed/MEDLINE) exports. Format is auto-detected;
the source database is guessed from the filename so you can correct it first.

![Import screen](pics/imports_screen.png)

You get PRISMA-ready dedup counts and a per-database breakdown. Deduplication
runs in layers:

1. Exact DOI
2. PMID
3. Fuzzy title, but only with matching year and first author surname

Borderline fuzzy matches go to a review queue instead of merging silently.

![Deduplication summary after import](pics/Projects_Screen_w_RIS_uploaded_showing_dups.png)

### 4. Screen

- **Mode A, Test run.** Small live sample. Always do this first. If the
  decisions look wrong, fix your criteria before spending anything.
- **Mode B, Full run.** Everything unscreened via the Batches API, half price,
  back within 24h. Close the app while it runs if you like; progress is saved
  as results arrive and re-running skips what is done.

The top panel warns about a missing API key or empty criteria before you spend.

![Screen screen](pics/Screen_Screen.png)

### 5. Results

Filterable table of every decision. Filter by decision, category, tag, or
whether the record had an abstract.

| Export | Use |
|---|---|
| **RIS** | Includes (and optionally maybes) straight into Covidence, Rayyan or EndNote |
| **CSV** | The decision table, abstracts optional |
| **PRISMA counts** | Stage-by-stage numbers for your flow diagram |

Export the CSV and put it beside your manual results. This is the comparison
step.

![Results screen](pics/Results_Screen.png)

### 6. Settings

API key, model, and a connection test that makes one tiny call to confirm both
work. The key is stored locally in `secrets.local.json`, never shown in full,
and is separate from any Claude.ai or Claude Code login.

![Settings screen](pics/Settings_Screen.png)

## Keyboard shortcuts

`Ctrl` on Windows, `Cmd` on macOS.

| | |
|---|---|
| Zoom in / out / reset | `+` / `-` / `0`, or Ctrl and scroll |
| Find in page | `F`, then `Enter` / `Shift+Enter` |
| Jump to a section | `1` to `6` |
| Reload | `R` |
| Close find or dialog | `Esc` |
| Shortcut list | `/` or `?` |
