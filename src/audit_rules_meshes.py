"""
audit_rules_meshes.py
------------------------------------------------------------------------------
Audit rules for StaticMesh assets.

CONFIDENCE NOTE: triangle-count and Nanite-detection are the most version-
fragile calls in this whole toolkit — the exact Python-exposed method for
"triangle count at a given LOD" has shifted across UE5 releases. Each risky
call is wrapped defensively: if the expected API isn't found, you get a
single INFO-level finding telling you to check manually, instead of the
whole audit crashing on the first mesh. Run audit_verify_api.py first and
adjust the marked candidate calls below if none of them work on your fork.
------------------------------------------------------------------------------
"""

import unreal
import audit_config


def _get_asset_data(asset_path):
    try:
        return unreal.EditorAssetLibrary.find_asset_data(asset_path)
    except Exception:
        return None


def _get_tag_int(asset_path, tag_name):
    """Reads an Asset Registry tag and parses it as int. Registry tags are
    generally stored as strings regardless of the underlying type, so this
    handles both a raw int and a numeric string without needing to know
    which one a given fork/version returns."""
    ad = _get_asset_data(asset_path)
    if ad is None:
        return None
    try:
        raw = ad.get_tag_value(tag_name)
        if raw is None or raw == "":
            return None
        return int(raw)
    except Exception:
        return None


def _get_tag_bool(asset_path, tag_name):
    ad = _get_asset_data(asset_path)
    if ad is None:
        return None
    try:
        raw = ad.get_tag_value(tag_name)
        if raw is None:
            return None
        if isinstance(raw, bool):
            return raw
        return str(raw).strip().lower() == "true"
    except Exception:
        return None


def audit_mesh(asset_path, mesh, tier, cfg=None):
    cfg = cfg or audit_config.load_config()
    budget = audit_config.get_tier_budget(tier, cfg)
    findings = []

    # --- Nanite enabled ------------------------------------------------------
    nanite_enabled = _get_nanite_enabled(asset_path, mesh)
    if nanite_enabled is None:
        findings.append(("INFO", "could not determine Nanite state via tag or property — verify manually"))
    elif nanite_enabled and audit_config.is_rule_enabled("nanite_enabled", cfg):
        findings.append((
            audit_config.get_rule_severity("nanite_enabled", cfg),
            "Nanite is enabled (the config forbids it; set rules.nanite_enabled to \"OFF\" to allow it)",
        ))

    # --- LOD count / triangle count -------------------------------------------
    lod_count = _get_lod_count(mesh)
    tri_count = _get_triangle_count(asset_path, mesh, lod_index=0)

    if lod_count is None:
        findings.append(("INFO", "could not determine LOD count — verify EditorStaticMeshLibrary.get_lod_count"))
    if tri_count is None:
        vert_ref = _get_vertex_count_reference(mesh, lod_index=0)
        extra = f" (LOD0 vertex count for rough reference only: {vert_ref})" if vert_ref is not None else ""
        findings.append((
            "INFO",
            "no 'Triangles' registry tag and no library fallback worked for this asset" + extra,
        ))

    if lod_count is not None and tri_count is not None:
        threshold = cfg["rules"].get("missing_lod_triangle_threshold", 3000)
        if lod_count <= 1 and tri_count > threshold and audit_config.is_rule_enabled("missing_lod", cfg):
            findings.append((
                audit_config.get_rule_severity("missing_lod", cfg),
                f"{tri_count} triangles at LOD0, only {lod_count} LOD(s) authored",
            ))

    # --- Triangle count vs. tier budget -----------------------------------------
    max_tri = budget.get("max_triangles")
    if tri_count is not None and max_tri and audit_config.is_rule_enabled("triangle_count_over_budget", cfg):
        severe_multiplier = cfg["rules"].get("severe_multiplier", 2.0)
        if tri_count > max_tri:
            severe = tri_count > max_tri * severe_multiplier
            rule = "triangle_count_over_budget_severe" if severe else "triangle_count_over_budget"
            findings.append((
                audit_config.get_rule_severity(rule, cfg),
                f"{tri_count} triangles exceeds '{tier}' tier budget ({max_tri})",
            ))

    # --- Collision complexity ----------------------------------------------------
    complex_as_simple = _get_complex_as_simple(mesh)
    if complex_as_simple and audit_config.is_rule_enabled("complex_as_simple_collision", cfg):
        findings.append((
            audit_config.get_rule_severity("complex_as_simple_collision", cfg),
            "collision set to 'Use Complex as Simple'",
        ))

    return findings


def _get_nanite_enabled(asset_path, mesh):
    # Confirmed working on this fork (Sept 2026): the "NaniteEnabled"
    # Asset Registry tag. Tried first since it's confirmed; the
    # nanite_settings property path below was never actually verified
    # against a real asset, so it's now just a fallback.
    tag_val = _get_tag_bool(asset_path, "NaniteEnabled")
    if tag_val is not None:
        return tag_val
    try:
        nanite_settings = mesh.get_editor_property("nanite_settings")
        return bool(nanite_settings.get_editor_property("enabled"))
    except Exception:
        return None


def _get_lod_count(mesh):
    try:
        return unreal.EditorStaticMeshLibrary.get_lod_count(mesh)
    except Exception:
        return None


def _get_triangle_count(asset_path, mesh, lod_index=0):
    # Confirmed working on this fork (Sept 2026): the "Triangles" Asset
    # Registry tag — the same source Content Browser's own Triangles column
    # reads from. This resolved a real gap: neither get_lod_triangle_count
    # nor get_number_triangles exist on EditorStaticMeshLibrary here.
    #
    # Note: this reflects whatever LOD Content Browser reports (typically
    # LOD0 / highest-detail) — treat lod_index as informational only, this
    # path doesn't actually select a specific LOD.
    tri = _get_tag_int(asset_path, "Triangles")
    if tri is not None:
        return tri
    # Kept as a fallback in case the tag is absent on some asset type —
    # these were confirmed NOT to exist on this fork's library, so treat
    # reaching this point as "something unexpected," not the normal path.
    candidates = [
        lambda: unreal.EditorStaticMeshLibrary.get_lod_triangle_count(mesh, lod_index),
        lambda: unreal.EditorStaticMeshLibrary.get_number_triangles(mesh, lod_index),
    ]
    for fn in candidates:
        try:
            return fn()
        except Exception:
            continue
    return None


def _get_vertex_count_reference(mesh, lod_index=0):
    """NOT a triangle-count substitute. Vertex count at a given LOD, for a
    rough, explicitly-labeled reference only — surfaced separately so it's
    never mistaken for a real triangle-budget number."""
    try:
        return unreal.EditorStaticMeshLibrary.get_number_verts(mesh, lod_index)
    except Exception:
        return None


def _get_complex_as_simple(mesh):
    try:
        body_setup = mesh.get_editor_property("body_setup")
        flag = body_setup.get_editor_property("collision_trace_flag")
        # Direct enum comparison — confirmed against this project's fork via
        # audit_verify_api.py (Sept 2026): CollisionTraceFlag prints as
        # "<CollisionTraceFlag.CTF_USE_COMPLEX_AS_SIMPLE: 3>", which broke
        # the previous string-suffix check. Comparing the enum value itself
        # sidesteps that entirely.
        return flag == unreal.CollisionTraceFlag.CTF_USE_COMPLEX_AS_SIMPLE
    except Exception:
        return False
