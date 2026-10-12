"""
audit_config.py
------------------------------------------------------------------------------
Loads and provides access to BudgetGuard's configuration.

Configuration is layered, so the tool stays project-agnostic:

  1. Defaults   - audit_budgets.json next to this file (ships with the tool,
                  generic, identical for every project it is installed in).
  2. Profile    - profile_<id>.json next to this file: a platform rule set
                  (tier budgets, texture/LOD groups, rule severities), e.g.
                  profile_mobile_vr_quest3.json. Chosen by the override's
                  "profile" key, else the defaults' "default_profile".
  3. Overrides  - <Project>/Saved/BudgetGuard/config.json, OPTIONAL. Holds only
                  what one project wants different: its own tier numbers, tag
                  rules (folder keywords), extra excluded folders, rule
                  severities. Lives in the project, so updating the tool never
                  overwrites a project's tuning.

Merge rule: JSON objects are merged key by key (so a project can change one
number of one tier), everything else - lists, scalars - is REPLACED by the
override. Exclusions are the one additive case, via the separate
"extra_excluded_path_fragments" key (the defaults stay in force).

Kept deliberately simple: no schema validation beyond "did it parse" - the
numeric budgets are provisional (see the "status" field) and are meant to be
hand-edited without touching any Python code. A override file that exists but
does not parse RAISES instead of silently falling back to defaults: auditing
against numbers the project did not choose would be worse than failing.

The project directory is resolved, in order, from the BUDGETGUARD_PROJECT_DIR
environment variable, then the running Editor's project directory, then (the
legacy flat <Project>/Content/Python deploy) two folders above this file.
------------------------------------------------------------------------------
"""

import copy
import json
import os
import shutil

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
# Repo layout keeps the JSON in <repo>/config/ (this file is in <repo>/src/); the legacy
# flat Content/Python deploy copies it next to this file, so fall back to that.
_REPO_CONFIG_DIR = os.path.join(os.path.dirname(_THIS_DIR), "config")
_CONFIG_DIR = _REPO_CONFIG_DIR if os.path.isdir(_REPO_CONFIG_DIR) else _THIS_DIR
DEFAULT_CONFIG_PATH = os.path.join(_CONFIG_DIR, "audit_budgets.json")

DATA_DIR_NAME = "BudgetGuard"          # <Project>/Saved/BudgetGuard/
PROJECT_CONFIG_NAME = "config.json"    # the per-project override file
PROFILE_PREFIX = "profile_"            # profile_<id>.json, in config/ (flat next to this file in a legacy deploy)
ENV_PROJECT_DIR = "BUDGETGUARD_PROJECT_DIR"

_cache = None
_sources = []   # files the cached config was built from, defaults first


# ---------------------------------------------------------------------------
# Project location
# ---------------------------------------------------------------------------

def get_project_dir():
    """Absolute path of the UE project root (the folder holding the
    .uproject), or None when it can't be resolved."""
    env = os.environ.get(ENV_PROJECT_DIR)
    if env and os.path.isdir(env):
        return os.path.abspath(env)

    try:
        import unreal
        project_dir = unreal.SystemLibrary.get_project_directory()
        if project_dir:
            return os.path.abspath(str(project_dir))
    except Exception:
        pass  # not inside the Editor, or the call isn't on this build

    try:
        import unreal
        project_dir = unreal.Paths.project_dir()   # repo-linked install: this file isn't under the project
        if project_dir:
            return os.path.abspath(str(project_dir))
    except Exception:
        pass

    legacy = os.path.abspath(os.path.join(_THIS_DIR, "..", ".."))
    if _has_uproject(legacy):
        return legacy
    return None


def _has_uproject(folder):
    try:
        return any(name.lower().endswith(".uproject") for name in os.listdir(folder))
    except OSError:
        return False


def get_project_name():
    """The .uproject's file name without extension (e.g. "MyGame"), or
    "Project" when it can't be resolved. Used to title reports/dashboards."""
    project_dir = get_project_dir()
    if project_dir:
        try:
            for name in sorted(os.listdir(project_dir)):
                if name.lower().endswith(".uproject"):
                    return os.path.splitext(name)[0]
        except OSError:
            pass
    return "Project"


