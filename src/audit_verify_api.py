"""
audit_verify_api.py
------------------------------------------------------------------------------
Diagnostic helper — NOT part of the audit pipeline. Run this ONCE in your
actual UE 5.7.4 console before trusting audit_rules_meshes.py and
audit_collector_level.py at scale. It prints what's actually available on
the API surfaces those modules guess at, so you can spot a mismatched name
in about a minute instead of debugging a silent wrong answer later.

USAGE:
    import audit_verify_api
    audit_verify_api.run()
------------------------------------------------------------------------------
"""

import unreal


def run():
    print("=" * 78)
    print("API VERIFICATION — compare against what audit_rules_meshes.py and")
    print("audit_collector_level.py assume. Anything printed as MISSING needs")
    print("a fix in the corresponding module before you trust it at scale.")
    print("=" * 78)

    _check_class_methods(
        "unreal.EditorStaticMeshLibrary",
        unreal.EditorStaticMeshLibrary,
        ["get_lod_count", "get_lod_triangle_count", "get_number_triangles", "get_number_verts"],
    )

    # LOD generation (audit_fix_meshes.py) — do these exist on
    # this fork at all before assuming either the declarative (LODGroup) or
    # programmatic (MeshReductionSettings) path is viable.
    _check_class_methods(
        "unreal.EditorStaticMeshLibrary -- LOD reduction (used by the LOD "
        "generation fix, audit_fix_meshes.py)",
        unreal.EditorStaticMeshLibrary,
        ["set_lod_reduction_settings", "get_lod_reduction_settings"],
    )

    _check_module_class_methods(
        "unreal.MeshReductionSettings struct fields",
        "MeshReductionSettings",
        ["percent_triangles", "percent_vertices", "terminate_criterion", "max_deviation", "welding_threshold"],
    )

    print("\n--- MeshReductionTerminationCriterion enum members ---")
    _print_enum_by_name("MeshReductionTerminationCriterion")

    print("\n--- dir(unreal.EditorStaticMeshLibrary) entries containing "
          "'lod', 'reduc', or 'nanite' (catches anything not already listed above) ---")
    for name in sorted(dir(unreal.EditorStaticMeshLibrary)):
        lname = name.lower()
        if "lod" in lname or "reduc" in lname or "nanite" in lname:
            print(f"  {name}")

    # 2026-09-09: the dir() scan above surfaced set_lods / set_lods_with_notification
    # -- a batch entry point that looks like exactly the "generate multiple LODs from
    # reduction settings in one call" API the LOD generation fix needs, instead of
    # manually extending source_models. Print real signatures/docs before writing any
    # code against them -- UE's Python bindings put the actual param list in __doc__.
    print("\n--- __doc__ for candidate batch LOD-generation methods (read the exact "
          "signature here before writing code against it) ---")
    for name in [
        "set_lods",
        "set_lods_with_notification",
        "get_lod_build_settings",
        "set_lod_build_settings",
        "get_lod_screen_sizes",
        "remove_lods",
        "set_lod_from_static_mesh",
    ]:
        method = getattr(unreal.EditorStaticMeshLibrary, name, None)
        print(f"\n  {name}:")
        if method is None:
            print("    MISSING")
        else:
            doc = getattr(method, "__doc__", None) or "    (no docstring)"
            for line in doc.strip().splitlines():
                print(f"    {line}")

    # 2026-09-09: set_lods()'s signature is (static_mesh, reduction_options) where
    # reduction_options is a StaticMeshReductionOptions struct -- almost certainly
    # holding an array of per-LOD reduction settings inside it, not one flat struct.
    # Don't guess its field names -- probe the class directly plus a broad dir(unreal)
    # scan for the nested per-LOD struct type, whatever it's actually called here.
    print("\n--- unreal.StaticMeshReductionOptions fields (guessed names -- MISSING "
          "here doesn't mean the real field doesn't exist under another name, see "
          "the raw dir() dump right below) ---")
    _check_module_class_methods(
        "unreal.StaticMeshReductionOptions",
        "StaticMeshReductionOptions",
        ["reduction_settings", "auto_compute_lod_screen_size"],
    )

    print("\n--- raw dir(unreal.StaticMeshReductionOptions), non-dunder only "
          "(ground truth for its actual field names) ---")
    cls = getattr(unreal, "StaticMeshReductionOptions", None)
    if cls is None:
        print("  MISSING  unreal.StaticMeshReductionOptions (class itself not found)")
    else:
        for name in sorted(dir(cls)):
            if not name.startswith("_"):
                print(f"  {name}")

    print("\n--- dir(unreal) entries containing 'Reduction' (to find the nested "
          "per-LOD struct type set_lods()'s reduction_options actually wants) ---")
    for name in sorted(dir(unreal)):
        if "Reduction" in name:
            print(f"  {name}")

    # 2026-09-09: StaticMeshReductionOptions.reduction_settings is an array of
    # StaticMeshReductionSettings (per-LOD entry) -- ground-truth its fields the
    # same way, plus the real termination-criterion enum this fork actually has
    # (unreal.StaticMeshReductionTerimationCriterion -- note the fork's own typo
    # in the name, confirmed from the dir(unreal) scan above; MeshReductionTermination-
    # Criterion, which was guessed earlier, does not exist here).
    print("\n--- raw dir(unreal.StaticMeshReductionSettings), non-dunder only "
          "(per-LOD entry inside StaticMeshReductionOptions.reduction_settings) ---")
    cls = getattr(unreal, "StaticMeshReductionSettings", None)
    if cls is None:
        print("  MISSING  unreal.StaticMeshReductionSettings (class itself not found)")
    else:
        for name in sorted(dir(cls)):
            if not name.startswith("_"):
                print(f"  {name}")

    print("\n--- StaticMeshReductionTerimationCriterion enum members (this fork's "
          "actual name/spelling for the termination-criterion enum) ---")
    _print_enum_by_name("StaticMeshReductionTerimationCriterion")

    # 2026-09-09: gating two more pieces of audit_fix_meshes.py before writing it --
    # a progress-bar mechanism for the potentially-long "whole scope" Fix Meshes
    # button, and the real struct name/fields for Nanite settings (only ever READ
    # via the "NaniteEnabled" registry tag so far -- writing nanite_settings.enabled
    # has never been attempted on this fork).
    print("\n--- unreal.ScopedSlowTask (progress bar for a long-running batch fix) ---")
    slow_task_cls = getattr(unreal, "ScopedSlowTask", None)
    if slow_task_cls is None:
        print("  MISSING  unreal.ScopedSlowTask (class itself not found on this fork)")
    else:
        for name in ["enter_progress_frame", "should_cancel", "make_dialog"]:
            status = "OK" if hasattr(slow_task_cls, name) else "MISSING"
            print(f"  {status:<8} {name}")

    print("\n--- dir(unreal) entries containing 'Nanite' (real struct name for "
          "mesh.get_editor_property('nanite_settings')) ---")
    for name in sorted(dir(unreal)):
        if "Nanite" in name:
            print(f"  {name}")

    print("\n--- raw dir(unreal.MeshNaniteSettings), non-dunder only (guessed name -- "
          "MISSING here just means check the dir(unreal) dump above for the real one) ---")
    cls = getattr(unreal, "MeshNaniteSettings", None)
    if cls is None:
        print("  MISSING  unreal.MeshNaniteSettings (class itself not found under this name)")
    else:
        for name in sorted(dir(cls)):
            if not name.startswith("_"):
                print(f"  {name}")

    _check_class_methods(
        "unreal.StaticMeshComponent",
        unreal.StaticMeshComponent,
        ["get_num_materials", "get_material"],
    )

    _check_class_methods(
        "unreal.EditorUtilityLibrary (used by audit_actions.py to read the "
        "Content Browser selection for the panel)",
        unreal.EditorUtilityLibrary,
        ["get_selected_folder_paths", "get_selected_asset_data"],
    )

    # audit_config.get_project_dir() resolves <Project>/Saved/BudgetGuard (the
    # per-project override config + exports) through this call. Unconfirmed on
    # the engine; if it's MISSING the config falls back to the legacy
    # two-folders-above-Content/Python guess, which breaks a repo-linked install.
    _check_module_class_methods(
        "unreal.SystemLibrary (used by audit_config.get_project_dir())",
        "SystemLibrary",
        ["get_project_directory"],
    )
    try:
        import audit_config
        print(f"    audit_config resolves project dir: {audit_config.get_project_dir()}")
        print(f"    audit_config data dir:             {audit_config.get_data_dir()}")
        print(f"    config sources in force:           {audit_config.get_config_sources()}")
    except Exception as exc:
        print(f"    audit_config check FAILED: {exc!r}")

    # 2026-09-09: tag_existing_content.py's bootstrap run() was calling
    # save_asset() once per tagged asset -- the dominant cost on a large
    # tree. Checking for a batched save entry point before trusting
    # _save_tagged_assets()'s batch path at scale.
    _check_module_class_methods(
        "unreal.EditorLoadingAndSavingUtils (batched save, used by "
        "tag_existing_content.py's _save_tagged_assets)",
        "EditorLoadingAndSavingUtils",
        ["save_packages", "save_dirty_packages"],
    )
    print("\n--- __doc__ for save_packages (read the exact signature here "
          "before trusting the batch save path) ---")
    save_packages_fn = getattr(
        getattr(unreal, "EditorLoadingAndSavingUtils", None), "save_packages", None
    )
    if save_packages_fn is None:
        print("    MISSING")
    else:
        doc = getattr(save_packages_fn, "__doc__", None) or "    (no docstring)"
        for line in doc.strip().splitlines():
            print(f"    {line}")

    # Confirmed on 2026-09-07: unreal.CollectionScriptingLibrary does not
    # exist at all on this engine (UE 5.7.4 vanilla, Epic Launcher build) --
    # zero classes with "Collection" in the name anywhere in dir(unreal).
    # Collections cannot be created/populated from Python here, full stop.
    # build_tier_collections.py instead SELECTS tagged assets in the Content
    # Browser (sync_browser_to_objects, checked below) so a native "Add to
    # Collection" right-click does the rest.
    _check_class_methods(
        "unreal.EditorAssetLibrary -- sync_browser_to_objects (used by "
        "build_tier_collections.py to select a tier's tagged assets in the "
        "Content Browser)",
        unreal.EditorAssetLibrary,
        ["sync_browser_to_objects"],
    )

    print("\n--- EditorActorSubsystem availability ---")
    try:
        sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        print("  OK — has get_all_level_actors:", hasattr(sub, "get_all_level_actors"))
    except Exception as e:
        print("  FAILED:", e)
        print("  Fallback (EditorLevelLibrary.get_all_level_actors) will be used instead.")

    print("\n--- CollisionTraceFlag enum members ---")
    _print_enum(unreal.CollisionTraceFlag)

    print("\n--- BlendMode enum members ---")
    _print_enum(unreal.BlendMode)

    print("\n--- TextureGroup members containing 'WORLD' ---")
    _print_enum(unreal.TextureGroup, filter_substr="WORLD")

    print("\n--- TextureGroup members containing 'PROJECT' (used by audit_fix_textures.py's "
          "custom-group-per-tier fix — must match audit_budgets.json's texture_groups values) ---")
    _print_enum(unreal.TextureGroup, filter_substr="PROJECT")

    print("\n--- TextureCompressionSettings members containing 'NORMAL' ---")
    _print_enum(unreal.TextureCompressionSettings, filter_substr="NORMAL")

    print("\n--- Manual checks (need a real loaded asset, can't auto-verify) ---")
    print("  Load any StaticMesh and run:")
    print("    mesh = unreal.load_asset('/Game/PathToYourMesh.YourMesh')")
    print("    print(mesh.get_editor_property('nanite_settings'))")
    print("    print(mesh.get_editor_property('body_setup').get_editor_property('collision_trace_flag'))")
    print("  Load any Material and run:")
    print("    mat = unreal.load_asset('/Game/PathToYourMaterial.YourMaterial')")
    print("    print(mat.get_used_textures())")
    print("  Load any Texture2D and run (used by audit_fix_textures.py's resolution")
    print("  override fix, never touched by this toolkit before):")
    print("    tex = unreal.load_asset('/Game/PathToYourTexture.YourTexture')")
    print("    print(tex.get_editor_property('max_texture_size'))")
    print("  For the LOD generation fix (audit_fix_meshes.py) — run against a")
    print("  DUPLICATED test mesh only, never a production asset:")
    print("    mesh = unreal.load_asset('/Game/PathToYourTestMesh.YourTestMesh')")
    print("    print(mesh.get_editor_property('lod_group'))")
    print("    print(len(mesh.get_editor_property('source_models')))")

    print("\n" + "=" * 78)
    print("Done. Fix any MISSING/FAILED lines in the relevant module before a full run.")
    print("=" * 78)


