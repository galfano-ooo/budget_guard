"""
audit_fix_meshes.py
------------------------------------------------------------------------------
"Fix Meshes" — mechanical, deterministic corrections for over-budget
StaticMesh assets, mirroring audit_fix_textures.py's shape (plan -> report ->
apply, untagged assets always skipped, never guessed).

Three independent fixes, all gated on the asset already carrying a
BudgetTier tag (see _get_tag()'s docstring — same "never guess a tier for a
write" rule as audit_fix_textures.py):

1. LOD_GROUP — deliberately DIFFERENT policy from audit_fix_textures.py's
   TEXTURE_GROUP fix. Unlike a texture's group (an editorial choice worth
   preserving if already customized), a mesh's LOD Group here IS the
   BudgetTier, restated in the engine's own LOD-Group mechanism — so this
   fix ALWAYS enforces the tier's configured LOD Group name
   (audit_budgets.json's "lod_groups" section), overriding whatever the
   mesh currently has, including a vendor pack's own pre-existing
   convention (observed 2026-09-09 on a real asset: a mesh tagged
   `architecture` still carrying the vendor's own "Deco" LOD Group from
   import) or the unassigned default ("None"). Single source of truth is
   `lod_groups[tier]` in audit_budgets.json, full stop — a mesh's LOD Group
   is never left to whatever the original asset happened to import with.
   Purely organizational until a matching `+LODGroups=(Name="...", ...)`
   entry is hand-added to the target project's DefaultEngine.ini (same
   ini-prerequisite pattern as TEXTUREGROUP_PROJECTxx, see docs/USER_MANUAL.md
   "One-time engine setup") — until then this writes the tag but it has no runtime effect. All
   tier values are `null` placeholders in audit_budgets.json until Tech Art
   defines real profiles; until then this fix plans nothing for any tier.

2. LOD_GENERATION — the live-confirmed fix (confirmed 2026-09-09 against a real
   over-budget mesh, SM_Stairs_straight_L_railing, both numerically and by
   eye in the Static Mesh Editor). Only applied to meshes that are BOTH
   over their tier's max_triangles budget AND still have lod_count <= 1 (no
   hand-authored LODs yet) — the lod_count <= 1 gate is deliberate and
   NON-NEGOTIABLE: set_lods_with_notification() REPLACES the entire LOD
   chain, so running this on a mesh with existing LODs would silently
   destroy any hand-authored LOD work. A mesh with lod_count > 1 is always
   left alone by this fix, regardless of triangle count.
   ALSO gated on _LOD_GENERATION_MAX_SOURCE_TRIANGLES (placeholder, currently
   100,000): a mesh over that ceiling is flagged LOD_GENERATION_TOO_LARGE
   (reported, never auto-applied) instead of run through the reducer —
   confirmed real 2026-09-09 that a whole-project run_scope() can hang the
   Editor for 10+ minutes on one dense-enough mesh, with the progress dialog
   stuck and no way to cancel a rebuild already in flight.
   Uses audit_budgets.json's "lod_generation_targets"[tier].poly_fractions
   (one entry per resulting LOD, LOD0 included) to build the
   StaticMeshReductionOptions/StaticMeshReductionSettings structs.

3. NANITE_DISABLE — disables Nanite on any mesh flagged by the
   "nanite_enabled" rule (mobile/standalone VR targets don't support
   Nanite). Skipped entirely when the config sets rules.nanite_enabled
   to "OFF" - a project that uses Nanite opts out there.
   CONFIDENCE NOTE: writing nanite_settings.enabled has never been
   exercised on this fork before this fix (only ever READ via the
   confirmed-working "NaniteEnabled" registry tag) —
   spot-check the first asset this fix touches by hand (open it in the
   Static Mesh Editor, confirm the Nanite checkbox actually cleared) before
   trusting this at scale, same as audit_fix_textures.py originally shipped
   with max_texture_size unverified and asked the same of the reader.

LOD_REGENERATE — a fourth, OPT-IN-ONLY fix_type addressing the fine-tuning
loop this tool is actually used in: editing "lod_generation_targets"
[tier].poly_fractions and re-running LOD_GENERATION has zero effect on any
mesh already processed, by design (the lod_count <= 1 gate above never
re-opens for a mesh with LODs already, whether tool-generated or hand-
authored — confirmed live 2026-09-09, editing poly_fractions and re-running
Fix Meshes on the whole project reported "0 mesh(es) would be touched").
LOD_REGENERATE closes that loop WITHOUT weakening the hand-authored-LOD
protection: every mesh this fix (re)generates LODs for gets a
_LOD_GEN_TAG_KEY metadata tag recording the exact poly_fractions used. A
mesh is only ever a LOD_REGENERATE candidate if that tag is PRESENT (i.e.
this tool generated its LODs, not an artist or the vendor pack) AND its
recorded fractions differ from the tier's CURRENT poly_fractions — an
untagged mesh with lod_count > 1 is still never touched, same as always.
Only reachable via regenerate_stale=True (run_selected()/run_scope()), never
the default path the plain Fix Meshes buttons use — see those functions'
docstrings. Meshes tool-generated before this feature existed have no tag
yet; mark_selected_as_auto_generated() is the one-time, explicit,
selection-only bridge for those (see its own docstring for why it's
selection-only, never folder/whole-project).

ARTIST REVIEW IS NOT OPTIONAL, NOT A SUGGESTION IN THE UI, AN ACTUAL GAP:
per-LOD triangle counts aren't reliably readable from Python on this fork
(get_lod_triangle_count/get_number_triangles both confirmed absent) — so nothing in this module's report can confirm the
generated LODs are actually good (silhouette, texel density, no holes).
Every mesh this fix touches needs a human look in the Static Mesh Editor
before being considered done.

TWO ENTRY POINTS, DELIBERATELY DIFFERENT SHAPES — see run_selected() and
run_scope()'s docstrings for why a single Content-Browser-selection-resolved
button (audit_fix_textures.py's/tag_existing_content.py's pattern) is NOT
reused here as-is: LOD_GENERATION triggers a real synchronous mesh rebuild
per asset (~3s for a moderate mesh in the 2026-09-09 pilot test) — safe for a
handful of explicitly selected assets, but a real risk of a long editor
freeze (and, on a very large/heavy scope, real instability) if silently run
across an entire folder or the whole project. run_scope() prints an explicit
count + warning before it does anything, and reports progress via the
Output Log (per-asset lines, no modal dialog — see run_scope()'s docstring
for why a ScopedSlowTask dialog is deliberately NOT used here) instead of
leaving the editor looking hung with zero feedback.

Scope:    3D Environment / Rendering pipeline only.
------------------------------------------------------------------------------
USAGE (from the UE5 Python console):

    import importlib
    import audit_fix_meshes as fix
    importlib.reload(fix)

    # Small, explicit scope — select mesh(es) in the Content Browser first:
    fix.run_selected()

    # Whole folder/project — prints a count + warning, then per-asset log lines:
    fix.run_scope("/Game/MyContent/Meshes/Buildings/Stairs")
    fix.run_scope("/Game")  # the whole project — read the warning first

    # Optional dry-run for either entry point before trusting this at scale:
    fix.run_selected(apply=False)
    fix.run_scope("/Game/MyContent", apply=False)
------------------------------------------------------------------------------
"""

