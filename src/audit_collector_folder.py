"""
audit_collector_folder.py
------------------------------------------------------------------------------
Collects assets by scanning a Content Browser folder directly (recursive).
Use for whole-project or specific-folder audits — independent of what's
actually placed in any level.

CONFIDENCE NOTE: this module uses only EditorAssetLibrary, one of the most
stable parts of the UE5 Python API — high confidence.
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


def collect(root_path, cfg=None):
    """Return dict: category -> list of (asset_path, loaded_object)."""
    cfg = cfg or audit_config.load_config()
    result = {"Textures": [], "Meshes": [], "Materials": []}

    all_paths = unreal.EditorAssetLibrary.list_assets(
        root_path, recursive=True, include_folder=False
    )

    for path in all_paths:
        if audit_config.is_excluded(path, cfg):
            continue
        asset_data = unreal.EditorAssetLibrary.find_asset_data(path)
        if not asset_data.is_valid():
            continue
        # UE 5.1+ API shape: asset_class_path.asset_name. If this errors on
        # your fork, try asset_data.asset_class (older API) instead.
        asset_class = str(asset_data.asset_class_path.asset_name)
        category = CLASS_TO_CATEGORY.get(asset_class)
        if category is None:
            continue
        loaded = unreal.load_asset(path)
        result[category].append((path, loaded))

    return result
