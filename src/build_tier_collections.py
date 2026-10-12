"""
build_tier_collections.py
------------------------------------------------------------------------------
Gives a one-click "show me everything in this tier" view in the Content
Browser, built on top of the BudgetTier metadata tag.

Scope:    3D Environment / Rendering pipeline only.
          No gameplay/mechanics logic is read, written, or touched.

------------------------------------------------------------------------------
WHY THIS ISN'T SCRIPTED COLLECTION CREATION (confirmed 2026-09-07):

Real Content Browser Collections would be the ideal "quick view", but two
things were checked live against this engine and both came back negative:

  1. `unreal.CollectionScriptingLibrary` does not exist at all -- zero
     classes with "Collection" in the name anywhere in `dir(unreal)`. This
     is UE 5.7.4 vanilla (Epic Launcher), not a stripped fork -- the API
     simply isn't exposed to Python on this engine. Collections cannot be
     created, emptied, or populated from Python here.
  2. The BudgetTier tag itself (written via
     `unreal.EditorAssetLibrary.set_metadata_tag`) is NOT visible to the
     Content Browser's native search/filter/column system either -- it's
     package `UMetaData`, not an Asset Registry tag. Confirmed by testing a
     Content Browser Custom Filter with `BudgetTier=<tier>` (and variants)
     against assets known to carry the tag: zero results. So there's no
     native filter/column shortcut either.

WHAT THIS SCRIPT DOES INSTEAD:

`select_tier(tier)` reads BudgetTier tags the only way that's confirmed to
work (load every asset, `get_metadata_tag()` one at a time -- same approach
tag_existing_content.py and the audit collectors already use), then calls
`unreal.EditorAssetLibrary.sync_browser_to_objects()` (confirmed working via
audit_verify_api.py) to select every matching asset in the Content Browser.

From there, creating/updating the actual Collection is a NATIVE editor
action, not Python: right-click the selection -> "Add to Collection" ->
create (first time) or pick "BudgetTier_<Tier>" (later times). Re-running
select_tier() + "Add to Collection" is safe to repeat -- adding an asset
already in a collection is a no-op. There is no scripted way to REMOVE a
stale entry (an asset that got re-tagged away from that tier) -- that still
needs a manual removal from the collection, this is an accepted limitation
given the API gap above.

------------------------------------------------------------------------------
USAGE (UE5 Python console):

    import importlib
    import build_tier_collections as btc
    importlib.reload(btc)

    # See per-tier counts (and anything untagged) without touching the
    # Content Browser selection at all:
    btc.preview(root_path="/Game/MyContent")

    # Select every "props"-tagged asset in the Content Browser, then use
    # the native right-click -> Add to Collection -> "BudgetTier_Props":
    btc.select_tier("props", root_path="/Game/MyContent")

Valid tier names come from audit_budgets.json's "tiers" section
(architecture, hero, props, background, utility, unless the config changes).
------------------------------------------------------------------------------
"""

import unreal
import audit_config


def _collect_tagged_assets(root_path, tag_key, cfg):
    """Return (by_tier, untagged): by_tier maps tier-string -> [asset_path,
    ...] read directly off each asset's BudgetTier metadata tag; untagged is
    every scanned asset with no tag at all. No bulk enumerator exists for
    metadata tags so this loads every asset once, same cost
    as tag_existing_content.py's own scan."""
    all_paths = unreal.EditorAssetLibrary.list_assets(
        root_path, recursive=True, include_folder=False
    )

    by_tier = {}
    untagged = []

    for path in all_paths:
        if audit_config.is_excluded(path, cfg):
            continue
        asset_data = unreal.EditorAssetLibrary.find_asset_data(path)
        if not asset_data.is_valid():
            continue
        asset = unreal.load_asset(path)
        if asset is None:
            continue
        tier = unreal.EditorAssetLibrary.get_metadata_tag(asset, tag_key)
        if not tier:
            untagged.append(path)
            continue
        by_tier.setdefault(tier, []).append(path)

    return by_tier, untagged


def count_tiers(root_path="/Game"):
    """Read-only, silent: ({tier: n_assets}, n_untagged) under root_path - what the
    panel's Tiers tab shows. Same load-every-asset cost as preview()/select_tier()."""
    cfg = audit_config.load_config()
    by_tier, untagged = _collect_tagged_assets(root_path, audit_config.get_tag_key(cfg), cfg)
    return {tier: len(paths) for tier, paths in by_tier.items()}, len(untagged)


def preview(root_path="/Game"):
    """Read-only: prints how many assets are currently tagged per tier (and
    how many are untagged) under root_path. Selects nothing -- use
    select_tier() for that."""
    cfg = audit_config.load_config()
    tag_key = audit_config.get_tag_key(cfg)
    tiers = list(audit_config.get_all_tiers(cfg).keys())

    by_tier, untagged = _collect_tagged_assets(root_path, tag_key, cfg)

    print("=" * 78)
    print("BudgetTier Content Browser view — PREVIEW (nothing selected)")
    print(f"Scope: {root_path}")
    print("=" * 78)

    for tier in tiers:
        paths = by_tier.get(tier, [])
        print(f"\n[{tier.upper()}] — {len(paths)} asset(s)")
        for p in paths[:15]:
            print(f"  {p}")
        if len(paths) > 15:
            print(f"  ... and {len(paths) - 15} more")

    unmatched_tiers = sorted(set(by_tier) - set(tiers))
    if unmatched_tiers:
        print(
            f"\n[WARNING] Tag value(s) found with no matching tier in "
            f"the BudgetGuard config: {unmatched_tiers}"
        )

    print(f"\n[UNTAGGED] — {len(untagged)} asset(s)")
    for p in untagged[:10]:
        print(f"  {p}")
    if len(untagged) > 10:
        print(f"  ... and {len(untagged) - 10} more")

    print("\nRun select_tier('<tier>') to select one tier's assets in the "
          "Content Browser, then right-click -> Add to Collection.")

    return {"by_tier": by_tier, "untagged": untagged}


def select_tier(tier, root_path="/Game"):
    """Selects every asset tagged BudgetTier=tier, under root_path, in the
    Content Browser -- via sync_browser_to_objects(), the only confirmed way
    to bridge from "assets matching this tag" to "something visible/actable
    on in the Content Browser" on this engine (see module docstring for why
    Collections/filters can't do this directly). Follow up manually:
    right-click the selection -> Add to Collection -> "BudgetTier_<Tier>".
    Returns the list of selected asset paths."""
    cfg = audit_config.load_config()
    tag_key = audit_config.get_tag_key(cfg)
    valid_tiers = set(audit_config.get_all_tiers(cfg).keys())

    if tier not in valid_tiers:
        unreal.log_error(
            f"[BudgetGuard] Unknown tier '{tier}' — must be one of {sorted(valid_tiers)}"
        )
        return []

    by_tier, _untagged = _collect_tagged_assets(root_path, tag_key, cfg)
    paths = by_tier.get(tier, [])

    if not paths:
        unreal.log(f"[BudgetGuard] No assets tagged '{tier}' found under {root_path}.")
        return []

    unreal.EditorAssetLibrary.sync_browser_to_objects(paths)
    unreal.log(
        f"[BudgetGuard] Selected {len(paths)} '{tier}'-tagged asset(s) in the "
        f"Content Browser. Right-click the selection -> Add to Collection -> "
        f"'BudgetTier_{tier.capitalize()}' to build/update the view."
    )
    return paths


if __name__ == "__main__":
    preview()
