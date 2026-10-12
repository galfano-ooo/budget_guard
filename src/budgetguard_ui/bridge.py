# -*- coding: utf-8 -*-
"""
The ONLY module in budgetguard_ui that touches the BudgetGuard backend (audit_config,
audit_actions, tag_existing_content, audit_fix_*, build_tier_collections) - the panel is a
thin view over it, and `audit_actions.py` is the action layer it calls.

No Qt in here on purpose. Every action returns a plain dict `{"ok": bool, "msg": str, ...}`;
an exception becomes `{"ok": False, "msg": "FAILED (...)"}` with the traceback in the Output
Log, so a Qt slot never sees one and the status line always has something to show.

Backend modules are looked up through `_m()` at call time (not imported at module top) so that
audit_actions.reload_toolkit_modules() - which reloads them - is picked up without
re-importing this package.
"""
import importlib
import os
import shutil
import traceback

import unreal

SCAN_LEVEL, SCAN_FOLDER, SCAN_PROJECT = "level", "folder", "project"
SCAN_MODES = (
    (SCAN_LEVEL, "Current level + sublevels"),
    (SCAN_FOLDER, "Selected Content Browser folder"),
    (SCAN_PROJECT, "Whole project (/Game)"),
)

# project chip states (see the Penpot "States" frame)
PROJECT_OK, PROJECT_NO_OVERRIDE, PROJECT_INVALID, PROJECT_NOT_FOUND = (
    "ok", "no_override", "invalid", "not_found")

_REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _m(name):
    return importlib.import_module(name)


def _fail(label, exc):
    unreal.log_error("[BudgetGuard] %s raised:\n%s" % (label, traceback.format_exc()))
    return {"ok": False, "msg": "FAILED (%s: %s: %s) - see Output Log" % (label, type(exc).__name__, exc)}


