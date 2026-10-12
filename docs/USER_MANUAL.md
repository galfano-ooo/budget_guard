# BudgetGuard — user manual

BudgetGuard is a content-budget checker for Unreal Engine 5 projects. It lives inside the Unreal Editor
(Tools → BudgetGuard), checks your **textures, meshes and materials** against a performance budget, and can
automatically fix the most common problems. It never reads or changes gameplay or Blueprint logic.

> The same tutorial is built into the panel: open the **Help** tab (question-mark icon in the left rail).

## 1. Concepts

| Term | Meaning |
|---|---|
| **Budget tier** | How much an asset is allowed to cost. Five tiers: `architecture`, `hero`, `props`, `background`, `utility`. Stored on each asset as a metadata tag called `BudgetTier`. |
| **Rule** | One check (e.g. *Texture resolution over budget*, *Nanite enabled*). Each rule can be switched off or set to `WARN` / `FAIL`. |
| **Profile** | A shipped set of budgets + rule severities for a target platform (currently *Mobile VR – Quest 3*). |
| **Project override** | Your project's own changes on top of the profile, saved in `<Project>/Saved/BudgetGuard/config.json`. Updating the tool never overwrites it. |
| **FAIL / WARN / INFO / OK** | Over budget / suspicious / could not be evaluated / fine. INFO is not counted as pass or fail. |
| **Untagged** | An asset with no `BudgetTier` yet. It is audited against the default tier and **never fixed** until tagged. |

`hero` is reserved for unique, story-critical objects and is **never assigned automatically** — tag those by hand.
All numeric budgets shipped with the tool are placeholders until a technical artist validates them.

## 2. Installation

1. Clone or unzip this repository somewhere permanent. The project is *linked* to it, nothing is copied.
2. Double-click `installer/install.bat`, pick the project's `.uproject`, press **Install to Project**.
   (Command line: `python installer/install_ue_project.py "D:/MyGame" [--dry-run] [--engine "D:/UE_5.7"] [--no-pyside] [--uninstall]`.)
3. Restart the Editor and open **Tools → BudgetGuard**.

The installer adds a managed block to `<Project>/Content/Python/init_unreal.py`, enables the *Python Editor Script
Plugin* (a `.uproject.bak` is written first) and installs PySide6 with the engine's own Python. Optional: install
Node.js and put it on `PATH` to build the HTML dashboard.

**Update:** `git pull`. Re-run the installer only if you moved the repository.
**Remove:** run the installer with `--uninstall`.
**Old copy-style install?** Delete the stale `audit_*.py`, `budgetguard_ui/` … from `Content/Python`; they would shadow the repo.

## 3. First use

1. **Open the panel** (Tools → BudgetGuard). The header shows the project. If a banner says *No project config yet*,
   press **Set up project…** and choose the profile closest to your target platform.
2. **Tag your content** (Tag tab).
3. **Run an audit** (Audit tab).
4. **Fix** what the audit found (Fix tab), then audit again.

## 4. Tabs

### Audit
Pick the **scan target**: the open level + loaded sublevels, the folder selected in the Content Browser, or the whole
project (`/Game`). **Run audit** fills the FAIL/WARN/INFO/OK tiles and the per-category table (Textures, Meshes,
Materials, with an *Untagged* column); the full list is in the Output Log.
**Audit Results** exports `audit_asis.csv` / `.json` to `<Project>/Saved/BudgetGuard/` (plus a timestamped copy in
`history/`), builds `audit_dashboard.html` with Node and opens it. The dashboard has a **Compare** mode: load an older
`history/audit_asis_<timestamp>.json` to see what was fixed, regressed, added or removed — entirely client-side.

> A high *Untagged* percentage on a fresh folder usually means "tag it first", not "it is over budget".

### Tag
* **Bootstrap tagging** — assigns tiers from folder-name keywords defined in the config. Press **Preview (dry run)**
  first and read the *unmatched* list (never guessed — handle those by hand); then **Apply tags**. Apply only ever
  targets the folder that was previewed. Already-tagged assets are skipped.
* **Tag selected assets as** — select assets in the Content Browser and press a tier button. Use this for freshly
  imported content and for `hero`.

