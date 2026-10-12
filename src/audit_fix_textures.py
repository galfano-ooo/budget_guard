"""
audit_fix_textures.py
------------------------------------------------------------------------------
"Fix Textures" — applies mechanical, deterministic corrections for the three
texture-side rules in audit_rules_textures.py, on demand (never as a side
effect of auditing).

UNLIKE tag_existing_content.py's folder-wide bootstrap sweep, this is NOT a
dry-run-by-default action gated on a separate preview step — the panel exposes
it as a single "Fix Textures" action that writes immediately (same reasoning
as tag_selection()'s immediate per-selection writes). What makes a broad
blind sweep safe here isn't a preview step, it's that **assets with no BudgetTier tag are skipped outright** — there is
nothing to guess a tier for, so there is nothing risky to apply. This mirrors
the toolkit's standing rule that a tier is never silently guessed (see
tag_existing_content.py's UNMATCHED handling) — audit_run.py's read-only
fallback to default_tier for reporting purposes does NOT apply here, because
this action writes.

Scope:    3D Environment / Rendering pipeline only.

------------------------------------------------------------------------------
USAGE (from the UE5 Python console):

    import importlib
    import audit_fix_textures as fix
    importlib.reload(fix)

    # Writes immediately (apply=True is the default here, unlike
    # tag_existing_content.py) — untagged assets are skipped, not guessed.
    fix.run("/Game/MyContent")

    # Optional dry-run for a first look before trusting this at scale:
    fix.run("/Game/MyContent", apply=False)

    # Selection-scoped counterpart — only the Texture2D asset(s) currently
    # selected in the Content Browser, nothing implied from their folder:
    fix.run_selected()
    fix.run_selected(apply=False)  # dry-run

    # One-off cleanup for a bulk-import root cause: clamps
    # max_texture_size even on tiers with a custom TextureGroup configured
    # (e.g. background). See WHAT THIS FIXES point 2 below before using this.
    fix.run("/Game/MyContent", apply=False, force_resolution=True)  # preview first

------------------------------------------------------------------------------
WHAT THIS FIXES, AND WHY THE RESOLUTION FIX IS CONDITIONAL:

0. UNTAGGED ASSETS ARE SKIPPED ENTIRELY — no fix is planned or applied for a
   texture with no BudgetTier metadata tag, listed separately in the report
   under "SKIPPED — UNTAGGED". Tag it first (bootstrap sweep or a manual
   tag-selected click in the Tag tab), then re-run Fix Textures.

1. TEXTURE GROUP — assigns the custom unreal.TextureGroup configured per tier
   in audit_budgets.json's "texture_groups" section, to any texture still on
   one of the engine-default groups listed in "default_texture_groups"
   (TEXTUREGROUP_WORLD, TEXTUREGROUP_WORLD_NORMAL_MAP, ... — mirrors
   audit_rules_textures.py's "texture_group_unassigned" check). This is
   evaluated FIRST because it decides whether fix #2 below applies at all.

2. RESOLUTION OVERRIDE (max_texture_size) — applied ONLY to textures whose
   tier has NO custom texture group configured (today: "utility"). For tiers
   WITH a custom group, the resolution budget is meant to be enforced once,
   centrally, via that TextureLODGroup's MaxLODSize in the UE project's
   DefaultEngine.ini — NOT also per-asset here. Setting both would create two
   overlapping sources of truth, and a non-zero per-asset max_texture_size
   always wins over the group's setting, which would make the custom group
   pointless for resolution purposes. See docs/USER_MANUAL.md ("One-time engine
   setup") for the ini snippet this depends on (a manual step, outside this repo).

   force_resolution=True (run()'s parameter) bypasses this gate for a
   deliberate one-off cleanup pass — e.g. a ~110-fail
   bulk-import root cause, where the studio decided the oversized textures
   are a real content mistake to correct directly rather than something to
   paper over via TextureGroup governance while the ini setup is pending.
   Re-run without force_resolution once the ini is configured, so grouped
   tiers go back to the single-source-of-truth path.

   NOTE: audit_rules_textures.py's "resolution_over_budget" finding compares
   the *imported* width/height against budget, not the effective size after
   either clamp — so this fix (either branch) will NOT make that finding
   disappear from a subsequent audit run. It corrects the real runtime
   behavior; the audit's resolution check measuring source size instead of
   effective size is a pre-existing limitation, not something this module
   changes.

3. SRGB ON NORMAL MAP — same detection heuristic as
   audit_rules_textures.audit_texture() (compression_settings == TC_NORMALMAP,
   or "normal" in the filename), turns srgb off. Independent of tier/group,
   applies uniformly.

CONFIDENCE NOTE: max_texture_size has never been read/written by this toolkit
before — run audit_verify_api.run() and check the "Manual checks" section
(load a real Texture2D, print get_editor_property('max_texture_size')) before
trusting this at scale. The TEXTUREGROUP_PROJECTxx enum members are likewise
unverified until audit_verify_api.run()'s TextureGroup dump shows them as
present on this fork/ini.
------------------------------------------------------------------------------
"""

