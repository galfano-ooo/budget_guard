"""
audit_run.py
------------------------------------------------------------------------------
Entry point for running the v1 audit manually from the UE5 Python console.

USAGE:
    import audit_run
    import importlib; importlib.reload(audit_run)

    # Default scope: current level + loaded sublevels
    audit_run.run_level_audit()

    # Alternative scope: a specific folder, or the whole /Game tree
    audit_run.run_folder_audit("/Game/MyContent")
    audit_run.run_folder_audit("/Game")
------------------------------------------------------------------------------
"""

import unreal

import audit_config
from audit_report import Report, Finding
import audit_rules_textures
import audit_rules_meshes
import audit_rules_materials
import audit_collector_level
import audit_collector_folder


def run_level_audit():
    cfg = audit_config.load_config()
    collected, meta = audit_collector_level.collect(cfg)

    report = Report(scope_label="Current level + loaded sublevels")
    for lvl in meta.get("skipped_levels", []):
        report.note_skipped_sublevel(lvl)

    _run_rules(collected, report, cfg)
    report.print_console()
    return report


def run_folder_audit(root_path):
    cfg = audit_config.load_config()
    collected = audit_collector_folder.collect(root_path, cfg)

    report = Report(scope_label=f"Folder scan: {root_path}")
    _run_rules(collected, report, cfg)
    report.print_console()
    return report


def _get_tier(asset_obj, cfg):
    tag_key = audit_config.get_tag_key(cfg)
    tier = unreal.EditorAssetLibrary.get_metadata_tag(asset_obj, tag_key)
    if not tier:
        return audit_config.get_default_tier(cfg), True   # (tier, was_untagged)
    return tier, False


def _run_rules(collected, report, cfg):
    for asset_path, tex in collected["Textures"]:
        tier, untagged = _get_tier(tex, cfg)
        tex_class = tex.get_class().get_name()
        report.mark_scanned("Textures", asset_path, asset_class=tex_class, tier=tier)
        if untagged:
            report.mark_untagged("Textures", asset_path)
        for severity, message in audit_rules_textures.audit_texture(asset_path, tex, tier, cfg):
            report.add(Finding(asset_path, tex_class, "Textures", "", severity, message))

    for asset_path, mesh in collected["Meshes"]:
        tier, untagged = _get_tier(mesh, cfg)
        report.mark_scanned("Meshes", asset_path, asset_class="StaticMesh", tier=tier)
        if untagged:
            report.mark_untagged("Meshes", asset_path)
        for severity, message in audit_rules_meshes.audit_mesh(asset_path, mesh, tier, cfg):
            report.add(Finding(asset_path, "StaticMesh", "Meshes", "", severity, message))

    for asset_path, mat in collected["Materials"]:
        tier, untagged = _get_tier(mat, cfg)
        mat_class = mat.get_class().get_name()
        report.mark_scanned("Materials", asset_path, asset_class=mat_class, tier=tier)
        if untagged:
            report.mark_untagged("Materials", asset_path)
        for severity, message in audit_rules_materials.audit_material(asset_path, mat, tier, cfg):
            report.add(Finding(asset_path, mat_class, "Materials", "", severity, message))


if __name__ == "__main__":
    run_level_audit()
