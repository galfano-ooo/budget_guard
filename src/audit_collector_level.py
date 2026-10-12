"""
audit_collector_level.py
------------------------------------------------------------------------------
Default collector: walks the currently open persistent level and its loaded
streaming sublevels, gathering the assets actually referenced by placed
actors — via component traversal (StaticMeshComponent on ANY actor class),
so meshes wrapped in Blueprints (doors, lamps, kitchen cabinets, per the
real project folder structure) are correctly counted as "used," not
reported as orphaned.

Sublevels that exist but aren't currently loaded/visible are reported, not
force-loaded — report-and-skip, per the agreed design.

CONFIDENCE NOTE: this is the least-verified file in the toolkit. Actor/
component enumeration and streaming-level introspection have real API
differences across UE5 releases (EditorLevelLibrary vs. EditorActorSubsystem
being the main one). Every risky call below has a fallback or degrades to
an empty/best-effort result rather than crashing — but this is the file to
test first and most carefully.
------------------------------------------------------------------------------
"""

import unreal
import audit_config

CLASS_TO_CATEGORY = {
    "Texture2D": "Textures",
    "TextureCube": "Textures",
    "StaticMesh": "Meshes",
    "Material": "Materials",
    "MaterialInstanceConstant": "Materials",
}


def collect(cfg=None):
    """Return (result, meta):
    result -> dict category -> list of (asset_path, loaded_object), deduplicated
    meta   -> dict with 'scanned_levels' / 'skipped_levels' for the report header
    """
    cfg = cfg or audit_config.load_config()
    result = {"Textures": [], "Meshes": [], "Materials": []}
    seen_paths = set()

    world = unreal.EditorLevelLibrary.get_editor_world()
    scanned_levels, skipped_levels = _get_loaded_levels(world)

    for actor in _get_all_actors():
        mesh_components = _get_static_mesh_components(actor)
        for comp in mesh_components:
            mesh = _safe_get(comp, "static_mesh")
            if mesh is None:
                continue
            _add_asset(mesh, result, seen_paths, cfg)

            for mat in _get_component_materials(comp):
                if mat is None:
                    continue
                _add_asset(mat, result, seen_paths, cfg)
                _add_material_textures(mat, result, seen_paths, cfg)

    meta = {"scanned_levels": scanned_levels, "skipped_levels": skipped_levels}
    return result, meta


def _add_asset(obj, result, seen_paths, cfg):
    try:
        path = obj.get_path_name().split(".")[0]
    except Exception:
        return
    if not path.startswith("/Game/"):
        return  # Engine/plugin content isn't project-owned — not tier-scored
    if path in seen_paths or audit_config.is_excluded(path, cfg):
        return
    asset_class = obj.get_class().get_name()
    category = CLASS_TO_CATEGORY.get(asset_class)
    if category is None:
        return
    seen_paths.add(path)
    result[category].append((path, obj))


def _add_material_textures(mat, result, seen_paths, cfg):
    # CONFIRMED on this fork (Sept 2026): MaterialEditingLibrary.get_used_textures
    # throws a TypeError on MaterialInstanceConstant — it only accepts base
    # Material objects ("Cannot nativize 'MaterialInstanceConstant' as
    # 'Material'"). Since this project's convention is "few masters, many
    # instances," that function was never going to work here — this was the
    # real bug behind Textures showing 0 scanned on the first two real runs.
    #
    # texture_parameter_values is the real source: an array of
    # TextureParameterValue structs, each holding the actual texture object
    # in .parameter_value. Works on instances; wrapped defensively in case a
    # base Material (which stores parameters differently) reaches this path.
    #
    # Known limitation, not yet confirmed either way: unclear whether this
    # only lists textures this specific instance overrides, or also
    # inherited-but-unmodified parameters from its parent. If some textures
    # are still missing from later audit runs, this is the first place to
    # check.
    try:
        tpv = mat.get_editor_property("texture_parameter_values")
    except Exception:
        tpv = []
    for entry in tpv:
        try:
            tex = entry.parameter_value
        except Exception:
            continue
        if tex is not None:
            _add_asset(tex, result, seen_paths, cfg)


def _get_all_actors():
    # Newer (5.x) API first, falls back to the older library for
    # engine/fork versions where the subsystem path isn't available.
    try:
        subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        return subsystem.get_all_level_actors()
    except Exception:
        pass
    try:
        return unreal.EditorLevelLibrary.get_all_level_actors()
    except Exception:
        return []


def _get_static_mesh_components(actor):
    try:
        return actor.get_components_by_class(unreal.StaticMeshComponent)
    except Exception:
        return []


def _get_component_materials(comp):
    materials = []
    try:
        num = comp.get_num_materials()
        for i in range(num):
            materials.append(comp.get_material(i))
    except Exception:
        pass
    return materials


def _get_loaded_levels(world):
    """Best-effort: persistent level name plus loaded streaming sublevels.
    Unloaded sublevels are listed as skipped, never force-loaded."""
    scanned = []
    skipped = []
    try:
        persistent = world.get_editor_property("persistent_level")
        scanned.append(persistent.get_outer().get_name())
    except Exception:
        scanned.append("(current persistent level — name lookup failed, verify API)")

    try:
        for sl in world.get_streaming_levels():
            try:
                name = str(sl.get_world_asset_package_name())
            except Exception:
                name = "(unnamed sublevel)"
            try:
                loaded = sl.is_level_loaded()
            except Exception:
                loaded = None
            if loaded is False:
                skipped.append(name)
            else:
                # loaded == True, or unknown (None) — include it rather than
                # silently dropping a sublevel we couldn't confirm either way.
                scanned.append(name)
    except Exception:
        pass  # streaming-level enumeration unsupported/failed — degrade gracefully

    return scanned, skipped


def _safe_get(obj, prop_name):
    try:
        return obj.get_editor_property(prop_name)
    except Exception:
        return None
