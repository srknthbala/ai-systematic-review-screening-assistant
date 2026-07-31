# AI Systematic Review Screening Assistant

A local desktop application for AI-assisted title/abstract screening. Single
user, runs entirely on your machine (macOS or Windows). Projects, criteria, imported
records, and screening results all persist in a local SQLite file between runs.

It is built around the Anthropic API: a synchronous **Test run** for sanity-
checking your criteria on a small sample, and an asynchronous **Full run** using
the **Message Batches API** (50% cheaper) for the whole set.

---

## Install

Grab the installer for your platform from the
[Releases page](../../releases):

| Platform | File | Installs to |
|---|---|---|
| macOS 11+ | `AI-Screening-Assistant-VERSION.dmg` | drag to Applications |
| Windows 10/11 64-bit | `AI-Screening-Assistant-VERSION.msi` | `Program Files` + Start menu |

On macOS, open the `.dmg` and drag the app onto the Applications shortcut.
On Windows, run the `.msi`.

Both are **unsigned**, so the OS will object the first time:

- **macOS:** launching gives "cannot be opened because Apple cannot check it".
  Right-click the app in Applications, choose **Open**, then confirm. You only
  do this once.
- **Windows:** SmartScreen shows a blue warning. Choose **More info**, then
  **Run anyway**.

Signing them away needs an Apple Developer ID (99 USD/year) and a Windows
code-signing certificate. The build scripts take both if you have them.

Your data lives outside the application and survives upgrades and uninstalls:

- macOS: `~/Library/Application Support/AI Systematic Review Screening Assistant/`
- Windows: `%APPDATA%\AI Systematic Review Screening Assistant\`

### Keyboard shortcuts

`Ctrl` on Windows, `Cmd` on macOS.

| | |
|---|---|
| Zoom in / out / reset | `+` / `-` / `0`, or Ctrl and scroll wheel |
| Find in page | `F`, then `Enter` / `Shift+Enter` to cycle |
| Jump to a section | `1` to `6` |
| Reload | `R` |
| Close find or dialog | `Esc` |
| Show this list | `/` or `?` |

## Building from source

The app ships as an installer; there is no browser mode and no dev server.
If you want to build it yourself you need **Python 3.11** and the matching OS,
because neither installer format can be produced from the other platform and
PyInstaller cannot cross-compile.

```bash
# macOS, produces dist/AI-Screening-Assistant-1.0.0.dmg
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-desktop.txt
./packaging/macos/build.sh 1.0.0
```

```powershell
# Windows, produces dist\AI-Screening-Assistant-1.0.0.msi
# (installs the WiX v5 CLI via dotnet tool if it is missing)
python -m venv .venv; .venv\Scripts\Activate.ps1
pip install -r requirements.txt -r requirements-desktop.txt
powershell -ExecutionPolicy Bypass -File packaging\windows\build.ps1 -Version 1.0.0
```

To run the app without packaging it, from a checkout:

```bash
pip install -r requirements.txt -r requirements-desktop.txt
python desktop.py
```

That opens the same native window the installed app does. Data goes to `./data`
instead of the per-user location.

CI builds both installers on their native runners, see
`.github/workflows/release.yml`. Push a tag to cut a release:

```bash
git tag v1.0.0 && git push origin v1.0.0
```

### First-time setup (inside the app)

1. **Settings** → paste your Anthropic API key, pick a model, click
   **Test connection**. The key is stored locally in `secrets.local.json`
   (file permissions `0600`) next to the database, never in the repo, and is
   **separate from any Claude Code or Claude.ai login**.
2. **Projects** → create a project (the active project scopes everything else).
3. **Criteria** → fill in the 12 PICOS boxes; optionally add full-text
   exclusion-reason categories.
4. **Import** → upload your `.ris` / `.txt` files, confirm the source label per
   file, import. Review the dedup counts and any borderline merges.
5. **Screen** → run a small **Test run** first, then submit the **Full run**.
6. **Results** → filter, read, and export: RIS for the records you are
   carrying into full-text screening, CSV for the decision table, and a
   stage/count CSV for your PRISMA flow.

---

## The workflow in detail

### Projects
Multiple projects, each storing Covidence-style review settings (review name,
review type, question type, area of research, free-text notes). All criteria,
imports, and results are scoped to the selected project.

### Criteria
Six PICOS categories (Population, Intervention/Exposure, Comparator/Context,
Outcome, Study Characteristics, Other), each with an Include and an Exclude box
(12 boxes total). Changes auto-save to the active project.

Optionally maintain a **full-text exclusion-reason list** (e.g. "Wrong
population", "Animal study", "No muscle morphology outcome"). If the list is
non-empty, every EXCLUDE/MAYBE is tagged with the single best-fit reason from the
list. If empty, the model writes a free-text reason instead.

### Import & deduplication
Accepts `.ris` and `.txt` (PubMed/MEDLINE). Format is auto-detected by content
signature (RIS opens with `TY  - ` and closes with `ER  - `; MEDLINE uses
4-char tags like `PMID- `, `TI  - `), with a filename-extension fallback you can
override per file. The **source database** is inferred from the filename and is
editable before import.

Text is normalized to ASCII (Greek letters spelled out, en/em dashes and smart
quotes folded, accents stripped). Records with no abstract are flagged (they
cannot be content-screened and tend toward MAYBE).

Deduplication runs in layered order:

1. **Exact DOI** match.
2. **PMID** match (for records not already merged by DOI).
3. **Fuzzy title** match for records missing *both* identifiers: lowercased,
   punctuation/whitespace stripped, **requiring the same year and the same
   first-author surname**.

Thresholds (in `app/services/dedup.py`, easy to edit):

- Pairs with similarity **> 0.93** (and matching year + first author) auto-merge.
- Pairs in the **0.88–0.93** borderline band go to a **"Review these merges"**
  queue instead of being silently merged, so you confirm or split each one.

Every merge is logged. A surviving record records **all** databases it appeared
in. The Import screen shows total-in / duplicates-removed / unique-out and a
per-database breakdown for your PRISMA diagram.

### Screening

**Independence.** Each record is screened in its own request containing only the
criteria (as a cached system block) plus that single title/abstract, with no other
study, no prior decision, no conversation history. The model is explicitly told
it has no memory of other records. Every decision is therefore independent and
reproducible (temperature 0).

Both modes return this exact JSON per record:

```json
{ "decision": "INCLUDE" | "EXCLUDE" | "MAYBE",
  "confidence": 0.0,
  "reason": "one short line",
  "exclusion_reason_category": "<one item from your reason list, or null>",
  "tags": [] }