import json
import unreal
from collections import defaultdict

import audit_config
import audit_collector_folder


# Placeholder ceiling, same "unvalidated until Tech Art looks at it" status as
# audit_budgets.json's numeric budgets — a mesh this far past its tier budget
# is dense enough that the synchronous reduction call risks running unbounded
# and freezing the Editor with no way to cancel (confirmed real 2026-09-09,
# whole-project run_scope() hung 10+ minutes on one such mesh). Meshes over
# this are flagged LOD_GENERATION_TOO_LARGE for manual authoring instead.
_LOD_GENERATION_MAX_SOURCE_TRIANGLES = 100_000

# Provenance tag for LOD_REGENERATE (see module docstring) — a private
# implementation constant, not an audit_budgets.json field: unlike a budget
# number, nobody is meant to hand-edit this key. Value is a JSON-encoded
# poly_fractions list, e.g. "[1.0, 0.5, 0.25, 0.1]", written every time this
# module (re)generates a mesh's LODs — see _apply_lod_generation().
_LOD_GEN_TAG_KEY = "LODGenPolyFractions"
# Written by mark_selected_as_auto_generated() for a mesh with no fraction
# history — json.loads("null") is Python None, which _parse_stored_fractions
# always treats as "not a valid fraction list", so a mesh carrying this
# marker always compares as stale against real config and gets picked up by
# the very next regenerate_stale=True run.
_UNMIGRATED_MARKER = "null"

# Hero-tier LODs are ALWAYS hand-authored, full stop — confirmed explicitly
# 2026-09-09: never auto-generate or auto-regenerate them, regardless of
# what audit_budgets.json's "lod_generation_targets"."hero" happens to say
# (that entry may still carry real poly_fractions from earlier tuning — this
# exclusion makes them inert rather than relying on someone remembering to
# null them out). Same hardcoded-not-configurable treatment CLAUDE.md
# already gives "hero" for bootstrap tagging ("hero is never auto-assigned")
# — extended here to LOD_GENERATION/LOD_REGENERATE specifically, since those
# are the only fixes in this module that touch actual mesh geometry.
# LOD_GROUP (organizational metadata only, no geometry rebuild) is NOT
# excluded — see _plan_mesh()'s LOD_GROUP block, unaffected by this set.
_LOD_GENERATION_EXCLUDED_TIERS = {"hero"}


# ---------------------------------------------------------------------------
# Tag / property reads — deliberately duplicated from audit_rules_meshes.py
# rather than imported, same convention audit_fix_textures.py already
# follows (see its module docstring) of not importing rule-module internals
# into a fix module.
# ---------------------------------------------------------------------------

