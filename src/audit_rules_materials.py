"""
audit_rules_materials.py
------------------------------------------------------------------------------
Audit rules for Material / MaterialInstanceConstant assets.

v1 scope is deliberately narrow: blend_mode and two_sided are standard,
long-stable UPROPERTY names on UMaterialInterface, so confidence here is
high. Sampler-count and shading-model checks need to walk the material
expression graph (via MaterialEditingLibrary) — that's the part of the
Material API most likely to need real, engine-version-specific work, so
it's deferred to v2 rather than shipped half-verified.
------------------------------------------------------------------------------
"""

"""
audit_rules_materials.py
------------------------------------------------------------------------------
Audit rules for Material / MaterialInstanceConstant assets.

CONFIRMED on this project's fork (Sept 2026): MaterialInstanceConstant does
NOT expose blend_mode / two_sided as direct properties (the earlier version
of this file silently failed on every single instance because of this).
They live inside a 'base_property_overrides' struct, active only when the
matching 'override_X' flag is true. When not overridden, the effective
value comes from the parent material — which may itself be another
instance, hence the walk-up-the-chain approach below.
------------------------------------------------------------------------------
"""

import unreal
import audit_config

TRANSLUCENT_LIKE_MODES = (
    unreal.BlendMode.BLEND_TRANSLUCENT,
    unreal.BlendMode.BLEND_ADDITIVE,
    unreal.BlendMode.BLEND_MODULATE,
)


def audit_material(asset_path, mat, tier, cfg=None):
    cfg = cfg or audit_config.load_config()
    findings = []

    blend_mode = _resolve_effective(mat, "blend_mode")
    if blend_mode in TRANSLUCENT_LIKE_MODES and audit_config.is_rule_enabled("translucent_material", cfg):
        findings.append((
            audit_config.get_rule_severity("translucent_material", cfg),
            f"effective blend mode is {blend_mode} — translucency should stay tightly scoped per project guidance",
        ))

    two_sided = _resolve_effective(mat, "two_sided")
    if two_sided and audit_config.is_rule_enabled("two_sided_material", cfg):
        findings.append((
            audit_config.get_rule_severity("two_sided_material", cfg),
            "two-sided is enabled (effective value, possibly inherited from parent) — extra shading cost under mobile forward rendering",
        ))

    return findings


def _resolve_effective(material_interface, prop_name, max_depth=10):
    """Walk up the instance parent chain to find the effective value of a
    property MaterialInstanceConstant only stores as an optional override.
    Base Material always has the property directly. Returns None if nothing
    could be resolved within max_depth hops (guards against a malformed or
    circular parent chain)."""
    obj = material_interface
    depth = 0
    while obj is not None and depth < max_depth:
        depth += 1
        class_name = obj.get_class().get_name()
        if class_name == "MaterialInstanceConstant":
            try:
                overrides = obj.get_editor_property("base_property_overrides")
                if overrides.get_editor_property(f"override_{prop_name}"):
                    return overrides.get_editor_property(prop_name)
            except Exception:
                pass
            try:
                obj = obj.get_editor_property("parent")
            except Exception:
                return None
        else:
            try:
                return obj.get_editor_property(prop_name)
            except Exception:
                return None
    return None
