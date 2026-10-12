# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**BudgetGuard** — a project-agnostic Python content-budget toolkit for Unreal Engine 5 (developed against UE 5.7.4), installable into any number of UE projects. It runs *inside the UE5 Editor Python console* (Python Editor Script Plugin), not standalone — there is no local test runner, build step, or CI in this repo. Scope is strictly 3D Environment / Rendering / Optimization.

Two capabilities:
1. **Tagging** (`tag_existing_content.py`) — applies a `BudgetTier` asset metadata tag (`architecture | hero | props | background | utility`) via folder-keyword matching, so later audits know what budget to check an asset against without re-deriving it from file location.
2. **Auditing** (`audit_run.py` + rule modules) — walks collected Textures/Meshes/Materials, checks each against its tier's budget in `audit_budgets.json`, and prints a categorized FAIL/WARN/OK console report.

Read `README.md` (overview + layout), `docs/USER_MANUAL.md` (end-user behaviour of every tab) and the "Constraints" section below before making changes — it records API facts that were confirmed the hard way against this engine and should not be re-guessed. Module docstrings carry the per-module rationale.

## Repository layout

```
src/         Python backend, flat modules (audit_*.py, tag_existing_content.py, build_tier_collections.py) + budgetguard_ui/ package — the one sys.path entry
config/      audit_budgets.json (generic defaults) + profile_*.json
examples/    per-project override examples
dashboard/   Node tooling (never imported by Python)
installer/   repo-linked installer
docs/        USER_MANUAL.md
VERSION      tool version
```

`audit_config` / `audit_actions` / `bridge` locate `config/`, `dashboard/`, `examples/` relative to `src/`. Modules inside `src/` stay flat (no package `__init__.py`) so `import audit_run` + `importlib.reload()` keep working.

## Running / testing changes

There is no automated test suite. Verification happens by pasting into the UE5 Editor's Python console:

```python
# Always run first when touching anything in audit_rules_meshes.py or
# audit_collector_level.py — it diagnoses whether the riskier engine API
# calls those modules depend on still exist on the current fork/version.
import audit_verify_api
audit_verify_api.run()

# Then the real audit:
import audit_run
audit_run.run_level_audit()                        # current level + loaded sublevels (default)
audit_run.run_folder_audit("/Game/MyContent") # or: direct recursive folder scan (validated — see Constraints)

# Bootstrap tagging — dry-run first, always:
import tag_existing_content as boot
boot.run(root_path="/Game/MyContent", apply=False)   # preview only
boot.run(root_path="/Game/MyContent", apply=True)    # writes tags
```

Python caches imports in the UE console — after editing a file, `importlib.reload(module_name)` before re-running, or changes won't take effect.

**Install: repo-linked (the only model).** `installer/install_ue_project.py` (+ `install_ue_project_gui.py`, `install.bat`) writes a managed block into `<Project>/Content/Python/init_unreal.py` that appends the repo's `src/` dir to `sys.path` and calls `budgetguard_ui.register_menu()` (Tools → BudgetGuard), enables PythonScriptPlugin, and pip-installs PySide6 with UE's own Python. Nothing is copied, so the flat-layout invariant below still holds *inside `src/`*. A leftover copy-model install in `Content/Python` shadows the repo (installer warns); the old copy-deploy script, ZIP/PowerShell installer, Editor Utility Widget and its action layer are gone. Offline-verified only (block write/update/uninstall, .uproject edit); NOT verified live: `register_menu()` in the Editor, `unreal.Paths.project_dir()` (new fallback in `audit_config.get_project_dir`), PySide6 pip step.

Modules in `src/` stay **flat** (no package `__init__.py`; `budgetguard_ui/` is the one subpackage) so plain `import` works with `src/` as the only `sys.path` entry and `importlib.reload()` stays simple. `dashboard/` is Node tooling, never `import`ed by Python.

`audit_actions.py` is the action layer the panel's `bridge.py` calls: scan-target resolution from the Content Browser selection, folder/level audits (keeping the last `Report` for export), export + dashboard build (`subprocess` → `dashboard/generate_dashboard.js`), and `reload_toolkit_modules()` (dependency-ordered reload; keep `_RELOAD_ORDER` in sync when adding a backend module).

## Architecture

Pipeline: **collector → rule modules → Report**, tied together by `audit_run.py`.