### Fix
Choose the scope — **Selected assets** or the **scan target folder** — then:

* **Fix textures**: custom texture group per tier, resolution override (only for tiers without a custom group), sRGB off on normal maps.
* **Fix meshes**: LOD Group per tier, tool-generated LODs for over-budget meshes with no LODs, Nanite off (when that rule is enabled).
* **Regenerate LODs**: redo tool-generated LODs whose configured poly fractions have changed since.
* **Mark LODs as tool-generated**: one-time migration for meshes whose LODs this tool created before provenance tracking existed (selected meshes only).

Fixes **write to your assets immediately**: use source control and save afterwards. Untagged assets are skipped and
listed. Hero meshes are never given generated LODs. LOD generation is a real mesh rebuild per asset — on large scopes
the Editor stays busy until the status bar turns green; progress is in the Output Log.

### Tiers
**Refresh counts** shows how many assets each tier holds (it loads every asset once, so it can be slow). **Select**
selects a tier's assets in the Content Browser; right-click → *Add to Collection* to keep them as a collection.
Unreal exposes no scripting API for collections, and `BudgetTier` is not searchable in the Content Browser, so
selection plus one native click is the supported route.

### Settings
Choose the profile, switch rules on/off, change `WARN`/`FAIL`, edit tier budgets, save/load **named presets**
(`Saved/BudgetGuard/presets/`), import/export the override file. Only values that differ from the profile are saved.
A rule set to `OFF` is skipped; today only `nanite_enabled` supports it (default is FAIL because the baseline target is
mobile/standalone VR — a desktop project that uses Nanite should switch it off). An override file that exists but is not
valid JSON stops the tool with a clear error instead of silently using defaults.

Per-project configuration example (`Saved/BudgetGuard/config.json`):

```json
{
  "extra_excluded_path_fragments": ["/Enums/"],
  "tiers": { "props": { "max_triangles": 6000 } },
  "rules": { "nanite_enabled": "OFF" },
  "tag_rules": { "props": ["furniture", "sofa"] }
}
```

Objects merge key by key, lists and plain values are replaced, `extra_excluded_path_fragments` adds to the default
exclusions. A ready-to-copy full example is in `examples/vendor_pack_modular_house.config.json`.

### Help and the left rail
**Help** is the in-panel tutorial. The bottom icon **Reload scripts** reloads the Python modules after you edit the
tool. **Compact** (header) shrinks the window to a narrow panel.

## 5. One-time engine setup for texture groups

*Fix textures* assigns each tier a custom texture group (`TEXTUREGROUP_PROJECT01…04`, see `texture_groups` in the
profile). For a group to have any effect at runtime, the project's ini must define it with the resolution cap you want
(a `TextureLODGroups` entry per group, e.g. `Group=TEXTUREGROUP_Project01,MaxLODSize=2048,…`). **The exact ini section
and syntax were not re-verified for this manual — check them against your engine version.**
Until this is done, the audit's *resolution over budget* rule under-reports for textures already on a custom group (it
trusts the group assignment). Mesh LOD Groups follow the same pattern: the group names in `lod_groups` must exist in the
project.

## 6. Troubleshooting

| Symptom | Likely cause |
|---|---|
| Tools → BudgetGuard is missing | Editor not restarted after install, or the PySide6 install failed — re-run the installer and read its log. |
| Header says *Project not found* | The tool could not resolve the project directory; set `BUDGETGUARD_PROJECT_DIR`. |
| Header says *config invalid* | `Saved/BudgetGuard/config.json` is not valid JSON — hover the chip for the error. |
| Many INFO findings | An engine API a rule needs is unavailable; run `import audit_verify_api; audit_verify_api.run()` in the Python console and read the Output Log. |
| Dashboard not built | Node.js is missing from `PATH`. |
| Code edits have no effect | Press **Reload scripts**; Python caches imports. |

## 7. Console use (optional)

```python
import audit_run
audit_run.run_level_audit()                     # open level + sublevels
audit_run.run_folder_audit("/Game/MyContent")   # a folder, recursively

import tag_existing_content as boot
boot.run(root_path="/Game/MyContent", apply=False)   # preview
boot.run(root_path="/Game/MyContent", apply=True)    # write tags
```