def _call(label, fn, *args, **kwargs):
    """fn(...) -> {"ok": True, "msg": str, **extras}; fn returns (msg, extras_dict) or msg."""
    try:
        out = fn(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001 - never let it escape into a Qt slot
        return _fail(label, exc)
    msg, extra = out if isinstance(out, tuple) else (out, {})
    return dict({"ok": True, "msg": str(msg)}, **extra)


# ---- project / config ----

def project_info():
    """{state, name, profile_label, error}: the header chip. Never raises."""
    cfg_mod = _m("audit_config")
    name = cfg_mod.get_project_name()
    if cfg_mod.get_project_dir() is None:
        return {"state": PROJECT_NOT_FOUND, "name": name, "profile_label": "", "error": ""}
    try:
        cfg = cfg_mod.load_config()
    except Exception as exc:  # noqa: BLE001 - invalid override JSON raises by design
        return {"state": PROJECT_INVALID, "name": name, "profile_label": "", "error": str(exc)}
    profile_id = cfg_mod.get_active_profile(cfg)
    label = next((p["label"] for p in cfg_mod.list_profiles() if p["id"] == profile_id), profile_id or "")
    state = PROJECT_OK if cfg_mod.has_project_config() else PROJECT_NO_OVERRIDE
    return {"state": state, "name": name, "profile_label": label, "error": ""}


def list_profiles():
    return _m("audit_config").list_profiles()


def settings_state():
    """Everything the Settings tab shows, as data: profile, rule catalog (+ overridden flag),
    tier budgets, override file path/state."""
    cfg_mod = _m("audit_config")
    cfg = cfg_mod.load_config()
    override = cfg_mod.read_project_config()
    profile_id = cfg_mod.get_active_profile(cfg)
    profile = next((p for p in cfg_mod.list_profiles() if p["id"] == profile_id), None)
    rules = cfg_mod.get_rule_catalog(cfg)
    disabled = set(override.get("disabled_rules", []))
    for r in rules:
        r["overridden"] = r["id"] in disabled or r["id"] in (override.get("rules") or {})
    tiers = []
    for tier, budget in cfg_mod.get_all_tiers(cfg).items():
        tiers.append({"tier": tier, "budget": budget,
                      "texture_group": cfg_mod.get_texture_group(tier, cfg),
                      "lod_group": cfg_mod.get_lod_group(tier, cfg)})
    base = cfg_mod.get_baseline(profile_id)
    return {"profile_id": profile_id, "profile": profile, "profiles": cfg_mod.list_profiles(),
            "rules": rules, "disabled": sorted(disabled), "tiers": tiers,
            "rule_values": dict(cfg_mod.get_all_rules(cfg)), "baseline_rules": dict(base.get("rules", {})),
            "baseline_tiers": base.get("tiers", {}), "baseline_disabled": list(base.get("disabled_rules", [])),
            "has_override": cfg_mod.has_project_config(),
            "override_path": cfg_mod.get_project_config_path(),
            "tag_tiers": list(cfg_mod.get_all_tiers(cfg).keys())}


def save_settings(profile_id, disabled_rules, tier_values, rule_values):
    cfg_mod = _m("audit_config")

    def _save():
        path = cfg_mod.save_edits(profile_id, disabled_rules, tier_values, rule_values)
        return "Saved %s" % path
    return _call("save_settings", _save)


def create_config(profile_id, tag_rules, extra_excluded):
    cfg_mod = _m("audit_config")
    return _call("create_config", lambda: "Created %s" % cfg_mod.create_project_config(
        profile_id, tag_rules=tag_rules, extra_excluded=extra_excluded))


def create_config_from_example():
    """Copy examples/vendor_pack_modular_house.config.json in as the project override."""
    cfg_mod = _m("audit_config")

    def _copy():
        if cfg_mod.has_project_config():
            raise FileExistsError("%s already exists" % cfg_mod.get_project_config_path())
        src = os.path.join(_REPO_DIR, "examples", "vendor_pack_modular_house.config.json")
        if not os.path.isfile(src):   # repo layout: examples/ sits above src/
            src = os.path.join(os.path.dirname(_REPO_DIR), "examples", "vendor_pack_modular_house.config.json")
        dest = cfg_mod.get_project_config_path()
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copyfile(src, dest)
        cfg_mod.reload_config()
        return "Created %s from the example" % dest
    return _call("create_from_example", _copy)


def import_config(path):
    import json
    cfg_mod = _m("audit_config")

    def _import():
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("config root must be a JSON object")
        cfg_mod.write_project_config(data)
        return "Imported %s" % path
    return _call("import_config", _import)


def export_config(path):
    cfg_mod = _m("audit_config")
    return _call("export_config", lambda: (shutil.copyfile(cfg_mod.get_project_config_path(), path),
                                           "Exported to %s" % path)[1])


def list_presets():
    try:
        return _m("audit_config").list_presets()
    except Exception:  # noqa: BLE001 - the Settings tab must still build
        return []


def preset_exists(name):
    cfg_mod = _m("audit_config")
    try:
        return os.path.isfile(os.path.join(cfg_mod.get_presets_dir(), "%s.json" % cfg_mod.clean_preset_name(name)))
    except ValueError:
        return False


def save_preset(name, overwrite=False):
    cfg_mod = _m("audit_config")
    return _call("save_preset", lambda: "Saved preset '%s'" % os.path.basename(
        cfg_mod.save_preset(name, overwrite))[:-5])


def load_preset(name):
    cfg_mod = _m("audit_config")
    return _call("load_preset", lambda: (cfg_mod.load_preset(name),
                                         "Loaded preset '%s' - previous override kept as '%s'"
                                         % (name, cfg_mod.PREVIOUS_PRESET))[1])


def delete_preset(name):
    return _call("delete_preset", lambda: (_m("audit_config").delete_preset(name), "Deleted preset '%s'" % name)[1])


def delete_config():
    cfg_mod = _m("audit_config")

    def _delete():
        os.remove(cfg_mod.get_project_config_path())
        cfg_mod.reload_config()
        return "Deleted the project override - generic defaults are back"
    return _call("delete_config", _delete)


def open_config_file():
    cfg_mod = _m("audit_config")
    path = cfg_mod.get_project_config_path()
    if not os.path.isfile(path):
        return {"ok": False, "msg": "No override file yet: %s" % path}

    def _open():
        filled = cfg_mod.fill_template_if_blank()   # empty file -> editable template
        os.startfile(path)
        return "Opened %s%s" % (path, " (template added)" if filled else "")
    return _call("open_config", _open)


# ---- scan target ----

def scan_root(mode):
    """Content path for a folder-scoped action, or None -> let audit_actions resolve it
    from the Content Browser selection (also the fallback when mode is 'level')."""
    return "/Game" if mode == SCAN_PROJECT else None


def describe_selection():
    """'3 assets selected' style text for the Tag / Fix tabs ('' when nothing)."""
    try:
        n = len(unreal.EditorUtilityLibrary.get_selected_asset_data())
    except Exception:  # noqa: BLE001
        return ""
    return "" if n == 0 else "%d asset%s selected" % (n, "" if n == 1 else "s")


def describe_target(mode):
    if mode == SCAN_LEVEL:
        return "Current level + sublevels"
    if mode == SCAN_PROJECT:
        return "Whole project"
    return _m("audit_actions").describe_scan_target()


# ---- audit ----

def run_audit(mode):
    actions = _m("audit_actions")

    def _run():
        if mode == SCAN_LEVEL:
            actions.run_level_audit_action()
        else:
            actions.run_audit(scan_root(mode))
        report = actions._last_report
        summary = report.summary()
        return ("Audit done - %d assets, %d FAIL / %d WARN" % (
            summary["total"], summary["overall"]["FAIL"], summary["overall"]["WARN"]),
            {"summary": summary})
    return _call("run_audit", _run)


def last_summary():
    report = _m("audit_actions")._last_report
    return report.summary() if report is not None else None


def export_audit():
    actions = _m("audit_actions")

    def _export():
        if actions._last_report is None:
            raise RuntimeError("no audit has been run yet this session")
        _, _, csv_dated, json_dated = actions._last_report.export_all(actions.EXPORT_DIR)
        return "Exported %s / %s" % (os.path.basename(csv_dated), os.path.basename(json_dated))
    return _call("export_audit", _export)


def build_dashboard():
    actions = _m("audit_actions")
    return _call("build_dashboard", lambda: (actions.export_and_build_dashboard(),
                                             "Dashboard built (see the Output Log for details)")[1])


def open_dashboard():
    actions = _m("audit_actions")
    return _call("open_dashboard", lambda: (actions.open_dashboard(), "Opening the dashboard")[1])


def audit_results():
    """Export CSV + JSON, rebuild the dashboard, open it. The action layer only logs its
    failures, so success is judged by the dashboard HTML actually being (re)written."""
    actions = _m("audit_actions")

    def _results():
        if actions._last_report is None:
            raise RuntimeError("no audit has been run yet this session")
        before = os.path.getmtime(actions.HTML_PATH) if os.path.isfile(actions.HTML_PATH) else None
        actions.export_and_build_dashboard()
        if not os.path.isfile(actions.HTML_PATH) or os.path.getmtime(actions.HTML_PATH) == before:
            raise RuntimeError("dashboard was not rebuilt (is Node.js installed? see the Output Log)")
        actions.open_dashboard()
        return "Exported CSV + JSON, built and opened the dashboard"
    return _call("audit_results", _results)


# ---- tagging ----

def tag_preview(root_path):
    boot = _m("tag_existing_content")

    def _preview():
        res = boot.run(root_path=root_path, apply=False)
        return ("Preview: %d would be tagged, %d unmatched folders" % (
            len(res["to_apply"]), len(res["unmatched"])), {"result": _tag_view(res)})
    return _call("tag_preview", _preview)


def tag_apply(root_path):
    boot = _m("tag_existing_content")

    def _apply():
        res = boot.run(root_path=root_path, apply=True)
        return ("Tagged %d asset(s)" % len(res["to_apply"]), {"result": _tag_view(res)})
    return _call("tag_apply", _apply)


def _tag_view(res):
    unmatched = [p for paths in res["unmatched"].values() for p in paths]
    return {"would_tag": len(res["to_apply"]), "unmatched": len(unmatched),
            "already": len(res["already_tagged"]),
            "rows": [(p, tier) for p, _c, tier in res["to_apply"][:50]] + [(p, None) for p in unmatched[:50]]}


def tag_selected(tier):
    boot = _m("tag_existing_content")
    return _call("tag_selected", lambda: "Tagged %s as '%s'" % (
        "%d asset(s)" % len(boot.tag_selection(tier) or []), tier))


def tag_tiers():
    return list(_m("audit_config").get_all_tiers().keys())


# ---- fixing ----

def _fix_msg(label, res):
    if not res:
        return "%s: nothing selected in the Content Browser" % label, {"fix": None}
    applied = res.get("applied")
    fixed = len(applied) if applied is not None else len(res.get("planned", []))
    skipped = len(res.get("skipped_untagged", []))
    failed = len(res.get("failed", []))
    return ("%s: %d fixed, %d skipped (untagged), %d failed" % (label, fixed, skipped, failed),
            {"fix": {"fixed": fixed, "skipped": skipped, "failed": failed}})


def fix_textures(selected):
    actions = _m("audit_actions")
    mod = _m("audit_fix_textures")
    return _call("fix_textures", lambda: _fix_msg(
        "Fix textures", mod.run_selected() if selected else mod.run(actions._resolve(None)[0])))


def fix_meshes(selected, regenerate=False):
    actions = _m("audit_actions")
    mod = _m("audit_fix_meshes")
    label = "Regenerate LODs" if regenerate else "Fix meshes"
    return _call("fix_meshes", lambda: _fix_msg(
        label, mod.run_selected(regenerate_stale=regenerate) if selected
        else mod.run_scope(actions._resolve(None)[0], regenerate_stale=regenerate)))


def mark_lods_tool_generated():
    mod = _m("audit_fix_meshes")

    def _mark():
        res = mod.mark_selected_as_auto_generated()
        return "Marked %d mesh(es) as tool-generated" % len((res or {}).get("marked", []))
    return _call("mark_lods", _mark)


# ---- tiers ----

def count_tiers(root_path="/Game"):
    def _count():
        counts, untagged = _m("build_tier_collections").count_tiers(root_path)
        return "Counted tagged assets (%d untagged)" % untagged, {"counts": counts, "untagged": untagged}
    return _call("count_tiers", _count)


def select_tier(tier, root_path="/Game"):
    paths = []

    def _select():
        paths.extend(_m("build_tier_collections").select_tier(tier, root_path=root_path))
        return "Selected %d '%s' asset(s) in the Content Browser" % (len(paths), tier)
    return _call("select_tier", _select)


# ---- tools ----

def reload_scripts():
    """Reload the backend; the caller (app.py) reloads this package afterwards."""
    return _call("reload_scripts", lambda: (_m("audit_actions").reload_toolkit_modules(),
                                            "Backend modules reloaded")[1])


def verify_api():
    return _call("verify_api", lambda: (_m("audit_verify_api").run(), "API check done - see the Output Log")[1])