def get_data_dir():
    """<Project>/Saved/BudgetGuard - per-machine output (exports, history) and
    the project's override config. Falls back to a folder next to this file
    when the project can't be resolved, so a standalone run still has
    somewhere to write."""
    project_dir = get_project_dir()
    if project_dir:
        return os.path.join(project_dir, "Saved", DATA_DIR_NAME)
    return os.path.join(_THIS_DIR, "Saved", DATA_DIR_NAME)


def get_project_config_path():
    return os.path.join(get_data_dir(), PROJECT_CONFIG_NAME)


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def _read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _deep_merge(base, override):
    """Objects merge key by key; anything else in `override` replaces `base`
    (an empty object too - that is how a project clears e.g. tag_rules)."""
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and value and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def profile_path(profile_id):
    return os.path.join(_CONFIG_DIR, f"{PROFILE_PREFIX}{profile_id}.json")


def list_profiles():
    """[{"id", "label", "description"}, ...] for every profile_*.json shipped
    with the tool - what the Settings profile picker offers."""
    profiles = []
    for name in sorted(os.listdir(_CONFIG_DIR)):
        if name.startswith(PROFILE_PREFIX) and name.endswith(".json"):
            data = _read_json(os.path.join(_CONFIG_DIR, name))
            pid = data.get("profile_id", name[len(PROFILE_PREFIX):-5])
            profiles.append({"id": pid, "label": data.get("label", pid),
                             "description": data.get("description", "")})
    return profiles


def load_config(path=None):
    """The merged config (cached). With an explicit `path`, loads that single
    file as-is - no layering, no cache - which is what tests and one-off
    experiments want."""
    global _cache, _sources
    if path is not None:
        return _read_json(path)
    if _cache is not None:
        return _cache

    cfg = _read_json(DEFAULT_CONFIG_PATH)
    sources = [DEFAULT_CONFIG_PATH]

    override = None
    override_path = get_project_config_path()
    if os.path.isfile(override_path):
        try:
            override = _read_json(override_path)
        except ValueError as exc:
            raise ValueError(
                f"BudgetGuard: project config {override_path} is not valid JSON ({exc}). "
                f"Fix or delete it - the tool will not fall back to defaults silently."
            ) from exc

    profile_id = (override or {}).get("profile") or cfg.get("default_profile")
    if profile_id:
        path_ = profile_path(profile_id)
        if not os.path.isfile(path_):
            raise FileNotFoundError(f"BudgetGuard: profile '{profile_id}' not found ({path_}).")
        cfg = _deep_merge(cfg, _read_json(path_))
        sources.append(path_)
    cfg["active_profile"] = profile_id

    if override is not None:
        cfg = _deep_merge(cfg, override)
        sources.append(override_path)

    _cache = cfg
    _sources = sources
    return _cache


def reload_config():
    """Drops the cache so the next accessor call re-reads both files."""
    global _cache, _sources
    _cache = None
    _sources = []
    return load_config()


def get_config_sources():
    """Files the active config was built from, defaults first - for logging
    and for showing the user which project overrides are in force."""
    load_config()
    return list(_sources)


# ---------------------------------------------------------------------------
# Accessors
# ---------------------------------------------------------------------------

def get_tier_budget(tier, cfg=None):
    cfg = cfg or load_config()
    return cfg["tiers"].get(tier, cfg["tiers"][cfg["default_tier"]])


def get_all_tiers(cfg=None):
    """Read-only view of every tier's budget, keyed by tier name - for
    display/reflection purposes (e.g. the panel's tier reference). Callers
    must not mutate the returned dict."""
    cfg = cfg or load_config()
    return cfg["tiers"]


def get_all_rules(cfg=None):
    """Read-only view of every rule's configured severity/threshold - same
    display purpose as get_all_tiers(). Callers must not mutate the
    returned dict."""
    cfg = cfg or load_config()
    return cfg["rules"]


def get_default_tier(cfg=None):
    cfg = cfg or load_config()
    return cfg["default_tier"]


def get_rule_severity(rule_name, cfg=None):
    cfg = cfg or load_config()
    return cfg["rules"].get(rule_name, "WARN")


def get_active_profile(cfg=None):
    cfg = cfg or load_config()
    return cfg.get("active_profile")