import unreal
from collections import defaultdict

import audit_config
import audit_collector_folder


# ---------------------------------------------------------------------------
# Tag lookup — deliberately NOT audit_run.py's _get_tier() (which falls back
# to default_tier for untagged assets, correct for a read-only audit report
# but wrong here: this module writes, and the toolkit's standing rule is to
# never silently guess a tier for a write — see module docstring, point 0).
# ---------------------------------------------------------------------------

def _get_tag(asset_obj, cfg):
    """Returns the asset's raw BudgetTier tag, or None if untagged — no
    default_tier fallback, on purpose."""
    tag_key = audit_config.get_tag_key(cfg)
    return unreal.EditorAssetLibrary.get_metadata_tag(asset_obj, tag_key) or None


def _safe_get(obj, prop_name):
    try:
        return obj.get_editor_property(prop_name)
    except Exception:
        return None


def _default_group_enums(cfg):
    """Resolve audit_config's configured 'default_texture_groups' names to
    actual unreal.TextureGroup enum members present on this fork, silently
    skipping any that don't exist. Mirrors audit_rules_textures.py's helper
    of the same name — kept as a duplicate per this module's existing
    convention of not importing rule-module internals (see module
    docstring)."""
    names = audit_config.get_default_texture_groups(cfg)
    return {getattr(unreal.TextureGroup, name, None) for name in names} - {None}


# ---------------------------------------------------------------------------
# Planning — decide what would change, without writing anything
# ---------------------------------------------------------------------------

def _plan_texture(asset_path, texture, tier, cfg, force_resolution=False):
    """Return a list of (fix_type, prop_name, new_value, note) tuples planned
    for this texture. fix_type is one of "TEXTURE_GROUP", "RESOLUTION",
    "SRGB", or a special "GROUP_MISSING" entry (not applied, just reported).

    force_resolution=True bypasses the "only ungrouped tiers get a
    max_texture_size override" rule below — a one-off escape hatch for
    correcting a genuine bulk-import mistake (~110 fails on the pilot project,
    background-tier textures imported at 2048-4096px against a 512px
    budget) before the DefaultEngine.ini TextureGroup setup is in place.
    Not the default: once that ini setup lands, the group's MaxLODSize is
    meant to be the single source of truth for grouped tiers (see module
    docstring, point 2)."""
    plans = []

    group_name = audit_config.get_texture_group(tier, cfg)
    lod_group = _safe_get(texture, "lod_group")

    # Checked against every engine-default group configured in
    # audit_budgets.json's "default_texture_groups", not just
    # TEXTUREGROUP_WORLD — a normal map imported with no explicit group
    # lands on TEXTUREGROUP_WORLD_NORMAL_MAP, so a WORLD-only check silently
    # never assigned normal maps their tier's custom group (see
    # audit_rules_textures.py's matching helper for the full story).
    if group_name and lod_group in _default_group_enums(cfg):
        group_enum = getattr(unreal.TextureGroup, group_name, None)
        if group_enum is None:
            plans.append((
                "GROUP_MISSING", None, None,
                f"tier '{tier}' configured for '{group_name}' but this enum "
                f"member doesn't exist on this fork/ini — check DefaultEngine.ini "
                f"and audit_verify_api.py's TextureGroup dump",
            ))
        else:
            plans.append(("TEXTURE_GROUP", "lod_group", group_enum, f"tier '{tier}'"))

    # Resolution override — only for tiers with no custom group at all. A
    # tier with group_name set is considered group-governed regardless of
    # whether this texture already carries that group or still needs it
    # assigned above (see module docstring, point 2, for the rationale) —
    # unless force_resolution explicitly opts out of that gate (see this
    # function's docstring).
    if group_name is None or force_resolution:
        budget = audit_config.get_tier_budget(tier, cfg)
        budget_res = budget.get("max_texture_resolution")
        if budget_res:
            width = texture.blueprint_get_size_x()
            height = texture.blueprint_get_size_y()
            max_res = max(width, height)
            if max_res > budget_res:
                current = _safe_get(texture, "max_texture_size")
                if current != budget_res:
                    plans.append((
                        "RESOLUTION", "max_texture_size", budget_res,
                        f"{width}x{height} exceeds '{tier}' tier budget ({budget_res}px)",
                    ))

    # sRGB on normal map — independent of tier/group
    srgb = _safe_get(texture, "srgb")
    compression = _safe_get(texture, "compression_settings")
    filename = asset_path.lower().rsplit("/", 1)[-1]
    looks_like_normal = "normal" in filename
    is_normal_map = (
        compression == unreal.TextureCompressionSettings.TC_NORMALMAP
        or looks_like_normal
    )
    if is_normal_map and srgb:
        plans.append(("SRGB", "srgb", False, "sRGB enabled on what looks like a normal map"))

    return plans


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def _collect_and_plan(items, cfg, force_resolution=False):
    """Shared planning core behind run() and run_selected() — items is a
    list of (asset_path, texture_obj) from either a folder collector walk
    or a live Content Browser selection, the two entry points' only real
    difference. Returns (planned, skipped_cube, skipped_untagged,
    group_missing), same shape both callers report/apply from."""
    planned = []           # (asset_path, fix_type, prop_name, new_value, note)
    skipped_cube = []      # TextureCube — resolution/srgb/group rules don't apply
    skipped_untagged = []  # no BudgetTier tag — never guessed, see module docstring
    group_missing = []     # (asset_path, note) — configured group doesn't exist on this fork

    for asset_path, texture in items:
        if not isinstance(texture, unreal.Texture2D):
            skipped_cube.append(asset_path)
            continue

        tier = _get_tag(texture, cfg)
        if tier is None:
            skipped_untagged.append(asset_path)
            continue

        for fix_type, prop_name, new_value, note in _plan_texture(
            asset_path, texture, tier, cfg, force_resolution=force_resolution
        ):
            if fix_type == "GROUP_MISSING":
                group_missing.append((asset_path, note))
                continue
            planned.append((asset_path, fix_type, prop_name, new_value, note))

    return planned, skipped_cube, skipped_untagged, group_missing