def _get_asset_data(asset_path):
    try:
        return unreal.EditorAssetLibrary.find_asset_data(asset_path)
    except Exception:
        return None


def _get_tag(asset_obj, cfg):
    """Returns the asset's raw BudgetTier tag, or None if untagged — no
    default_tier fallback, on purpose (see module docstring point 0 /
    audit_fix_textures.py's _get_tag() for the full rationale)."""
    tag_key = audit_config.get_tag_key(cfg)
    return unreal.EditorAssetLibrary.get_metadata_tag(asset_obj, tag_key) or None


def _safe_get(obj, prop_name):
    try:
        return obj.get_editor_property(prop_name)
    except Exception:
        return None


def _get_triangle_count(asset_path):
    ad = _get_asset_data(asset_path)
    if ad is None:
        return None
    try:
        raw = ad.get_tag_value("Triangles")
        if raw is None or raw == "":
            return None
        return int(raw)
    except Exception:
        return None


def _get_nanite_enabled(asset_path):
    ad = _get_asset_data(asset_path)
    if ad is None:
        return None
    try:
        raw = ad.get_tag_value("NaniteEnabled")
        if raw is None:
            return None
        if isinstance(raw, bool):
            return raw
        return str(raw).strip().lower() == "true"
    except Exception:
        return None


def _get_lod_count(mesh):
    try:
        return unreal.EditorStaticMeshLibrary.get_lod_count(mesh)
    except Exception:
        return None


def _serialize_fractions(fractions):
    return json.dumps(fractions)


def _parse_stored_fractions(raw):
    """Parses a _LOD_GEN_TAG_KEY tag value back into a list of floats, or
    None if it's missing, _UNMIGRATED_MARKER, or otherwise not a valid
    fraction list — all three cases are meant to compare unequal to any real
    poly_fractions list from config, so the caller doesn't need to special-
    case any of them (see _plan_mesh()'s LOD_REGENERATE branch)."""
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if isinstance(value, list) and all(isinstance(x, (int, float)) for x in value):
        return [float(x) for x in value]
    return None


def _get_lod_gen_raw_tag(mesh):
    """Raw _LOD_GEN_TAG_KEY tag value, or None if this mesh's LODs were
    never (re)generated by this tool — the presence/absence of this tag,
    not its parsed content, is what protects a hand-authored LOD chain from
    ever being touched by LOD_REGENERATE (see _plan_mesh())."""
    return unreal.EditorAssetLibrary.get_metadata_tag(mesh, _LOD_GEN_TAG_KEY) or None


def _is_default_lod_group(value):
    """The unassigned/default LOD Group reads back as the FName literally
    named "None" (confirmed 2026-09-09 on a freshly-duplicated mesh) — not Python None, an FName
    whose string form is the text "None". Used only to phrase the LOD_GROUP
    fix's note (overriding a real vendor value vs. filling in the
    unassigned default) — NOT to gate whether the fix applies, see
    _plan_mesh()'s LOD_GROUP block and module docstring point 1: the
    tier's configured group is always enforced either way."""
    if value is None:
        return True
    return str(value) in ("None", "")


# ---------------------------------------------------------------------------
# Planning — decide what would change, without writing anything
# ---------------------------------------------------------------------------