```

Rules baked into the system prompt: three-way decisions (MAYBE when the abstract
is missing, the P/I/C is ambiguous, or it can't be decided from the abstract
alone); title/abstract-stage exclusions only (full-text-only concerns such as
effect-size data, exact post-baseline timing, or washout adequacy return MAYBE,
never EXCLUDE); and auto-tagging of "Confound: BFR", "Confound: Protein
supplementation", and "Spasticity present" when present in the abstract.

- **Mode A, Test run (synchronous):** screen a small sample (default 25) live
  with a progress bar.
- **Mode B, Full run (Message Batches API):** submit all unscreened records
  asynchronously; returns within 24h (usually much faster). The `batch_id` is
  persisted, so you can **close and reopen the app** while it runs and it resumes
  polling. Results are written incrementally; a crash or close never loses
  progress, and re-running skips already-screened records.

**Cost.** Prompt caching is applied to the (identical) criteria block, which
stacks with the batch discount, roughly 95% off input tokens for cached batch
requests.

### Results
A filterable table (title, year, source databases, decision, confidence, reason,
exclusion category, tags, DOI, PMID, has-abstract). Filter by decision (see all
MAYBEs in one pass), tag, exclusion category, and abstract presence. Summary
counts at the top feed your PRISMA diagram. **Export to CSV** respects the active
filters.

### Settings
API key (stored locally, masked, removable), model dropdown
(`claude-sonnet-4-6` default, `claude-haiku-4-5` cheapest, `claude-opus-4-8`
most capable), and a one-call **Test connection** button. The key does not
determine the model. The model is chosen here per request.

---

## Notes & troubleshooting

- **Data location.** Everything lives in `data/screening.db`. Delete it to start
  clean. Back it up to keep your work.
- **Your key never leaves your machine** except in calls to the Anthropic API.
  `secrets.local.json` and `data/` are gitignored.
- **Model id rejected?** Model identifiers occasionally change. Edit the `MODELS`
  list in `app/config.py` and restart.
- **Adding more files later** re-runs dedup across the whole project (use
  "Re-run dedup" on the Import screen).
- This is a research-preview practice tool; always have a human review the
  model's INCLUDE/MAYBE decisions before relying on them.

## Project layout

```
ai-screening/
├── requirements.txt
├── app/
│   ├── main.py            # FastAPI app + static SPA
│   ├── config.py          # paths, model list, local secret handling
│   ├── db.py              # SQLite schema + helpers
│   ├── routers/           # projects, criteria, imports, screen, results, settings
│   ├── services/          # ris_parser, normalize, dedup, importer,
│   │                      #   anthropic_client, screener, batches,
│   │                      #   exporters (RIS + PRISMA)
│   └── static/            # index.html, css, js, bundled typeface
├── packaging/             # PyInstaller spec, icon generator,
│                          #   .dmg and .msi build scripts
├── desktop.py             # native window shell (pywebview)
├── data/                  # screening.db (created at runtime, gitignored)
└── tests/                 # parser/dedup, screening, results. Run with python
```

## Running the tests

```bash
python tests/test_import_dedup.py    # parsing + layered dedup
python tests/test_screen.py          # JSON parsing, independence, sync + batch
python tests/test_results.py         # results filters + CSV export
```

The screening tests use an injected fake client, so they run without an API key
or network access.

## Credits

The interface is set in **Karrik** by Jean-Baptiste Morizot and Lucas Le Bihan,
published by [Velvetyne](https://velvetyne.fr/fonts/karrik/). It is a
vernacular sans that keeps the weight disadjustments and uneven letter widths
of the anonymous early grotesques it draws from, which is the reason it is
here rather than a neutral UI face.

Karrik is used under the SIL Open Font License 1.1. The font files and the
full licence text ship with the app in `app/static/fonts/`.