def get_rule_catalog(cfg=None):
    """[{"id", "category", "label", "description", "extra"?}, ...] - the rules
    the Settings panel lists, each with its effective severity and on/off."""
    cfg = cfg or load_config()
    return [dict(r, severity=get_rule_severity(r["id"], cfg),
                 enabled=is_rule_enabled(r["id"], cfg)) for r in cfg.get("rule_catalog", [])]


def is_rule_enabled(rule_name, cfg=None):
    """False when the rule's severity is "OFF" - how a project opts out of a
    rule that assumes a target platform it doesn't have (e.g. nanite_enabled
    on a desktop project that uses Nanite). Rules absent from the config stay
    enabled (severity falls back to WARN, see get_rule_severity). A rule
    listed in "disabled_rules" (the Settings panel's per-rule switch) is also
    off, without losing the profile's severity for when it is switched back on."""
    cfg = cfg or load_config()
    if rule_name in cfg.get("disabled_rules", []):
        return False
    return get_rule_severity(rule_name, cfg).upper() != "OFF"


def get_texture_group(tier, cfg=None):
    """Custom unreal.TextureGroup enum member name (string) configured for
    this tier under "texture_groups", or None if the tier has no custom
    group (e.g. "utility" - falls back to the resolution override fix
    instead, see audit_fix_textures.py)."""
    cfg = cfg or load_config()
    return cfg.get("texture_groups", {}).get(tier)


def get_lod_group(tier, cfg=None):
    """Custom LOD Group name (string FName, not a unreal enum - unlike
    get_texture_group()'s TextureGroup) configured for this tier under
    "lod_groups", or None if the tier has no custom group configured yet.
    Mirrors get_texture_group()'s per-tier lookup so BudgetTier-driven
    LODGroup assignment (audit_fix_meshes.py) stays config-driven the same
    way the texture-group fix is - see audit_budgets.json's "lod_groups"
    section."""
    cfg = cfg or load_config()
    return cfg.get("lod_groups", {}).get(tier)


def get_lod_generation_targets(tier, cfg=None):
    """{"target_lod_count": int, "poly_fractions": [float, ...]} configured
    for this tier under "lod_generation_targets", or None if the tier has
    none configured (e.g. "utility"). poly_fractions is one entry per
    resulting LOD, LOD0 included - see audit_fix_meshes.py for how this feeds
    unreal.StaticMeshReductionOptions."""
    cfg = cfg or load_config()
    return cfg.get("lod_generation_targets", {}).get(tier)


def get_default_texture_groups(cfg=None):
    """Engine-default unreal.TextureGroup enum member names (strings) that
    count as "not yet governed by a project-specific tier group" - e.g. a
    normal map imported with no explicit group lands on
    TEXTUREGROUP_WORLD_NORMAL_MAP, not TEXTUREGROUP_WORLD, so a check that
    only recognized WORLD silently never matched normal maps. Callers
    resolve these names to actual enum members themselves (skipping any
    that don't exist on the current fork), same pattern as
    get_texture_group()'s configured per-tier group name."""
    cfg = cfg or load_config()
    return cfg.get("default_texture_groups", ["TEXTUREGROUP_WORLD"])


def get_tag_key(cfg=None):
    cfg = cfg or load_config()
    return cfg.get("tag_key", "BudgetTier")


def get_taggable_classes(cfg=None):
    """Asset class names the tagger/auditor consider. Everything else
    (Blueprints, Levels, Enums...) is skipped: tiering is a rendering-budget
    concept and doesn't apply to logic assets."""
    cfg = cfg or load_config()
    return set(cfg.get("taggable_classes", []))


def get_tag_rules(cfg=None):
    """{tier: [keyword, ...]} used by the bootstrap tagger. Checked in
    declared order, first match wins; keywords are case-insensitive
    substrings of the path. "hero" is never auto-assigned whatever it
    holds here - see tag_existing_content.py."""
    cfg = cfg or load_config()
    return cfg.get("tag_rules", {})


def get_excluded_path_fragments(cfg=None):
    """Defaults plus the project's own "extra_excluded_path_fragments"."""
    cfg = cfg or load_config()
    return list(cfg.get("excluded_path_fragments", [])) + list(
        cfg.get("extra_excluded_path_fragments", [])
    )