def _plan_mesh(asset_path, mesh, tier, cfg, regenerate_stale=False):
    """Return a list of (fix_type, note, payload) tuples planned for this
    mesh. fix_type is one of "LOD_GROUP", "LOD_GENERATION",
    "LOD_GENERATION_TOO_LARGE", "NANITE_DISABLE", "LOD_REGENERATE". payload
    carries whatever the apply step needs (the group name string, a
    (tri_count, poly_fractions) tuple for LOD_GENERATION/LOD_REGENERATE, or
    None for the rest — LOD_GENERATION_TOO_LARGE is informational only and
    is never applied, see _APPLY_FNS).

    regenerate_stale=False (the default, used by every plain Fix Meshes
    button) never plans LOD_REGENERATE — see that branch below and the
    module docstring for why this has to be a deliberate opt-in."""
    plans = []

    # --- LOD_GROUP — always enforces the tier's configured group, even over
    # an existing non-default value (see module docstring point 1: this is
    # a deliberate divergence from the texture-group fix's "preserve custom
    # values" policy — a mesh's LOD Group here IS the BudgetTier). ---
    lod_group_name = audit_config.get_lod_group(tier, cfg)
    if lod_group_name:
        current = _safe_get(mesh, "lod_group")
        if str(current) != lod_group_name:
            note = f"tier '{tier}' configured LOD Group"
            if not _is_default_lod_group(current):
                note += f" (overrides existing '{current}')"
            plans.append(("LOD_GROUP", note, lod_group_name))

    # --- LOD_GENERATION — over budget AND no hand-authored LODs yet. The
    # lod_count <= 1 gate is load-bearing, see module docstring point 2.
    # Also gated on _LOD_GENERATION_MAX_SOURCE_TRIANGLES: a mesh far enough
    # over budget to be this dense is exactly the case where the synchronous
    # reduction call can run unbounded and freeze the Editor with no way to
    # cancel (confirmed real 2026-09-09) — those are flagged as
    # LOD_GENERATION_TOO_LARGE for manual authoring instead of auto-run. ---
    budget = audit_config.get_tier_budget(tier, cfg)
    max_tri = budget.get("max_triangles")
    tri_count = _get_triangle_count(asset_path)
    lod_count = _get_lod_count(mesh)

    targets = audit_config.get_lod_generation_targets(tier, cfg)
    current_fractions = (targets or {}).get("poly_fractions")

    if (
        tier not in _LOD_GENERATION_EXCLUDED_TIERS
        and max_tri and tri_count is not None and lod_count is not None
    ):
        if tri_count > max_tri and lod_count <= 1:
            if tri_count > _LOD_GENERATION_MAX_SOURCE_TRIANGLES:
                plans.append((
                    "LOD_GENERATION_TOO_LARGE",
                    f"{tri_count} triangles exceeds the auto-generation ceiling "
                    f"({_LOD_GENERATION_MAX_SOURCE_TRIANGLES}) — needs manual LOD authoring, not auto-run",
                    None,
                ))
            elif current_fractions:
                plans.append((
                    "LOD_GENERATION",
                    f"{tri_count} triangles exceeds '{tier}' budget ({max_tri}), only {lod_count} LOD authored",
                    (tri_count, current_fractions),
                ))

        # --- LOD_REGENERATE — opt-in only (see module docstring and
        # _plan_mesh()'s own docstring). A mesh only reaches here if it
        # ALREADY has LODs (lod_count > 1, the first-generation branch above
        # didn't apply) — the untagged-mesh check below is what keeps a
        # hand-authored LOD chain permanently out of reach, exactly like the
        # lod_count <= 1 gate protects it from first-generation. ---
        elif regenerate_stale and lod_count > 1 and current_fractions:
            raw_tag = _get_lod_gen_raw_tag(mesh)
            if raw_tag is not None:
                stored_fractions = _parse_stored_fractions(raw_tag)
                if stored_fractions != current_fractions:
                    if tri_count is not None and tri_count > _LOD_GENERATION_MAX_SOURCE_TRIANGLES:
                        plans.append((
                            "LOD_GENERATION_TOO_LARGE",
                            f"{tri_count} triangles exceeds the auto-generation ceiling "
                            f"({_LOD_GENERATION_MAX_SOURCE_TRIANGLES}) — needs manual LOD authoring, not auto-run",
                            None,
                        ))
                    elif stored_fractions is None:
                        plans.append((
                            "LOD_REGENERATE",
                            f"no fraction history recorded (pre-migration) — adopting tier "
                            f"'{tier}' current poly_fractions {current_fractions}",
                            (tri_count, current_fractions),
                        ))
                    else:
                        plans.append((
                            "LOD_REGENERATE",
                            f"tier '{tier}' poly_fractions changed: {stored_fractions} -> {current_fractions}",
                            (tri_count, current_fractions),
                        ))

    # --- NANITE_DISABLE — tier-independent; off when rules.nanite_enabled is "OFF". ---
    if audit_config.is_rule_enabled("nanite_enabled") and _get_nanite_enabled(asset_path):
        plans.append(("NANITE_DISABLE", "Nanite enabled — not allowed by the config (rules.nanite_enabled)", None))

    return plans


# ---------------------------------------------------------------------------
# Apply — one function per fix_type, each independently try/except-guarded
# so one bad asset never aborts the whole batch (same defensive style as
# every risky unreal.* call elsewhere in this toolkit).
# ---------------------------------------------------------------------------

def _apply_lod_group(mesh, group_name):
    mesh.set_editor_property("lod_group", group_name)


def _apply_lod_generation(asset_path, tri_count, mesh, poly_fractions):
    # This call is synchronous and its cost scales with mesh complexity, not
    # just triangle count — the 2026-09-09 pilot test's ~3s estimate was for one
    # "moderate" mesh, not a guarantee. Logged BEFORE the blocking call so the
    # Output Log names the asset that's mid-rebuild if this run appears to
    # hang (confirmed real 2026-09-09: an over-the-_LOD_GENERATION_MAX_SOURCE_TRIANGLES-
    # ceiling mesh froze the Editor for 10+ minutes with the progress dialog
    # stuck, no way to tell which asset it was on).
    unreal.log(f"[Fix Meshes] LOD_GENERATION starting for {asset_path} ({tri_count} triangles) — this call blocks until the rebuild finishes.")
    options = unreal.StaticMeshReductionOptions()
    options.set_editor_property("auto_compute_lod_screen_size", True)
    entries = []
    for fraction in poly_fractions:
        entry = unreal.StaticMeshReductionSettings()
        entry.set_editor_property("percent_triangles", fraction)
        entries.append(entry)
    options.set_editor_property("reduction_settings", entries)
    unreal.EditorStaticMeshLibrary.set_lods_with_notification(mesh, options, True)
    # Provenance stamp — shared by first-time generation and LOD_REGENERATE
    # (same function, see _APPLY_FNS): records exactly what this rebuild used,
    # so a future regenerate_stale=True run can tell "already up to date"
    # from "config has moved on since" (see _plan_mesh()'s LOD_REGENERATE
    # branch) without ever having to guess about a mesh with no tag at all.
    unreal.EditorAssetLibrary.set_metadata_tag(mesh, _LOD_GEN_TAG_KEY, _serialize_fractions(poly_fractions))