- **Collectors** (`audit_collector_level.py`, `audit_collector_folder.py`) each return the same shape: a dict of `{"Textures": [(path, obj), ...], "Meshes": [...], "Materials": [...]}`. This is the contract new collectors must satisfy — `audit_run._run_rules()` consumes that shape and doesn't care how it was produced.
  - `audit_collector_level.py` walks actors/components (not filtered by actor class) so meshes/materials wrapped inside Blueprints are still caught. Unloaded sublevels are reported, not force-loaded.
  - `audit_collector_folder.py` is a direct recursive Content Browser scan, independent of level placement.
- **Rule modules** (`audit_rules_textures.py`, `audit_rules_meshes.py`, `audit_rules_materials.py`) each expose one `audit_X(asset_path, obj, tier, cfg=None)` function returning a list of `(severity, message)` tuples. Severity (`FAIL`/`WARN`/`INFO`) and numeric thresholds come from `cfg`, never hardcoded — see `audit_budgets.json`. `INFO` specifically means "couldn't evaluate this rule against the API," not a content problem, and is excluded from the pass/fail tally.
- **`audit_config.py`** is the sole reader of the config (module-level cached), exposing accessors (`get_tier_budget`, `get_rule_severity`, `is_rule_enabled`, `get_tag_key`, `get_tag_rules`, `get_taggable_classes`, `is_excluded`, `get_data_dir`, `get_project_name`) rather than having callers touch the parsed JSON directly. The config is **layered**: generic defaults in `audit_budgets.json` (ships with the tool, identical for every project) deep-merged with an optional per-project override at `<Project>/Saved/BudgetGuard/config.json` (objects merge key by key; lists and scalars are replaced; `extra_excluded_path_fragments` is additive). A project override that exists but doesn't parse **raises** — never a silent fallback to defaults. The project dir comes from `BUDGETGUARD_PROJECT_DIR`, else `unreal.SystemLibrary.get_project_directory()` (not yet confirmed live on this engine), else the legacy two-folders-above-this-file guess. `examples/vendor_pack_modular_house.config.json` is a ready-to-copy override.
- **`audit_report.py`**'s `Report`/`Finding` collects results and renders the console log — one section per category with FAIL/WARN/INFO/OK counts. New rule modules should route findings through `Finding(...)` + `Report.add()` rather than printing directly.
- **`audit_run.py`** is the only place that wires a collector's output to the rule modules and resolves each asset's `BudgetTier` tag (falling back to `default_tier` from config, and flagging the asset as untagged in the report).
- **`tag_existing_content.py`** reads its keyword table (`tag_rules`), `taggable_classes`, exclusions and tag key from `audit_config` — nothing project-specific lives in the Python. `hero` is never auto-assigned even if a project config lists keywords for it (`MANUAL_ONLY_TIERS`).

- **`budgetguard_ui/`** is the PySide6 panel, built to the approved Penpot design (file "Nuovo File 1", page "Panel"). Open with `import budgetguard_ui; budgetguard_ui.show()`; `budgetguard_ui.reload()` re-imports it. Same mechanism as greybox_gen's panel (Slate tick pump, `parent_external_window_to_slate`, no `app.exec()`). `bridge.py` is the ONLY module that touches the backend (every call returns `{"ok", "msg", ...}`, never raises into a Qt slot); `theme.py` is the only place a hex colour is written; tabs: `tabs.py` (Audit/Tag/Fix/Tiers), `help_tab.py` (static in-panel tutorial for first-time users — keep it in step with `docs/USER_MANUAL.md` when a tab's behaviour changes), `settings_tab.py` (staged profile, per-rule switch + WARN/FAIL severity + thresholds, editable tier budgets, named presets in `Saved/BudgetGuard/presets/`, Save bar, override-file actions; `audit_config.save_edits` stores only values that differ from the profile baseline; opening an empty override writes an editable template; scan target lives in the Audit tab), `setup_dialog.py` (first-run). `audit_actions.py` is the action layer the bridge calls. Don't use `deleteLater()` alone to drop widgets (the tick pump doesn't run deferred deletes) — use `widgets.clear_layout()`.

### Adding a new rule
Add it inside the relevant `audit_rules_*.py` module's `audit_X()` function, add its severity/thresholds to `audit_budgets.json` under `"rules"`, and read them via `audit_config.get_rule_severity(...)` — don't hardcode a severity string in the rule module.

### Editing budgets
Change config, not Python. `audit_budgets.json` holds the **generic defaults** shipped with the tool — edit it only for something that should change for *every* project; a project's own numbers, keywords and exclusions go in its `<Project>/Saved/BudgetGuard/config.json` override. All default numeric values are explicit placeholders (`"status": "budgets_v01_tbd"`) pending a technical art validation pass — don't treat them as final when reasoning about whether a check "should" fire.