def is_excluded(asset_path, cfg=None):
    return any(frag in asset_path for frag in get_excluded_path_fragments(cfg))


# ---------------------------------------------------------------------------
# Writing the project override (Settings panel / first-run setup)
# ---------------------------------------------------------------------------

def has_project_config():
    return os.path.isfile(get_project_config_path())


def read_project_config():
    """The raw override dict ({} when the file doesn't exist). Raises like
    load_config() when it exists but isn't valid JSON."""
    path = get_project_config_path()
    if not os.path.isfile(path):
        return {}
    return _read_json(path)


def write_project_config(data):
    """Writes the whole override file (creating Saved/BudgetGuard/) and drops
    the cache so the next accessor call sees it. Returns the path."""
    path = get_project_config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    reload_config()
    return path


TEMPLATE_ABOUT = (
    "Project override. Every value below is the active profile's current value - edit the ones you "
    "want to change and DELETE the ones you don't (a deleted key keeps following the profile). "
    "tiers: per-tier budgets (null = no limit). rules: FAIL / WARN / OFF per rule, plus thresholds. "
    "Not listed here but supported: tag_rules (replaces the whole keyword list of a tier), "
    "disabled_rules, texture_groups, lod_groups, lod_generation_targets. "
    "Keys starting with _ are ignored. After saving press Reload scripts."
)


def build_template(profile_id=None):
    """A ready-to-edit override: the profile's tier budgets + rule severities/thresholds
    spelled out, so the user can see every number they may change."""
    profile_id = profile_id or load_config().get("active_profile")
    profile = _read_json(profile_path(profile_id))
    return {
        "_about": TEMPLATE_ABOUT,
        "profile": profile_id,
        "tiers": copy.deepcopy(profile.get("tiers", {})),
        "rules": copy.deepcopy(profile.get("rules", {})),
        "extra_excluded_path_fragments": [],
    }


def fill_template_if_blank():
    """Called when the user opens the override file: an empty file, bare {} or a profile-only
    override gets the template. Returns True if it wrote one. A file with real content is never touched."""
    path = get_project_config_path()
    if not os.path.isfile(path):
        return False
    with open(path, "r", encoding="utf-8") as f:
        text = f.read().strip()
    profile_id = None
    if text:
        try:
            data = json.loads(text)
        except ValueError:
            return False   # broken JSON: leave it for the user to fix
        if not isinstance(data, dict) or set(data) - {"profile", "_about"}:
            return False   # has real content
        profile_id = data.get("profile")
    # load_config() would raise on a blank file, so take the profile from the defaults directly
    write_project_config(build_template(profile_id or _read_json(DEFAULT_CONFIG_PATH).get("default_profile")))
    return True


# ---- named presets: snapshots of the override file, next to it in Saved/BudgetGuard/presets/ ----

PREVIOUS_PRESET = "_previous"   # auto-backup of the override taken right before a preset is loaded


def get_presets_dir():
    return os.path.join(os.path.dirname(get_project_config_path()), "presets")


def _preset_path(name):
    return os.path.join(get_presets_dir(), f"{name}.json")


def clean_preset_name(name):
    name = "".join(c if (c.isalnum() or c in "-_ .") else "_" for c in (name or "").strip()).strip(" .")
    if not name or name.startswith("_"):
        raise ValueError("Preset name must not be empty or start with '_' (reserved for the auto-backup).")
    return name


def list_presets():
    """Preset names, newest file first; the auto-backup (PREVIOUS_PRESET) comes last."""
    folder = get_presets_dir()
    if not os.path.isdir(folder):
        return []
    files = [f for f in os.listdir(folder) if f.endswith(".json")]
    files.sort(key=lambda f: os.path.getmtime(os.path.join(folder, f)), reverse=True)
    names = [f[:-5] for f in files]
    return [n for n in names if n != PREVIOUS_PRESET] + ([PREVIOUS_PRESET] if PREVIOUS_PRESET in names else [])


