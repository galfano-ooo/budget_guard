"""
tag_existing_content.py
------------------------------------------------------------------------------
Bootstrap script: applies a BudgetTier metadata tag to existing Content Browser
assets, based on folder-name keyword matching.

The keyword table, the taggable asset classes, the excluded folders and the tag
key all come from BudgetGuard's layered config (audit_config.py): generic
defaults in audit_budgets.json, plus an optional per-project override in
<Project>/Saved/BudgetGuard/config.json. Nothing project-specific lives in this
file.

Scope:    3D Environment / Rendering pipeline only.
          No gameplay/mechanics logic is read, written, or touched.

------------------------------------------------------------------------------
USAGE (from the UE5 Python console, or via exec(open(path).read())):

    import importlib
    import tag_existing_content as boot
    importlib.reload(boot)

    # 1) ALWAYS dry-run first. Writes nothing, just prints the plan.
    boot.run(root_path="/Game/MyContent", apply=False)

    # 2) Review the printed report (especially the UNMATCHED section).
    #    Once it looks right, apply for real:
    boot.run(root_path="/Game/MyContent", apply=True)

    # Re-running later is safe: assets that already carry a BudgetTier tag
    # are skipped, protecting any manual overrides made after run 1.
    # Pass force=True to re-evaluate and overwrite existing tags instead.

------------------------------------------------------------------------------
DESIGN RULES (do not change without re-confirming):
  - Dry-run by default. Changes require apply=True explicitly.
  - Assets already tagged with BudgetTier are left alone unless force=True.
  - Folders/keywords with no match are NEVER guessed at (e.g. never silently
    defaulted to "background") - they're collected into an UNMATCHED list
    for manual review instead.
  - Only rendering-relevant asset classes are considered. Blueprints, Enums,
    Maps, Collections and Developer sandboxes are excluded entirely.
  - "hero" is never auto-assigned by this script, even if a project config
    lists keywords for it. It's reserved for unique, narrative-critical
    objects and gets tagged manually (tag_selection("hero")).

For a Content Browser "quick view" per tier, see build_tier_collections.py:
BudgetTier is package metadata (not an Asset Registry tag), so it isn't
visible to native Content Browser search/filters/columns, and the engine has
no Python-scriptable Collections API either (confirmed live on UE 5.7.4) -
build_tier_collections.select_tier() instead selects a tier's assets in the
Content Browser so a native "Add to Collection" click can build the view.
Nothing here depends on that.

------------------------------------------------------------------------------
VERSION NOTE: written against the general UE5 EditorAssetLibrary Python API.
A couple of calls below (AssetData.asset_class_path, list_assets' returned
path format) have shifted between engine versions historically. Validated
against UE 5.7.4 - run on a small test folder first on a different engine
version, and check the printed asset classes look sane before pointing it at
a full tree.
------------------------------------------------------------------------------
"""

import re
import unreal
from collections import defaultdict

import audit_config

# Tiers this script never assigns on its own (see DESIGN RULES).
MANUAL_ONLY_TIERS = {"hero"}


# ---------------------------------------------------------------------------
# Matching helpers
# ---------------------------------------------------------------------------

def _is_excluded(asset_path: str) -> bool:
    return audit_config.is_excluded(asset_path)


def _tag_key() -> str:
    return audit_config.get_tag_key()


def _tier_order():
    """Tiers in report order: the ones with auto-match keywords first (in
    declared order), then every other configured tier (hero, utility...)."""
    ordered = [t for t in audit_config.get_tag_rules() if t not in MANUAL_ONLY_TIERS]
    ordered += [t for t in audit_config.get_all_tiers() if t not in ordered]
    return ordered


_VARIANT_SUFFIX_RE = re.compile(r"(_worn|_a|_b)(?=/|$)")


def _normalize(path: str) -> str:
    """Lowercase and strip common vendor variant suffixes (_worn, _A, _B) so
    e.g. Lamps_A, Lamps_B and Lamps_A_worn all resolve to the same keyword.

    Only strips the suffix at the end of a path segment (right before "/"
    or end of string) — a blanket str.replace() here would also eat "_a"/
    "_b" occurring mid-word (e.g. "Meshes_Building" -> "Meshes_uilding"),
    silently breaking substring keyword matches like "meshes_building"."""
    p = path.lower()
    return _VARIANT_SUFFIX_RE.sub("", p)