def _check_class_methods(label, cls, method_names):
    print(f"\n--- {label} ---")
    for name in method_names:
        exists = hasattr(cls, name)
        status = "OK" if exists else "MISSING"
        print(f"  {status:<8} {name}")


def _check_module_class_methods(label, class_name, method_names):
    """Like _check_class_methods, but looks the class up on the unreal
    module by NAME at call time instead of taking the class object as an
    argument -- so a class that doesn't exist at all on this fork (e.g.
    unreal.CollectionScriptingLibrary) prints as MISSING instead of raising
    an AttributeError before run() even gets here."""
    print(f"\n--- {label} ---")
    cls = getattr(unreal, class_name, None)
    if cls is None:
        print(f"  MISSING  unreal.{class_name} (class itself not found on this fork)")
        return
    for name in method_names:
        exists = hasattr(cls, name)
        status = "OK" if exists else "MISSING"
        print(f"  {status:<8} {name}")


def _print_enum(enum_cls, filter_substr=None):
    for member in list(enum_cls):
        name = str(member)
        if filter_substr and filter_substr not in name.upper():
            continue
        print(f"  {name}")


def _print_enum_by_name(enum_class_name, filter_substr=None):
    """Like _print_enum, but looks the enum up on the unreal module by NAME
    at call time, so an enum that doesn't exist at all on this fork prints
    as MISSING instead of raising an AttributeError before run() gets here."""
    enum_cls = getattr(unreal, enum_class_name, None)
    if enum_cls is None:
        print(f"  MISSING  unreal.{enum_class_name} (enum itself not found on this fork)")
        return
    _print_enum(enum_cls, filter_substr=filter_substr)


if __name__ == "__main__":
    run()