def _apply_nanite_disable(mesh):
    nanite_settings = mesh.get_editor_property("nanite_settings")
    nanite_settings.set_editor_property("enabled", False)
    mesh.set_editor_property("nanite_settings", nanite_settings)


_APPLY_FNS = {
    "LOD_GROUP": lambda asset_path, mesh, payload: _apply_lod_group(mesh, payload),
    "LOD_GENERATION": lambda asset_path, mesh, payload: _apply_lod_generation(asset_path, payload[0], mesh, payload[1]),
    "NANITE_DISABLE": lambda asset_path, mesh, payload: _apply_nanite_disable(mesh),
}
# LOD_REGENERATE reuses LOD_GENERATION's apply verbatim — same mechanics
# (rebuild + re-tag with the fractions actually used), same payload shape
# (tri_count, poly_fractions). See _plan_mesh()'s LOD_REGENERATE branch.
_APPLY_FNS["LOD_REGENERATE"] = _APPLY_FNS["LOD_GENERATION"]
# Deliberately NOT in _APPLY_FNS: "LOD_GENERATION_TOO_LARGE" is informational
# only (see _plan_mesh's ceiling check below) — it's never applied, only
# reported, so a mesh flagged this way is routed to manual LOD authoring
# instead of risking an unbounded synchronous rebuild.


def _apply_one(asset_path, mesh, fix_type, payload):
    try:
        _APPLY_FNS[fix_type](asset_path, mesh, payload)
        unreal.EditorAssetLibrary.save_asset(asset_path, only_if_is_dirty=True)
        return True, None
    except Exception as e:
        return False, e


# ---------------------------------------------------------------------------
# Shared core — both entry points below build a (asset_path, mesh, tier)
# list their own way, then hand it to this.
# ---------------------------------------------------------------------------

def _fix_meshes(candidates, cfg, apply, progress=None, regenerate_stale=False):
    """candidates: list of (asset_path, mesh, tier). Returns the same result
    dict shape both entry points expose."""
    planned = []          # (asset_path, fix_type, note, payload)
    skipped_untagged = []
    applied = []           # (asset_path, fix_type)
    failed = []            # (asset_path, fix_type, exception)
    cancelled_after = None

    # should_cancel() is listed in audit_verify_api.py's ScopedSlowTask probe
    # but its result was never confirmed on this fork — gate
    # on hasattr so a missing/renamed method degrades to "no cancel support"
    # instead of crashing the batch, same defensive style as every other
    # risky unreal.* call in this module.
    can_check_cancel = progress is not None and hasattr(progress, "should_cancel")

    for asset_path, mesh, tier in candidates:
        if can_check_cancel:
            try:
                if progress.should_cancel():
                    cancelled_after = asset_path
                    break
            except Exception:
                can_check_cancel = False

        if progress is not None:
            progress.enter_progress_frame(1, asset_path)

        for fix_type, note, payload in _plan_mesh(asset_path, mesh, tier, cfg, regenerate_stale=regenerate_stale):
            planned.append((asset_path, fix_type, note, payload))
            if apply and fix_type in _APPLY_FNS:
                ok, exc = _apply_one(asset_path, mesh, fix_type, payload)
                if ok:
                    applied.append((asset_path, fix_type))
                else:
                    failed.append((asset_path, fix_type, exc))

    return {
        "planned": planned,
        "skipped_untagged": skipped_untagged,
        "applied": applied,
        "failed": failed,
        "cancelled_after": cancelled_after,
    }


def _candidates_from_assets(asset_paths, cfg):
    """Loads each asset, filters to StaticMesh, resolves its tier (skipping
    untagged — see module docstring point 0). Returns
    (candidates, skipped_untagged, skipped_not_mesh)."""
    candidates = []
    skipped_untagged = []
    skipped_not_mesh = []

    for asset_path in asset_paths:
        mesh = unreal.load_asset(asset_path)
        if not isinstance(mesh, unreal.StaticMesh):
            skipped_not_mesh.append(asset_path)
            continue
        tier = _get_tag(mesh, cfg)
        if tier is None:
            skipped_untagged.append(asset_path)
            continue
        candidates.append((asset_path, mesh, tier))

    return candidates, skipped_untagged, skipped_not_mesh


