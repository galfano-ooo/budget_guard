# BudgetGuard — Unreal content budget toolkit

Checks the **textures, meshes and materials** of an Unreal Engine 5 project against per-tier performance budgets
and fixes the common problems automatically. Runs inside the Editor (Tools → BudgetGuard, a PySide6 panel), is
installed per project, and is project-agnostic: budgets, rules and tagging keywords are configuration, not code.

**Works with:** any UE 5 project (developed against UE 5.7.4).
**Scope:** 3D Environment / Rendering / Optimization only. No gameplay or mechanics logic is read, written or touched.

* **Tag** — writes a `BudgetTier` tag (`architecture | hero | props | background | utility`) on assets, by
  folder keywords or by hand, so audits know which budget applies.
* **Audit** — checks each asset against its tier (resolution, power-of-two, sRGB on normals, texture group,
  triangles, LODs, Nanite, collision, blend mode, two-sided) and reports FAIL / WARN / INFO / OK.
* **Fix** — texture groups and resolution, LOD groups, generated LODs, Nanite off.
* **Report** — CSV/JSON export and a self-contained HTML dashboard with a compare-with-previous-run mode.

New here? Read **[docs/USER_MANUAL.md](docs/USER_MANUAL.md)** — or open the **Help** tab in the panel.

## Quick start

1. Clone this repo somewhere permanent.
2. Run `installer/install.bat`, choose your project's `.uproject`, press **Install to Project**
   (details: `installer/QUICKSTART.md`).
3. Restart the Editor → **Tools → BudgetGuard**.

The installer *links* the project to this repo (nothing is copied): it adds a managed block to
`<Project>/Content/Python/init_unreal.py`, enables the Python Editor Script Plugin and installs PySide6 with the
engine's Python. Update with `git pull`.

## Repository layout

```
src/            Python backend (flat modules) + budgetguard_ui/ (PySide6 panel). src/ is the one sys.path entry.
config/         audit_budgets.json (generic defaults) + profile_*.json (shipped profiles)
examples/       ready-to-copy per-project override configs
dashboard/      Node tooling: audit CSV -> HTML dashboard (shelled out to by the panel)
installer/      repo-linked UE project installer (GUI + CLI)
docs/           USER_MANUAL.md
VERSION         tool version
```

Modules in `src/` stay flat (no package `__init__.py`) so `import audit_run` and `importlib.reload()` keep working.

### Backend modules

| File | Purpose |
|---|---|
| `audit_config.py` | Sole reader of the layered config: defaults + profile + the project's `Saved/BudgetGuard/config.json` override |
| `tag_existing_content.py` | Bootstrap and per-selection `BudgetTier` tagging (dry-run by default) |
| `audit_collector_level.py` / `audit_collector_folder.py` | Collect textures/meshes/materials from the open level + sublevels, or a folder recursively |
| `audit_rules_textures.py` / `_meshes.py` / `_materials.py` | The rules; severities and thresholds come from config |
| `audit_report.py` | `Report` / `Finding`: console log, CSV/JSON export |
| `audit_run.py` | Wires collectors → rules → report |
| `audit_fix_textures.py` / `audit_fix_meshes.py` | The fixes (plan → report → apply) |
| `build_tier_collections.py` | Counts tiers and selects a tier's assets in the Content Browser |
| `audit_actions.py` | Action layer the panel calls: scan-target resolution, audits, export + dashboard, reload |
| `audit_verify_api.py` | Diagnostic: checks the riskier engine API calls exist on your engine version |
| `budgetguard_ui/` | The panel: `bridge.py` is the only module touching the backend |

## Configuration (per project)

Defaults are generic. Everything a project wants different goes in
`<YourProject>/Saved/BudgetGuard/config.json` (edit it from the panel's Settings tab, or by hand) — it lives in the
project, so updating the tool never overwrites it. Only list what changes:

```json
{
  "extra_excluded_path_fragments": ["/Enums/"],
  "tiers": { "props": { "max_triangles": 6000 } },
  "rules": { "nanite_enabled": "OFF" },
  "tag_rules": { "props": ["furniture", "sofa"] }
}
```

Objects merge key by key; lists and plain values are replaced; `extra_excluded_path_fragments` is additive. A rule
severity of `"OFF"` disables the rule (currently honoured by `nanite_enabled`). An override that exists but is not
valid JSON stops the tool with a clear error. See `examples/` for a full keyword table.

## Console use

The panel wraps these; they work from the Editor's Python console too (`importlib.reload(module)` after edits):

```python
import audit_verify_api; audit_verify_api.run()          # check engine API availability first

import audit_run
audit_run.run_level_audit()                              # open level + sublevels
audit_run.run_folder_audit("/Game/MyContent")            # folder, recursively

import tag_existing_content as boot
boot.run(root_path="/Game/MyContent", apply=False)       # dry run; apply=True writes tags
```

## Reviewing results outside the editor

*Audit Results* in the panel (or `report.export_all(dir)`) writes `audit_asis.csv` / `.json` plus a timestamped copy
under `history/` into `<Project>/Saved/BudgetGuard/`. Build the dashboard from a terminal with:

```
node dashboard/generate_dashboard.js <csv_path> <html_out_path> [--project <name>]
```

It is a self-contained page: per-category stat bars, an auto-computed biggest-shared-root-cause callout, a filterable
FAIL table, and a **Compare** mode that loads an earlier `history/audit_asis_<timestamp>.json` to show fixed,
regressed, new and removed assets — all client-side. Needs Node.js on `PATH`.

## Known limitations

* **Sampler count / shading model** are not checked — walking the material expression graph is the most
  version-fragile part of the Material API.
* **`hero` is never auto-tagged** — a fresh project shows zero `hero` assets, which is correct.
* **No CI / headless entry point yet** (`UnrealEditor-Cmd.exe` commandlet is still to do).
* **All numeric budgets are placeholders** pending a technical-art validation pass.
* **Collections are not scriptable** on UE 5.7.4, and `BudgetTier` (package metadata) is invisible to Content Browser
  search/filters — the Tiers tab selects assets and you add them to a collection with one native click.
* **Texture-group fix needs a one-time ini setup** in the project, otherwise the audit's resolution check
  under-reports for textures already on a custom group — see the manual, section 5.
* Verified offline only: the installer's `register_menu()`, `unreal.Paths.project_dir()` fallback and PySide6 pip step
  have not all been confirmed live in the Editor.