def _apply_planned(planned):
    """Writes every planned fix immediately — shared by run() and
    run_selected() so the actual property-write path only exists once."""
    for asset_path, _fix_type, prop_name, new_value, _note in planned:
        texture = unreal.load_asset(asset_path)
        texture.set_editor_property(prop_name, new_value)
        unreal.EditorAssetLibrary.save_asset(asset_path, only_if_is_dirty=True)


def run(root_path, apply=True, force_resolution=False):
    """
    Scan root_path for Texture2D assets, plan the fixes described in this
    module's docstring, and write them immediately (apply=True, the
    default — this action is meant to run as a single panel click, not
    a preview/apply pair; see module docstring). Pass apply=False for an
    optional dry-run look at the plan first.

    force_resolution=True applies the max_texture_size override to EVERY
    over-budget texture, including tiers with a custom TextureGroup
    configured — see _plan_texture()'s docstring for why this exists and
    when to use it (default False keeps the original group-governed
    behavior).

    Untagged assets are never fixed — see _get_tag()'s docstring.

    See run_selected() for the Content-Browser-selection-scoped
    counterpart — same plan/report/apply shape, different asset source.
    """
    cfg = audit_config.load_config()
    collected = audit_collector_folder.collect(root_path, cfg)

    planned, skipped_cube, skipped_untagged, group_missing = _collect_and_plan(
        collected["Textures"], cfg, force_resolution=force_resolution
    )

    _print_report(root_path, planned, skipped_cube, skipped_untagged, group_missing, apply, force_resolution)

    if apply:
        _apply_planned(planned)
        unreal.log(f"[Fix Textures] Applied {len(planned)} fix(es).")
    else:
        unreal.log(
            "[Fix Textures] DRY RUN — no changes written. "
            "Re-run with apply=True (or no argument) to write."
        )

    return {
        "planned": planned,
        "skipped_cube": skipped_cube,
        "skipped_untagged": skipped_untagged,
        "group_missing": group_missing,
    }