# ---------------------------------------------------------------------------
# Entry point 1 — explicitly selected asset(s). Small, bounded, safe by
# construction: no warning needed, single click like Fix Textures.
# ---------------------------------------------------------------------------

def run_selected(apply=True, regenerate_stale=False):
    """Fixes only the StaticMesh asset(s) currently selected in the Content
    Browser — NOT their containing folder (unlike audit_fix_textures.py's
    _resolve() convention). Deliberate: LOD_GENERATION triggers a real
    synchronous mesh rebuild per asset, so this entry point's scope is
    exactly what you can see selected, nothing implied or expanded.

    regenerate_stale=True additionally allows LOD_REGENERATE (see
    _plan_mesh()'s docstring and the module docstring) — only ever touches
    meshes this tool already tagged as tool-generated whose recorded
    poly_fractions differ from the current config. Default False, same as
    run_scope(), so the plain "Fix Meshes (Selected)" button's behavior is
    unchanged."""
    cfg = audit_config.load_config()

    try:
        asset_data_list = unreal.EditorUtilityLibrary.get_selected_asset_data()
    except AttributeError:
        asset_data_list = []

    if not asset_data_list:
        unreal.log("[Fix Meshes] Nothing selected in the Content Browser.")
        return None

    asset_paths = [str(ad.package_name) for ad in asset_data_list]
    candidates, skipped_untagged, skipped_not_mesh = _candidates_from_assets(asset_paths, cfg)

    result = _fix_meshes(candidates, cfg, apply, regenerate_stale=regenerate_stale)
    result["skipped_untagged"] = skipped_untagged
    result["skipped_not_mesh"] = skipped_not_mesh

    _print_report(f"{len(asset_paths)} selected asset(s)", result, apply)
    return result


# ---------------------------------------------------------------------------
# Entry point 1b — migration bridge for LOD_REGENERATE (see module docstring
# and _plan_mesh()'s LOD_REGENERATE branch). A one-time, explicit,
# selection-only action — deliberately NOT a folder/whole-project version of
# this: LOD_REGENERATE's entire safety model rests on "a mesh only carries
# _LOD_GEN_TAG_KEY if this tool put it there", and a mesh's LODs having
# lod_count > 1 is not proof of that — it could just as easily be a vendor
# pack's or an artist's hand-authored work. Only a human looking at a
# specific mesh can vouch for its provenance; automating that judgment over
# a whole folder would risk claiming (and later silently replacing on some
# future regenerate run) real hand-authored LOD work — exactly what every
# other gate in this module exists to prevent.
# ---------------------------------------------------------------------------

def mark_selected_as_auto_generated():
    """Tags the currently selected StaticMesh(es) as tool-generated, using
    _UNMIGRATED_MARKER since there's no real fraction history for them (they
    were fixed before LOD_REGENERATE's tracking tag existed). Writes only —
    never rebuilds anything itself. The next regenerate_stale=True run
    always treats an unparseable stored value as stale (see
    _parse_stored_fractions()), so this schedules a one-time real
    regeneration (+ proper re-tag with real fractions) the next time you
    click Regenerate Auto LODs.

    Skips exactly like every other fix in this module: assets with no
    BudgetTier tag (never guess a tier), and — specific to this helper —
    meshes with lod_count <= 1 (nothing to migrate; those are still eligible
    for ordinary first-time LOD_GENERATION instead)."""
    cfg = audit_config.load_config()

    try:
        asset_data_list = unreal.EditorUtilityLibrary.get_selected_asset_data()
    except AttributeError:
        asset_data_list = []

    if not asset_data_list:
        unreal.log("[Fix Meshes] Nothing selected in the Content Browser.")
        return None

    asset_paths = [str(ad.package_name) for ad in asset_data_list]
    candidates, skipped_untagged, skipped_not_mesh = _candidates_from_assets(asset_paths, cfg)

    marked = []
    skipped_no_lods = []
    skipped_already_tagged = []
    for asset_path, mesh, _tier in candidates:
        lod_count = _get_lod_count(mesh)
        if lod_count is None or lod_count <= 1:
            skipped_no_lods.append(asset_path)
            continue
        if _get_lod_gen_raw_tag(mesh) is not None:
            skipped_already_tagged.append(asset_path)
            continue
        unreal.EditorAssetLibrary.set_metadata_tag(mesh, _LOD_GEN_TAG_KEY, _UNMIGRATED_MARKER)
        unreal.EditorAssetLibrary.save_asset(asset_path, only_if_is_dirty=True)
        marked.append(asset_path)

    print("=" * 78)
    print("Adopt Selected LODs as Auto-Generated")
    print("=" * 78)
    print(f"\n[MARKED — will be picked up by the next Regenerate run] — {len(marked)} mesh(es)")
    print("-" * 78)
    for asset_path in marked:
        print(f"  {asset_path}")
    print(f"\n[SKIPPED — already tracked] — {len(skipped_already_tagged)} mesh(es)")
    for asset_path in skipped_already_tagged[:10]:
        print(f"  {asset_path}")
    print(f"\n[SKIPPED — no LODs to migrate (lod_count <= 1)] — {len(skipped_no_lods)} mesh(es)")
    for asset_path in skipped_no_lods[:10]:
        print(f"  {asset_path}")
    print(f"\n[SKIPPED — UNTAGGED, no BudgetTier — never guessed] — {len(skipped_untagged)} asset(s)")
    for asset_path in skipped_untagged[:10]:
        print(f"  {asset_path}")
    print("=" * 78)

    return {
        "marked": marked,
        "skipped_already_tagged": skipped_already_tagged,
        "skipped_no_lods": skipped_no_lods,
        "skipped_untagged": skipped_untagged,
        "skipped_not_mesh": skipped_not_mesh,
    }