def _match_tier(asset_path: str):
    """Return the matched tier name, or None if nothing matched."""
    normalized = _normalize(asset_path)
    for tier, keywords in audit_config.get_tag_rules().items():
        if tier in MANUAL_ONLY_TIERS:
            continue
        for kw in keywords:
            if kw.lower() in normalized:
                return tier
    return None


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------

def _collect_taggable_assets(root_path: str):
    """Return (asset_path, asset_class) for every taggable, non-excluded
    asset under root_path."""
    all_paths = unreal.EditorAssetLibrary.list_assets(
        root_path, recursive=True, include_folder=False
    )
    taggable = audit_config.get_taggable_classes()
    result = []
    for path in all_paths:
        if _is_excluded(path):
            continue
        asset_data = unreal.EditorAssetLibrary.find_asset_data(path)
        if not asset_data.is_valid():
            continue
        # UE 5.1+ API: AssetData.asset_class_path.asset_name
        # If this errors on your fork, try asset_data.asset_class instead
        # (older API) and adjust this one line.
        asset_class = str(asset_data.asset_class_path.asset_name)
        if asset_class not in taggable:
            continue
        result.append((path, asset_class))
    return result


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run(root_path="/Game", apply=False, force=False, show_all=True):
    """
    Scan root_path for taggable assets, match a BudgetTier via folder
    keywords, and either preview (apply=False, default) or write
    (apply=True) the tags.

    force=True re-evaluates and overwrites assets that already carry a
    BudgetTier tag (off by default, to protect manual overrides made after
    a previous run).

    show_all=True (default) lists every asset in the report so the dry-run
    can be reviewed in full before apply; False truncates long sections.
    """
    assets = _collect_taggable_assets(root_path)

    to_apply = []                    # (path, class, tier)
    already_tagged = []              # (path, class, existing_tier)
    unmatched = defaultdict(list)    # parent_folder -> [asset paths]

    for path, asset_class in assets:
        loaded = unreal.load_asset(path)
        existing = unreal.EditorAssetLibrary.get_metadata_tag(loaded, _tag_key())

        if existing and not force:
            already_tagged.append((path, asset_class, existing))
            continue

        tier = _match_tier(path)
        if tier is None:
            parent = path.rsplit("/", 1)[0]
            unmatched[parent].append(path)
            continue

        to_apply.append((path, asset_class, tier))

    _print_report(root_path, to_apply, already_tagged, unmatched, apply,
                  show_all)

    if apply:
        for path, asset_class, tier in to_apply:
            asset = unreal.load_asset(path)
            unreal.EditorAssetLibrary.set_metadata_tag(asset, _tag_key(), tier)
        _save_tagged_assets([path for path, _, _ in to_apply])
        unreal.log(
            f"[BudgetGuard Bootstrap] Applied tags to {len(to_apply)} asset(s)."
        )
    else:
        unreal.log(
            "[BudgetGuard Bootstrap] DRY RUN — no changes written. "
            "Re-run with apply=True once this looks correct."
        )

    return {
        "to_apply": to_apply,
        "already_tagged": already_tagged,
        "unmatched": unmatched,
    }


# ---------------------------------------------------------------------------
# Saving
# ---------------------------------------------------------------------------