def run_selected(apply=True, force_resolution=False):
    """Fixes only the Texture2D asset(s) currently selected in the Content
    Browser — NOT their containing folder (same convention as
    audit_fix_meshes.run_selected()). Same plan/report/apply shape and
    untagged/TextureCube-skip rules as run() — the only difference is the
    scope source (explicit live selection vs. a collector walk over
    root_path).

    Use this for a handful of textures picked by hand when you want to
    confirm exactly what's about to be touched before writing anything;
    use run() (the "Fix Textures (Scope)" button) for a folder/whole-
    project sweep."""
    cfg = audit_config.load_config()

    try:
        asset_data_list = unreal.EditorUtilityLibrary.get_selected_asset_data()
    except AttributeError:
        asset_data_list = []

    if not asset_data_list:
        unreal.log("[Fix Textures] Nothing selected in the Content Browser.")
        return None

    items = []
    for asset_data in asset_data_list:
        obj = unreal.load_asset(str(asset_data.package_name))
        if obj is not None:
            items.append((str(asset_data.package_name), obj))

    planned, skipped_cube, skipped_untagged, group_missing = _collect_and_plan(
        items, cfg, force_resolution=force_resolution
    )

    label = f"{len(asset_data_list)} selected asset(s)"
    _print_report(label, planned, skipped_cube, skipped_untagged, group_missing, apply, force_resolution)

    if apply:
        _apply_planned(planned)
        unreal.log(f"[Fix Textures] Applied {len(planned)} fix(es).")
    else:
        unreal.log(
            "[Fix Textures] DRY RUN — no changes written. "
            "Re-run with apply=True (or no argument) to write."
        )

    return {
        "planned": planned,
        "skipped_cube": skipped_cube,
        "skipped_untagged": skipped_untagged,
        "group_missing": group_missing,
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

_FIX_ORDER = ["TEXTURE_GROUP", "RESOLUTION", "SRGB"]
_FIX_LABELS = {
    "TEXTURE_GROUP": "TEXTURE GROUP",
    "RESOLUTION": "RESOLUTION OVERRIDE",
    "SRGB": "SRGB ON NORMAL MAP",
}


def _print_report(root_path, planned, skipped_cube, skipped_untagged, group_missing, apply, force_resolution=False):
    mode = "APPLY" if apply else "DRY RUN (preview only, nothing written)"
    print("=" * 78)
    print(f"Fix Textures — {mode}")
    print(f"Scope: {root_path}")
    if force_resolution:
        print("force_resolution=True — resolution override applied to ALL tiers, "
              "including grouped ones (bypasses the ini/TextureGroup gate)")
    print("=" * 78)

    by_fix = defaultdict(list)
    for asset_path, fix_type, _prop_name, new_value, note in planned:
        by_fix[fix_type].append((asset_path, new_value, note))

    for fix_type in _FIX_ORDER:
        entries = by_fix.get(fix_type, [])
        print(f"\n[{_FIX_LABELS[fix_type]}] — {len(entries)} texture(s)")
        print("-" * 78)
        for asset_path, new_value, note in entries[:15]:
            print(f"  {asset_path}  ->  {new_value}  ({note})")
        if len(entries) > 15:
            print(f"  ... and {len(entries) - 15} more")

    print(f"\n[SKIPPED — UNTAGGED, no BudgetTier — never guessed] — {len(skipped_untagged)} asset(s)")
    print("-" * 78)
    for asset_path in skipped_untagged[:10]:
        print(f"  {asset_path}")
    if len(skipped_untagged) > 10:
        print(f"  ... and {len(skipped_untagged) - 10} more")
    if skipped_untagged:
        print("  Tag these first (bootstrap sweep or a manual tag-selected click in the Tag tab), "
              "then re-run Fix Textures.")

    print(f"\n[TEXTURECUBE — skipped, rules don't apply] — {len(skipped_cube)} asset(s)")
    print("-" * 78)
    for asset_path in skipped_cube[:5]:
        print(f"  {asset_path}")
    if len(skipped_cube) > 5:
        print(f"  ... and {len(skipped_cube) - 5} more")

    print(f"\n[TEXTURE GROUP CONFIGURED BUT MISSING ON THIS FORK/INI] — {len(group_missing)} asset(s)")
    print("-" * 78)
    for asset_path, note in group_missing[:10]:
        print(f"  {asset_path}  ({note})")
    if len(group_missing) > 10:
        print(f"  ... and {len(group_missing) - 10} more")

    total = len(planned)
    print("\n" + "=" * 78)
    print(f"SUMMARY: {total} fix(es) planned across {_FIX_ORDER} categories.")
    print("=" * 78)


if __name__ == "__main__":
    run("/Game")