# ---------------------------------------------------------------------------
# Entry point 2 — folder/whole-project scope, same resolution convention as
# every other panel action (see audit_actions.py's resolve_scan_target()).
# Prints a candidate count + explicit warning BEFORE touching anything, and
# tracks progress via unreal.ScopedSlowTask WITHOUT a dialog (see run_scope()
# below for why) — the Output Log is the source of truth for what's
# happening during a long batch, not a Slate widget. See module docstring
# for why this is a separate, heavier-weight entry point rather than reusing
# run_selected()'s shape.
# ---------------------------------------------------------------------------

_LARGE_SCOPE_WARNING_THRESHOLD = 20  # candidate count above which the warning gets louder


def run_scope(root_path, apply=True, regenerate_stale=False):
    """regenerate_stale=True additionally allows LOD_REGENERATE (see
    _plan_mesh()'s docstring and the module docstring) — only ever touches
    meshes this tool already tagged as tool-generated whose recorded
    poly_fractions differ from the current config; a mesh with no tracking
    tag is never touched regardless of this flag. Default False, so the
    plain "Fix Meshes (Scope)" button's behavior is unchanged."""
    cfg = audit_config.load_config()
    collected = audit_collector_folder.collect(root_path, cfg)

    candidates = []
    skipped_untagged = []
    for asset_path, mesh in collected["Meshes"]:
        tier = _get_tag(mesh, cfg)
        if tier is None:
            skipped_untagged.append(asset_path)
            continue
        candidates.append((asset_path, mesh, tier))

    # Pre-count how many actually have a fix planned, not just how many
    # meshes exist in scope — the warning should reflect real work, not
    # every mesh the collector happened to walk past.
    would_touch = [c for c in candidates if _plan_mesh(c[0], c[1], c[2], cfg, regenerate_stale=regenerate_stale)]

    print("=" * 78)
    print(f"Fix Meshes — SCOPE: {root_path}")
    print(f"{len(would_touch)} mesh(es) would be touched out of {len(candidates)} tagged, "
          f"{len(collected['Meshes'])} scanned total.")
    if len(would_touch) > _LARGE_SCOPE_WARNING_THRESHOLD:
        print("!" * 78)
        print("WARNING: LOD generation triggers a real, synchronous mesh rebuild per")
        print("asset (~3s for a moderate mesh in the 2026-09-09 pilot test, but cost scales")
        print("with mesh complexity — a single dense mesh can block the Editor for")
        print("many minutes with no way to tell which asset it's stuck on besides the")
        print("Output Log). Meshes over "
              f"{_LOD_GENERATION_MAX_SOURCE_TRIANGLES} triangles are flagged")
        print("LOD_GENERATION_TOO_LARGE and skipped for manual authoring instead of")
        print("auto-run, but the ones under that ceiling still run for real, one at a")
        print("time. There is no Cancel button (see below) — once started, the batch")
        print("runs to completion; it cannot interrupt an asset already mid-rebuild")
        print("either way. Save your work before proceeding. Consider running on a")
        print("smaller subfolder first if this is your first time using this button.")
        print("!" * 78)
    print("=" * 78)

    # No progress DIALOG (no make_dialog() call) — confirmed real, three times
    # on 2026-09-09: a ScopedSlowTask dialog opened from a Python-console-
    # driven batch (as opposed to a normal in-engine C++ action) got stuck on
    # screen capturing input (Esc did nothing) with the Editor otherwise idle
    # (0% CPU) — happened even on a 0-candidate run with nothing to rebuild,
    # so it's not about batch size or LOD_GENERATION's rebuild cost, and an
    # explicit progress.destroy_progress() call in run_scope()'s finally
    # block (added after the first two repros) did not stop the third. The
    # Output Log's per-asset lines (LOD_GENERATION's "starting for ..." plus
    # the final report) are the progress feedback now — no modal widget that
    # can wedge the Editor. ScopedSlowTask itself is still used, undialogued,
    # purely for should_cancel()/enter_progress_frame() bookkeeping in
    # _fix_meshes — harmless with no dialog attached, so left in place rather
    # than ripped out.
    progress = None
    slow_task_cls = getattr(unreal, "ScopedSlowTask", None)
    if slow_task_cls is not None and apply:
        try:
            progress = slow_task_cls(len(would_touch), f"Fix Meshes: {root_path}")
        except Exception as e:
            unreal.log(f"[Fix Meshes] Could not start progress tracking ({e!r}) — continuing without it.")
            progress = None

    # Iterate would_touch, not candidates — the progress total above is
    # len(would_touch), so entering one frame per candidate instead (most of
    # which have nothing planned) desynced the bar from what it displayed as
    # its total. _plan_mesh() is pure/deterministic so re-running it inside
    # _fix_meshes on the same (asset_path, mesh, tier) tuples yields identical
    # plans — nothing is lost by pre-filtering here.
    try:
        result = _fix_meshes(would_touch, cfg, apply, progress=progress if apply else None, regenerate_stale=regenerate_stale)
    finally:
        # No dialog is attached anymore (see above), so there's nothing left
        # to visually get stuck — this destroy_progress() call is just
        # cleanup for the ScopedSlowTask object itself, kept for correctness
        # (and in a finally so a mid-batch exception can't leak it either),
        # not a fix for the freeze — that was the dialog, now removed.
        if progress is not None and hasattr(progress, "destroy_progress"):
            try:
                progress.destroy_progress()
            except Exception as e:
                unreal.log(f"[Fix Meshes] progress.destroy_progress() failed ({e!r}) — dialog may stay on screen, harmless otherwise.")

    result["skipped_untagged"] = skipped_untagged
    result["skipped_not_mesh"] = []

    _print_report(root_path, result, apply)
    return result


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