def save_preset(name, overwrite=False):
    """Snapshot the current override under `name`. Returns the preset path."""
    name = clean_preset_name(name)
    if not has_project_config():
        raise FileNotFoundError("No project override to save yet.")
    path = _preset_path(name)
    if os.path.exists(path) and not overwrite:
        raise FileExistsError(f"Preset '{name}' already exists.")
    read_project_config()   # raises if the current override isn't valid JSON - don't snapshot garbage
    os.makedirs(get_presets_dir(), exist_ok=True)
    shutil.copyfile(get_project_config_path(), path)
    return path


def load_preset(name):
    """Make preset `name` the active override. The override it replaces is first copied to
    presets/_previous.json (one rolling backup), so a load can always be undone."""
    path = _preset_path(name)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Preset '{name}' not found ({path}).")
    _read_json(path)   # refuse to activate a broken preset
    if has_project_config() and name != PREVIOUS_PRESET:
        os.makedirs(get_presets_dir(), exist_ok=True)
        shutil.copyfile(get_project_config_path(), _preset_path(PREVIOUS_PRESET))
    shutil.copyfile(path, get_project_config_path())
    reload_config()
    return path


def delete_preset(name):
    os.remove(_preset_path(name))


def create_project_config(profile_id, tag_rules="generic", extra_excluded=None, overwrite=False):
    """First-run setup: a minimal override picking `profile_id`.
    tag_rules: "generic" keeps the shipped starter keywords (nothing written),
    "empty" writes {} so nothing is auto-tagged until the project adds its own.
    Refuses to clobber an existing file unless overwrite=True."""
    if has_project_config() and not overwrite:
        raise FileExistsError(f"BudgetGuard: {get_project_config_path()} already exists.")
    if profile_id not in [p["id"] for p in list_profiles()]:
        raise ValueError(f"BudgetGuard: unknown profile '{profile_id}'.")
    data = build_template(profile_id)
    if tag_rules == "empty":
        data["tag_rules"] = {}
    if extra_excluded:
        data["extra_excluded_path_fragments"] = list(extra_excluded)
    return write_project_config(data)


def get_baseline(profile_id=None):
    """Defaults + the profile, no project override: what the project would get with an empty
    override. The Settings panel diffs the user's edits against this."""
    cfg = _read_json(DEFAULT_CONFIG_PATH)
    profile_id = profile_id or cfg.get("default_profile")
    if profile_id:
        cfg = _deep_merge(cfg, _read_json(profile_path(profile_id)))
    return cfg


def save_edits(profile_id, disabled_rules, tier_values, rule_values):
    """Settings-panel save. tier_values = {tier: {field: value|None}}, rule_values = {key: value}
    hold the values the panel manages; only those that differ from the profile baseline are
    stored (so the override stays short and everything else keeps following the profile).
    Override keys the panel doesn't manage are left alone. Returns the file path."""
    base = get_baseline(profile_id)
    data = read_project_config()
    data["profile"] = profile_id

    def _store(section, values, base_section, nested):
        cur = data.get(section) or {}
        for key, value in values.items():
            if nested:
                tier_cur = cur.get(key) or {}
                for field, v in value.items():
                    if v == (base_section.get(key) or {}).get(field):
                        tier_cur.pop(field, None)
                    else:
                        tier_cur[field] = v
                if tier_cur:
                    cur[key] = tier_cur
                else:
                    cur.pop(key, None)
            elif value == base_section.get(key):
                cur.pop(key, None)
            else:
                cur[key] = value
        if cur:
            data[section] = cur
        else:
            data.pop(section, None)

    _store("tiers", tier_values, base.get("tiers", {}), True)
    _store("rules", rule_values, base.get("rules", {}), False)
    # also drop leftovers the panel doesn't manage that merely repeat the profile (an old template)
    data["rules"] = {k: v for k, v in (data.get("rules") or {}).items() if v != base.get("rules", {}).get(k)}
    for tier, fields in list((data.get("tiers") or {}).items()):
        fields = {f: v for f, v in fields.items() if v != (base.get("tiers", {}).get(tier) or {}).get(f)}
        if fields:
            data["tiers"][tier] = fields
        else:
            data["tiers"].pop(tier)
    for section in ("tiers", "rules"):
        if not data.get(section):
            data.pop(section, None)
    if disabled_rules:
        data["disabled_rules"] = sorted(disabled_rules)
    else:
        data.pop("disabled_rules", None)
    return write_project_config(data)