def _save_tagged_assets(paths):
    """Persist newly-tagged assets to disk.

    Prefers one batched unreal.EditorLoadingAndSavingUtils.save_packages()
    call over calling EditorAssetLibrary.save_asset() once per asset -- the
    per-asset save is what made the 2026-09-09 bootstrap run slow on a large
    tree (each call re-pays full editor save overhead). Falls back to the
    old per-asset loop if the batch API isn't present on this fork or the
    call raises -- run audit_verify_api.run() first to check which path
    you're actually on before trusting the batch path at scale.
    """
    batch_fn = getattr(unreal.EditorLoadingAndSavingUtils, "save_packages", None)
    if batch_fn is None:
        for path in paths:
            unreal.EditorAssetLibrary.save_asset(path, only_if_is_dirty=True)
        return

    packages = []
    for path in paths:
        asset = unreal.load_asset(path)
        package = asset.get_outer()
        if package is not None:
            packages.append(package)

    try:
        batch_fn(packages, True)
    except Exception as e:
        unreal.log_warning(
            f"[BudgetGuard Bootstrap] Batched save_packages failed ({e}); "
            "falling back to per-asset save."
        )
        for path in paths:
            unreal.EditorAssetLibrary.save_asset(path, only_if_is_dirty=True)


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def _print_report(root_path, to_apply, already_tagged, unmatched, apply,
                  show_all=True):
    mode = "APPLY" if apply else "DRY RUN (preview only, nothing written)"
    print("=" * 78)
    print(f"BudgetGuard tagging — {mode}")
    print(f"Scope: {root_path}")
    print("=" * 78)

    by_tier = defaultdict(list)
    for path, asset_class, tier in to_apply:
        by_tier[tier].append((path, asset_class))

    for tier in _tier_order():
        entries = by_tier.get(tier, [])
        print(f"\n[{tier.upper()}] — {len(entries)} asset(s)")
        print("-" * 78)
        shown = entries if show_all else entries[:15]
        for path, asset_class in shown:
            print(f"  {asset_class:<24} {path}")
        if len(entries) > len(shown):
            print(f"  ... and {len(entries) - len(shown)} more")

    print(f"\n[ALREADY TAGGED — skipped] — {len(already_tagged)} asset(s)")
    print("-" * 78)
    shown_tagged = already_tagged if show_all else already_tagged[:10]
    for path, asset_class, existing_tier in shown_tagged:
        print(f"  {asset_class:<24} {path}  (BudgetTier={existing_tier})")
    if len(already_tagged) > len(shown_tagged):
        print(f"  ... and {len(already_tagged) - len(shown_tagged)} more")

    total_unmatched = sum(len(v) for v in unmatched.values())
    print(
        f"\n[UNMATCHED — NEEDS MANUAL REVIEW] — {total_unmatched} asset(s) "
        f"across {len(unmatched)} folder(s)"
    )
    print("-" * 78)
    for folder, paths in sorted(unmatched.items(), key=lambda kv: -len(kv[1])):
        print(f"  {folder}  ({len(paths)} asset(s))")
        if show_all:
            for p in sorted(paths):
                print(f"      {p}")

    total =len(to_apply) + len(already_tagged) + total_unmatched
    print("\n" + "=" * 78)
    print(
        f"SUMMARY: {len(to_apply)} to tag | {len(already_tagged)} already "
        f"tagged | {total_unmatched} unmatched | {total} scanned total"
    )
    print("=" * 78)


# ---------------------------------------------------------------------------
# Manual per-selection tagging (import-time workflow: artist selects one or
# more freshly-imported assets in the Content Browser and clicks a
# tier button in the panel). Independent of run()'s folder-keyword bootstrap
# pass above.
# ---------------------------------------------------------------------------

def tag_selection(tier):
    """Apply BudgetTier=tier to every asset currently selected in the
    Content Browser. Always overwrites any existing tag on those assets --
    unlike run()'s bootstrap pass (which skips already-tagged assets to
    protect manual overrides), a click on this button IS the deliberate
    manual override, so there's nothing to protect it from. This is the
    intended channel for "hero" too (never auto-assigned by run(), but
    exactly what a manual per-asset button is for).

    Same exclusion rules as run(): assets under an excluded path fragment or
    outside the taggable classes (both from the config) are skipped, not silently tagged, so a stray
    Blueprint/Level caught in a multi-select doesn't get a meaningless tag.

    Returns the list of asset paths actually tagged.
    """
    valid_tiers = set(audit_config.get_all_tiers())
    if tier not in valid_tiers:
        unreal.log_error(
            f"[BudgetGuard] Unknown tier '{tier}' — must be one of {sorted(valid_tiers)}"
        )
        return []

    try:
        selected = unreal.EditorUtilityLibrary.get_selected_asset_data()
    except AttributeError:
        selected = []

    if not selected:
        unreal.log("[BudgetGuard] Nothing selected in the Content Browser.")
        return []

    taggable = audit_config.get_taggable_classes()
    tagged = []
    skipped = []
    for asset_data in selected:
        path = str(asset_data.package_name)
        asset_class = str(asset_data.asset_class_path.asset_name)
        if _is_excluded(path) or asset_class not in taggable:
            skipped.append((path, asset_class))
            continue
        asset = unreal.load_asset(path)
        unreal.EditorAssetLibrary.set_metadata_tag(asset, _tag_key(), tier)
        tagged.append(path)
    _save_tagged_assets(tagged)

    unreal.log(f"[BudgetGuard] Tagged {len(tagged)} asset(s) as '{tier}':")
    for path in tagged:
        unreal.log(f"  + {path}")
    if skipped:
        unreal.log(
            f"[BudgetGuard] Skipped {len(skipped)} selected item(s) "
            f"(excluded folder or non-taggable class):"
        )
        for path, asset_class in skipped:
            unreal.log(f"  - {asset_class:<24} {path}")

    return tagged


if __name__ == "__main__":
    run(apply=False)