_FIX_ORDER = ["LOD_GROUP", "LOD_GENERATION", "LOD_REGENERATE", "LOD_GENERATION_TOO_LARGE", "NANITE_DISABLE"]
_FIX_LABELS = {
    "LOD_GROUP": "LOD GROUP ASSIGNMENT",
    "LOD_GENERATION": "LOD GENERATION",
    "LOD_REGENERATE": "LOD REGENERATION (config changed since last generation)",
    "LOD_GENERATION_TOO_LARGE": f"LOD GENERATION SKIPPED — over {_LOD_GENERATION_MAX_SOURCE_TRIANGLES} triangles, needs manual authoring",
    "NANITE_DISABLE": "NANITE DISABLE (unverified write — spot-check the first one)",
}


def _print_report(label, result, apply):
    mode = "APPLY" if apply else "DRY RUN (preview only, nothing written)"
    print("=" * 78)
    print(f"Fix Meshes — {mode}")
    print(f"Scope: {label}")
    if result.get("cancelled_after"):
        print(f"CANCELLED by user, stopped before: {result['cancelled_after']}")
        print("(everything before that point in the batch was already applied)")
    print("=" * 78)

    by_fix = defaultdict(list)
    for asset_path, fix_type, note, _payload in result["planned"]:
        by_fix[fix_type].append((asset_path, note))

    applied_set = {(p, f) for p, f in result["applied"]}
    failed_map = {(p, f): exc for p, f, exc in result["failed"]}

    for fix_type in _FIX_ORDER:
        entries = by_fix.get(fix_type, [])
        print(f"\n[{_FIX_LABELS[fix_type]}] — {len(entries)} mesh(es)")
        print("-" * 78)
        for asset_path, note in entries[:15]:
            status = ""
            if apply:
                if (asset_path, fix_type) in applied_set:
                    status = "  [applied]"
                elif (asset_path, fix_type) in failed_map:
                    status = f"  [FAILED: {failed_map[(asset_path, fix_type)]!r}]"
            print(f"  {asset_path}  ({note}){status}")
        if len(entries) > 15:
            print(f"  ... and {len(entries) - 15} more")

    print(f"\n[SKIPPED — UNTAGGED, no BudgetTier — never guessed] — {len(result['skipped_untagged'])} asset(s)")
    print("-" * 78)
    for asset_path in result["skipped_untagged"][:10]:
        print(f"  {asset_path}")
    if len(result["skipped_untagged"]) > 10:
        print(f"  ... and {len(result['skipped_untagged']) - 10} more")

    if result.get("skipped_not_mesh"):
        print(f"\n[SKIPPED — NOT A STATICMESH] — {len(result['skipped_not_mesh'])} asset(s)")
        print("-" * 78)
        for asset_path in result["skipped_not_mesh"][:10]:
            print(f"  {asset_path}")

    total_planned = len(result["planned"])
    total_failed = len(result["failed"])
    print("\n" + "=" * 78)
    print(f"SUMMARY: {total_planned} fix(es) planned across {_FIX_ORDER} categories, "
          f"{total_failed} failed to apply.")
    print("ARTIST REVIEW REQUIRED for every LOD GENERATION entry above — per-LOD")
    print("triangle counts aren't reliably readable from Python on this fork, so")
    print("this report cannot confirm the generated LODs are actually good. Open")
    print("each fixed mesh in the Static Mesh Editor and check by eye.")
    print("=" * 78)


if __name__ == "__main__":
    run_scope("/Game", apply=False)