## Constraints that shape the code (don't relitigate without reason)

- **Rules can be switched off per project**: a rule whose severity is `"OFF"` is skipped (`audit_config.is_rule_enabled`). Today only `nanite_enabled` honours it (audit finding and the `NANITE_DISABLE` fix) — the default stays FAIL because the tool's baseline target is mobile/standalone VR; a desktop project that uses Nanite sets it to `OFF` in its override.
- **Tags decouple tier from folder location.** `BudgetTier` is written once by the bootstrap script and persisted as metadata, not re-derived from folder path on every audit run — content can be reorganized later without losing its tier.
- **`hero` is never auto-assigned.** Reserved for unique narrative-critical objects; the current vendor furniture pack is expected to show zero `hero`-tagged assets, which is correct, not a bug.
- **Bootstrap tagging is dry-run by default** (`apply=True` required explicitly), skips already-tagged assets unless `force=True`, and never silently defaults unmatched folders to a tier — unmatched assets are listed for manual review instead.
- **Material property access must go through `base_property_overrides`**, not direct `get_editor_property("blend_mode"/"two_sided"/"shading_model")` calls on instances — those throw on `MaterialInstanceConstant`. If the relevant `override_X` flag is `False`, resolve the effective value by walking `.get_editor_property("parent")` up to the base `Material` (see `audit_rules_materials._resolve_effective`).
- **Engine enum values must be compared directly, never via `str()`.** `str(some_enum_value)` renders as `"<ClassName.MEMBER_NAME: value>"`, not the plain member name — string-based comparisons silently never match. This caused real bugs; run `audit_verify_api.run()` before relying on any new engine API call.
- **Triangle count comes from `AssetData.get_tag_value("Triangles")`**, not `EditorStaticMeshLibrary` (no triangle-count method exists on this fork; vertex count is not a valid proxy since UV/normal seams split vertices unpredictably).
- **`run_folder_audit()` / `audit_collector_folder.py` is now fully validated** (2026-09-03, pilot project, full content tree: 608 textures / 691 meshes / 230 materials, zero exceptions). Two real bugs surfaced and were fixed during that validation, both in rule modules the collector feeds, not the collector itself: `TextureCube` crashing `audit_rules_textures.audit_texture()` (it assumed `Texture2D`), and a false-positive sRGB-on-normal-map match caused by an overly broad `"_n" in filename` heuristic (narrowed to `"normal" in filename`). One caveat also surfaced: **a folder scan can hit assets the bootstrap tagging pass never covered**, so a high untagged-% in a folder-audit report may mean "run `tag_existing_content.py` on this subtree first," not "these assets are actually over budget" — check the untagged count before trusting FAIL/WARN totals from a fresh subtree.
- **Excluded folders have one source now**: `excluded_path_fragments` (defaults) + the project's `extra_excluded_path_fragments`, read by `audit_config.is_excluded()` for both tagging and auditing — the old duplicated-list hazard is gone. The generic defaults only exclude `/Collections/` and `/Developers/`; anything project-specific (`/Enums/`, script folders…) belongs in the project override.
- **There is no scriptable Content Browser Collections API on this engine, and `BudgetTier` is invisible to native search/filters/columns.** Both confirmed live (2026-09-07): `unreal.CollectionScriptingLibrary` doesn't exist at all — zero classes with "Collection" in the name anywhere in `dir(unreal)`, on UE 5.7.4 vanilla (Epic Launcher), not a stripped fork. Separately, a Content Browser Custom Filter using `BudgetTier=<tier>` (and variants) against known-tagged assets returned zero results — the tag is package `UMetaData`, not an Asset Registry tag, so it's invisible to search/filters/columns too, not just to Collections. **Don't re-attempt either approach without re-verifying first.** `build_tier_collections.py`'s `select_tier()` is the practical workaround: it finds a tier's tagged assets (same load-every-asset-and-read-the-tag approach as everything else in this toolkit) and selects them in the Content Browser via the confirmed-working `unreal.EditorAssetLibrary.sync_browser_to_objects`. Building/updating the actual Collection from that selection is then one native "Add to Collection" click — not scriptable, but safe to repeat (adding an already-present asset is a no-op); removing a re-tagged-away asset from a stale collection still needs a manual removal. Wired to the panel's Tiers tab (`bridge.select_tier()` / `count_tiers()`).
