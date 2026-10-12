"""
audit_actions.py
------------------------------------------------------------------------------
Action layer behind the BudgetGuard Qt panel (budgetguard_ui/bridge.py is its
only caller). It sits between the panel and the audit pipeline: scan-target
resolution from the Content Browser, the audit runs, export + dashboard build,
and the module reload.

Scan target: run_audit() and the fix actions take no path by default — they
resolve one from the current Content Browser selection (a selected folder
wins; then a selected asset's containing folder; otherwise the whole project,
"/Game"). describe_scan_target() returns that same resolution as a short
string. Pass an explicit root_path to override the auto-resolution.

run_level_audit_action() ignores the Content Browser selection and scans the
currently open level + loaded sublevels instead (audit_run.run_level_audit()).

State: the last Report from run_audit() / run_level_audit_action() is kept in
this module's global (_last_report) so export_and_build_dashboard() can reuse
it without re-running the audit. Reloading this module (reload_toolkit_modules())
resets it — run the audit again afterwards.

Exported data (CSV/JSON/HTML) is written under the *project's*
Saved/BudgetGuard/ folder, not into this repo — it's per-machine, ephemeral
output, the same way Unreal treats build artifacts.
------------------------------------------------------------------------------
"""

import importlib
import os
import subprocess
import sys

import unreal

import audit_config
import audit_run

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

FULL_PROJECT_ROOT = "/Game"  # fallback when nothing is selected in the Content Browser

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))

# <repo>/dashboard/ — this file lives in <repo>/src/.
DASHBOARD_DIR = os.path.join(os.path.dirname(_THIS_DIR), "dashboard")
GENERATE_SCRIPT = os.path.join(DASHBOARD_DIR, "generate_dashboard.js")

# <Project>/Saved/BudgetGuard — same folder that holds the project's optional
# config.json override (audit_config.get_data_dir() resolves the project).
EXPORT_DIR = audit_config.get_data_dir()
CSV_PATH = os.path.join(EXPORT_DIR, "audit_asis.csv")
JSON_PATH = os.path.join(EXPORT_DIR, "audit_asis.json")
HTML_PATH = os.path.join(EXPORT_DIR, "audit_dashboard.html")

NODE_EXE = "node"  # change this if node.exe isn't on PATH for the Editor process

_last_report = None       # set by run_audit()/run_level_audit_action(); read by export_and_build_dashboard()


def _log(msg):
    unreal.log(f"[BudgetGuard] {msg}")


# ---------------------------------------------------------------------------
# Scan target resolution — Content Browser selection, not a hardcoded path
# ---------------------------------------------------------------------------

def resolve_scan_target():
    """Returns (root_path, label): a selected Content Browser folder wins;
    then a selected asset's containing folder; otherwise the whole project.
    label is the same thing as a human-readable string, for logging."""
    try:
        folders = unreal.EditorUtilityLibrary.get_selected_folder_paths()
    except AttributeError:
        folders = []
    if folders:
        root = str(folders[0])
        if len(folders) > 1:
            return root, f"{root}  (+{len(folders) - 1} more folder(s) also selected — using the first)"
        return root, root

    try:
        assets = unreal.EditorUtilityLibrary.get_selected_asset_data()
    except AttributeError:
        assets = []
    if assets:
        package_name = str(assets[0].package_name)
        root = package_name.rsplit("/", 1)[0] if "/" in package_name else package_name
        return root, f"{root}  (from selected asset {assets[0].asset_name})"

    return FULL_PROJECT_ROOT, f"{FULL_PROJECT_ROOT}  (nothing selected in the Content Browser — the whole project)"


def _short_name(path):
    """Last segment of an /A/B/C-style content path, e.g. 'Meshes_doors'
    for '/Game/MyContent/Meshes/Meshes_doors'."""
    return path.rstrip("/").rsplit("/", 1)[-1] or path


def describe_scan_target():
    """Short, human-friendly label for the scan target — just the
    folder/asset name (e.g. 'Meshes_doors'), not the full path. The full path
    is still logged by run_audit() when it runs."""
    root, _ = resolve_scan_target()
    if root == FULL_PROJECT_ROOT:
        return "Whole project"
    return _short_name(root)


def _resolve(root_path):
    if root_path:
        return root_path, root_path
    return resolve_scan_target()


# ---------------------------------------------------------------------------
# Reload toolkit modules (avoid stale-code mismatches). Python only imports a
# module once per Editor session, so editing a .py file does nothing until
# something calls importlib.reload() on it.
# Order matters: base modules with no toolkit dependencies first, then
# audit_run last among the "leaf" set because it does
# `from audit_report import Report, Finding` — a name binding that only
# picks up a reloaded audit_report's new classes once audit_run ITSELF is
# also reloaded afterward. This module reloads itself last of all, via the
# sys.modules[__name__] self-reload trick — see reload_toolkit_modules().
# ---------------------------------------------------------------------------

