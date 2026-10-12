"""
audit_rules_textures.py
------------------------------------------------------------------------------
Audit rules for Texture2D assets.

CONFIDENCE NOTE: this module relies on fairly standard, long-stable UE5
Texture2D API (blueprint_get_size_x/y, srgb, compression_settings,
lod_group) — higher confidence than the mesh/material rule modules, but the
exact enum member spellings (TC_NORMALMAP, TEXTUREGROUP_WORLD) are still
worth a quick check via audit_verify_api.py before trusting this at scale.
------------------------------------------------------------------------------
"""

import unreal
import audit_config


def audit_texture(asset_path, texture, tier, cfg=None):
    """Return a list of (severity, message) tuples for one texture asset."""
    cfg = cfg or audit_config.load_config()

    # blueprint_get_size_x/y (and the rules built on it) only exist on
    # Texture2D — TextureCube (HDRIs/skyboxes) reaches this function too
    # since collectors file both under the "Textures" category.
    if not isinstance(texture, unreal.Texture2D):
        return [(
            "INFO",
            f"{texture.get_class().get_name()} — resolution/pow2/sRGB/group rules only apply to Texture2D, skipped",
        )]

    budget = audit_config.get_tier_budget(tier, cfg)
    findings = []

    width = texture.blueprint_get_size_x()
    height = texture.blueprint_get_size_y()
    max_res = max(width, height)

    # Read once, reused by both the resolution check below (to recognize a
    # texture already governed by its tier's custom group) and the "Texture
    # Group still unassigned" check further down.
    lod_group = _safe_get(texture, "lod_group")

    # --- Resolution vs. tier budget ---------------------------------------
    budget_res = budget.get("max_texture_resolution")
    if budget_res and max_res > budget_res and audit_config.is_rule_enabled("resolution_over_budget", cfg):
        # If this texture already carries its tier's configured custom
        # TextureGroup (see audit_budgets.json's "texture_groups" and
        # audit_fix_textures.py), the *effective* runtime resolution is
        # governed by that group's MaxLODSize in DefaultEngine.ini, not by
        # this imported size — flagging FAIL/WARN off the import size alone
        # would be a false alarm once that group is in place. Treated as OK
        # (no finding at all), not INFO: INFO in this toolkit specifically
        # means "couldn't evaluate the rule, API missing" (see
        # audit_report.py's docstring), which isn't the case here — the rule
        # WAS evaluated, it just resolved differently. The residual risk
        # (the ini's MaxLODSize might not actually be configured yet) is a
        # one-time environment-setup concern documented in docs/USER_MANUAL.md ("One-time engine setup"),
        # not something worth re-flagging on every audit run once an asset
        # is correctly grouped.
        configured_group = audit_config.get_texture_group(tier, cfg)
        configured_group_enum = (
            getattr(unreal.TextureGroup, configured_group, None) if configured_group else None
        )
        governed_by_group = configured_group_enum is not None and lod_group == configured_group_enum
        if not governed_by_group:
            severe_multiplier = cfg["rules"].get("severe_multiplier", 2.0)
            severe = max_res > budget_res * severe_multiplier
            rule = "resolution_over_budget_severe" if severe else "resolution_over_budget"
            findings.append((
                audit_config.get_rule_severity(rule, cfg),
                f"{width}x{height} exceeds '{tier}' tier budget ({budget_res}px)",
            ))

    # --- Power-of-two check --------------------------------------------------
    def _is_pow2(n):
        return n > 0 and (n & (n - 1)) == 0

    if not (_is_pow2(width) and _is_pow2(height)):
        findings.append(("WARN", f"{width}x{height} is not power-of-two"))

    # --- sRGB enabled on what looks like a normal map -------------------------
    srgb = _safe_get(texture, "srgb")
    compression = _safe_get(texture, "compression_settings")
    filename = asset_path.lower().rsplit("/", 1)[-1]
    # "_n" alone is too broad (matches "_noise", "_nosignal", etc.) — this
    # pack's normal maps consistently use the "_Normal" suffix, so "normal"
    # alone is both sufficient and specific.
    looks_like_normal = "normal" in filename
    is_normal_map = (
        compression == unreal.TextureCompressionSettings.TC_NORMALMAP
        or looks_like_normal
    )
    if is_normal_map and srgb and audit_config.is_rule_enabled("srgb_on_normal_map", cfg):
        findings.append((
            audit_config.get_rule_severity("srgb_on_normal_map", cfg),
            "sRGB enabled on what looks like a normal map",
        ))

    # --- Texture Group still unassigned (an engine-default group) -------------
    # Direct enum comparison, confirmed against this fork via
    # audit_verify_api.py (Sept 2026) — the previous string-strip check
    # never matched because of the "<TextureGroup.X: n>" repr wrapper.
    # (lod_group already read above, reused here.)
    #
    # Checked against the full set of engine-default groups
    # (audit_config.get_default_texture_groups), not just TEXTUREGROUP_WORLD:
    # UE auto-assigns a normal map to TEXTUREGROUP_WORLD_NORMAL_MAP on import,
    # never WORLD, so a WORLD-only check silently never flagged normal maps
    # as unassigned (found the hard way).
    if lod_group in _default_group_enums(cfg) and audit_config.is_rule_enabled("texture_group_unassigned", cfg):
        findings.append((
            audit_config.get_rule_severity("texture_group_unassigned", cfg),
            "still on an engine-default texture group — no project-specific group assigned",
        ))

    return findings


def _safe_get(obj, prop_name):
    try:
        return obj.get_editor_property(prop_name)
    except Exception:
        return None


def _default_group_enums(cfg):
    """Resolve audit_config's configured 'default_texture_groups' names to
    actual unreal.TextureGroup enum members present on this fork, silently
    skipping any that don't exist (see audit_verify_api.py's TextureGroup
    dump before trusting a newly-added name here)."""
    names = audit_config.get_default_texture_groups(cfg)
    return {getattr(unreal.TextureGroup, name, None) for name in names} - {None}