_RELOAD_ORDER = [
    "audit_config",
    "audit_report",
    "audit_rules_textures",
    "audit_rules_meshes",
    "audit_rules_materials",
    "audit_collector_level",
    "audit_collector_folder",
    "audit_verify_api",
    "audit_run",
    "audit_fix_textures",
    "audit_fix_meshes",
    "build_tier_collections",
    "tag_existing_content",
]


def reload_toolkit_modules():
    """Force-reloads every toolkit module, in dependency order, INCLUDING
    audit_actions itself as the very last step.

    The self-reload (`importlib.reload(sys.modules[__name__])`) is safe to
    call from inside this very function: reload() re-executes the module's
    top-level code into the SAME dict this running function is already
    using as its globals, so this call finishes on its old bytecode and
    only the NEXT call sees the fresh definitions. The one real side effect:
    it also resets this module's session state (_last_report) to None, same
    as restarting the Editor would — run the audit again before exporting.
    """
    reloaded = []
    failed = []
    for name in _RELOAD_ORDER:
        try:
            module = importlib.import_module(name)
            importlib.reload(module)
            reloaded.append(name)
        except Exception as exc:
            failed.append((name, exc))

    try:
        importlib.reload(sys.modules[__name__])
        reloaded.append(__name__)
    except Exception as exc:
        failed.append((__name__, exc))

    _log(f"Reloaded {len(reloaded)} module(s): {', '.join(reloaded)}")
    for name, exc in failed:
        _log(f"FAILED to reload {name}: {exc}")
    if __name__ in reloaded:
        _log("audit_actions.py itself was reloaded too — session state "
             "(_last_report) was reset; run the audit again before exporting.")


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------

def run_audit(root_path=None):
    """Runs the full folder audit on the current selection (or the whole
    project if nothing's selected) and keeps the Report in memory for
    export_and_build_dashboard()."""
    global _last_report
    root_path, label = _resolve(root_path)
    _log(f"Running audit on {label} ...")
    _last_report = audit_run.run_folder_audit(root_path)
    _log(f"Audit complete — {len(_last_report.findings)} finding(s) logged above.")


def run_level_audit_action():
    """Runs the audit against the currently open level + loaded sublevels
    (audit_run.run_level_audit()) instead of a Content Browser
    folder/selection, and keeps the Report in memory — same contract as
    run_audit()."""
    global _last_report
    _log("Running level audit (current level + loaded sublevels) ...")
    _last_report = audit_run.run_level_audit()
    _log(f"Audit complete — {len(_last_report.findings)} finding(s) logged above.")


# ---------------------------------------------------------------------------
# Export + dashboard
# ---------------------------------------------------------------------------

def export_and_build_dashboard():
    """Exports the last audit report to Saved/BudgetGuard/ — both the
    always-current audit_asis.csv/json (CSV_PATH/JSON_PATH, what
    generate_dashboard.js and the Compare file-picker's "latest" reads) and a
    timestamped archive copy under Saved/BudgetGuard/history/, so every run
    leaves its own file behind instead of overwriting the previous one. Then
    shells out to Node to (re)build the HTML dashboard next to it."""
    if _last_report is None:
        _log("No audit has been run yet this session — run an audit first.")
        return

    _, _, csv_dated, json_dated = _last_report.export_all(EXPORT_DIR)
    _log(f"Exported to {EXPORT_DIR} (archived copy: {os.path.basename(csv_dated)} / {os.path.basename(json_dated)})")

    if not os.path.isfile(GENERATE_SCRIPT):
        _log(f"generate_dashboard.js not found at {GENERATE_SCRIPT} — "
             f"is the repo's dashboard/ folder intact?")
        return

    try:
        result = subprocess.run(
            [NODE_EXE, GENERATE_SCRIPT, CSV_PATH, HTML_PATH,
             "--project", audit_config.get_project_name()],
            capture_output=True, text=True, timeout=60,
        )
    except FileNotFoundError:
        _log(f"Couldn't launch '{NODE_EXE}' — is Node.js installed and on PATH "
             f"for this machine?")
        return
    except subprocess.TimeoutExpired:
        _log("generate_dashboard.js timed out after 60s.")
        return

    if result.returncode != 0:
        _log(f"generate_dashboard.js failed:\n{result.stderr.strip()}")
        return

    _log(result.stdout.strip())


def open_dashboard():
    """Opens the last-built dashboard HTML in the default browser."""
    if not os.path.isfile(HTML_PATH):
        _log("No dashboard built yet — export + build the dashboard first.")
        return
    os.startfile(HTML_PATH)  # Windows. On Mac/Linux use: subprocess.run(["open"/"xdg-open", HTML_PATH])
