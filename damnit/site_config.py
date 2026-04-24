"""Helpers to load and use site-specific DAMNIT configuration.

The goal is to keep DAMNIT deployable in different labs without patching code.
Configuration is loaded from a JSON file near the database directory and can
reference secrets from environment variables (including a local `.env` file).
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import socket
from copy import deepcopy
from glob import glob
from pathlib import Path
from typing import Any

DEFAULT_CONTEXT_PYTHON = (
    "/gpfs/exfel/sw/software/euxfel-environment-management/environments/202502/"
    ".pixi/envs/default/bin/python"
)
DEFAULT_DAMNIT_PYTHON = (
    "/gpfs/exfel/sw/software/xfel_anaconda3/amore-mid/.pixi/envs/default/bin/python"
)

DEFAULT_SITE_CONFIG = {
    "profile": "xfel",
    "site_env_file": ".damnit.env",
    "lab": {
        "name": "European XFEL",
        "proposal_required": True,
        "data_roots": [],
        "data_root_env": "XFEL_DATA_ROOT",
        "data_root_default": "/gpfs/exfel/exp",
        "proposal_glob": "*/*/p{proposal:06d}",
        "damnit_directory_name": "usr/Shared/amore",
    },
    "auth": {
        "provider": "xfel",
        "ldap": {
            "server": "",
            "base_dn": "",
            "user_attribute": "uid",
        },
        "helmholtz": {
            "issuer_url": "",
            "client_id": "",
            "scopes": "openid profile email",
        },
    },
    "runtime": {
        "default_context_python": DEFAULT_CONTEXT_PYTHON,
        "default_damnit_python": DEFAULT_DAMNIT_PYTHON,
    },
    "kafka": {
        "update_brokers": ["exflwgs06.desy.de:9091"],
        "update_topic_template": "test.damnit.db-{db_id}",
        "file_submit_topic": "test.damnit.file_submissions",
        "listener_profiles": {
            "maxwell": {
                "brokers": ["exflwgs06:9091"],
                "topics": ["test.r2d2", "cal.offline-corrections"],
                "events": ["migration_complete", "run_corrections_complete"],
            },
            "onc": {
                "brokers": ["exflwgs06:9091"],
                "topics": ["test.euxfel.hed.daq", "test.euxfel.hed.cal"],
                "events": ["daq_run_complete", "online_correction_complete"],
            },
        },
        "hostname_profiles": [
            {"pattern": "exflonc*", "profile": "onc"},
            {"pattern": "*", "profile": "maxwell"},
        ],
    },
    "listener": {
        "default_profile": "maxwell",
        "auto_add_official_databases": True,
    },
    "data_sources": {
        "mongodb": {},
        "planned_ingest": {
            "hdf5": {"enabled": False, "watch_dir": ""},
            "kafka": {"enabled": False, "profile": "", "topic": ""},
            "bigdata": {"enabled": False, "endpoint": "", "token_env": ""},
        },
    },
}

HZDR_SITE_CONFIG_TEMPLATE = {
    "profile": "hzdr",
    "site_env_file": ".damnit.env",
    "lab": {
        "name": "HZDR",
        "proposal_required": False,
        "data_roots": ["$DAMNIT_HZDR_DATA_ROOT"],
        "data_root_env": "DAMNIT_HZDR_DATA_ROOT",
        "data_root_default": "",
        "proposal_glob": "{proposal}",
        "damnit_directory_name": "usr/Shared/amore",
    },
    "auth": {
        "provider": "helmholtz",
        "ldap": {
            "server": "$DAMNIT_LDAP_SERVER",
            "base_dn": "$DAMNIT_LDAP_BASE_DN",
            "user_attribute": "uid",
        },
        "helmholtz": {
            "issuer_url": "$DAMNIT_HELMHOLTZ_ISSUER",
            "client_id": "$DAMNIT_HELMHOLTZ_CLIENT_ID",
            "scopes": "openid profile email",
        },
    },
    "runtime": {
        "default_context_python": DEFAULT_CONTEXT_PYTHON,
        "default_damnit_python": DEFAULT_DAMNIT_PYTHON,
    },
    "kafka": {
        "update_brokers": ["$DAMNIT_HZDR_UPDATE_BROKER"],
        "update_topic_template": "damnit.db.{db_id}",
        "file_submit_topic": "damnit.file_submissions",
        "listener_profiles": {
            "hzdr": {
                "brokers": ["$DAMNIT_HZDR_KAFKA_BROKER"],
                "topics": ["$DAMNIT_HZDR_KAFKA_TOPIC"],
                "events": ["hzdr_run_complete"],
            }
        },
        "hostname_profiles": [
            {"pattern": "*", "profile": "hzdr"},
        ],
    },
    "listener": {
        "default_profile": "hzdr",
        "auto_add_official_databases": False,
    },
    "data_sources": {
        "mongodb": {
            "labfrog": {
                "uri": "$DAMNIT_MONGODB_LABFROG_URI",
                "database": "labfrog",
                "collection": "shotsheet",
            }
        },
        "planned_ingest": {
            "hdf5": {
                "enabled": False,
                "watch_dir": "$DAMNIT_HZDR_HDF5_WATCH_DIR",
            },
            "kafka": {
                "enabled": True,
                "profile": "hzdr",
                "topic": "$DAMNIT_HZDR_KAFKA_TOPIC",
            },
            "bigdata": {
                "enabled": False,
                "endpoint": "$DAMNIT_HZDR_BIGDATA_ENDPOINT",
                "token_env": "DAMNIT_HZDR_BIGDATA_TOKEN",
            },
        },
    },
}

SITE_CONFIG_CANDIDATES = (
    "damnit-site.json",
    ".damnit-site.json",
    ".damnit/site.json",
)
ENV_VAR_PATTERN = re.compile(r"\$(?:\{([^}]+)\}|([A-Za-z_][A-Za-z0-9_]*))")


def _deep_merge_dict(base: dict, override: dict) -> dict:
    merged = deepcopy(base)
    for key, value in override.items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = _deep_merge_dict(existing, value)
        else:
            merged[key] = deepcopy(value)
    return merged


def _expand_env_vars(obj: Any, env: dict[str, str]) -> Any:
    if isinstance(obj, dict):
        return {k: _expand_env_vars(v, env) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_expand_env_vars(v, env) for v in obj]
    if isinstance(obj, str):
        return ENV_VAR_PATTERN.sub(
            lambda m: env.get(m.group(1) or m.group(2), m.group(0)), obj
        )
    return obj


def _read_env_file(path: Path | None) -> dict[str, str]:
    if path is None or not path.is_file():
        return {}

    env = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        env[key] = value
    return env


def find_site_config_path(base_dir: Path | None = None) -> Path | None:
    if explicit := os.environ.get("DAMNIT_SITE_CONFIG"):
        return Path(explicit).expanduser()

    base = (base_dir or Path.cwd()).absolute()
    for folder in (base, *base.parents):
        for name in SITE_CONFIG_CANDIDATES:
            candidate = folder / name
            if candidate.is_file():
                return candidate
    return None


def _resolve_env_file_path(
    site_cfg: dict[str, Any], base_dir: Path, config_path: Path | None
) -> Path | None:
    if explicit := os.environ.get("DAMNIT_SITE_ENV"):
        return Path(explicit).expanduser()

    env_relpath = site_cfg.get("site_env_file", ".damnit.env")
    if not env_relpath:
        return None

    env_path = Path(env_relpath).expanduser()
    if env_path.is_absolute():
        return env_path
    if config_path is not None:
        return config_path.parent / env_path
    return base_dir / env_path


def load_site_config(base_dir: Path | None = None) -> dict[str, Any]:
    base = (base_dir or Path.cwd()).absolute()
    cfg_path = find_site_config_path(base)

    cfg = deepcopy(DEFAULT_SITE_CONFIG)
    if cfg_path is not None and cfg_path.is_file():
        loaded = json.loads(cfg_path.read_text())
        if not isinstance(loaded, dict):
            raise ValueError(f"Expected object at top of {cfg_path}")
        cfg = _deep_merge_dict(cfg, loaded)

    env_path = _resolve_env_file_path(cfg, base, cfg_path)
    env_from_file = _read_env_file(env_path)
    env = dict(env_from_file)
    env.update(os.environ)

    return _expand_env_vars(cfg, env)


def write_site_config_template(
    target_dir: Path, profile: str = "hzdr", force: bool = False
) -> tuple[Path, Path]:
    target_dir = target_dir.absolute()
    cfg_path = target_dir / "damnit-site.json"
    env_example_path = target_dir / ".damnit.env.example"

    if cfg_path.exists() and not force:
        raise FileExistsError(f"{cfg_path} already exists")
    if env_example_path.exists() and not force:
        raise FileExistsError(f"{env_example_path} already exists")

    if profile == "hzdr":
        template = HZDR_SITE_CONFIG_TEMPLATE
        env_example = """\
# Optional auth settings
DAMNIT_LDAP_SERVER=ldap.example.org
DAMNIT_LDAP_BASE_DN=dc=example,dc=org
DAMNIT_HELMHOLTZ_ISSUER=https://login.helmholtz.de/auth/realms/helmholtz
DAMNIT_HELMHOLTZ_CLIENT_ID=damnit

# HZDR data locations and event streams
DAMNIT_HZDR_DATA_ROOT=/data/hzdr
DAMNIT_HZDR_KAFKA_BROKER=kafka.hzdr.de:9092
DAMNIT_HZDR_KAFKA_TOPIC=labfrog.runs
DAMNIT_HZDR_UPDATE_BROKER=kafka.hzdr.de:9092

# LabFrog / ShotSheet MongoDB
DAMNIT_MONGODB_LABFROG_URI=mongodb://user:pass@mongo.hzdr.de:27017

# Planned future ingestion modes
DAMNIT_HZDR_HDF5_WATCH_DIR=/data/hzdr/incoming-hdf5
DAMNIT_HZDR_BIGDATA_ENDPOINT=https://bigdata.hzdr.de/api
DAMNIT_HZDR_BIGDATA_TOKEN=
"""
    elif profile == "xfel":
        template = DEFAULT_SITE_CONFIG
        env_example = """\
# Optional override to route update traffic through another broker
AMORE_BROKER=
"""
    else:
        raise ValueError(f"Unknown profile: {profile!r}")

    cfg_path.write_text(json.dumps(template, indent=2, sort_keys=True) + "\n")
    env_example_path.write_text(env_example)
    return cfg_path, env_example_path


def _get_nested(cfg: dict[str, Any], keys: list[str], default):
    cur = cfg
    for key in keys:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


def get_update_brokers(base_dir: Path | None = None) -> list[str]:
    if "AMORE_BROKER" in os.environ:
        return [os.environ["AMORE_BROKER"]]
    cfg = load_site_config(base_dir)
    brokers = _get_nested(cfg, ["kafka", "update_brokers"], [])
    return list(brokers) if isinstance(brokers, list) else []


def get_update_topic_template(base_dir: Path | None = None) -> str:
    cfg = load_site_config(base_dir)
    return str(
        _get_nested(
            cfg,
            ["kafka", "update_topic_template"],
            "test.damnit.db-{db_id}",
        )
    )


def format_update_topic(db_id: str, base_dir: Path | None = None) -> str:
    template = get_update_topic_template(base_dir)
    if "{db_id}" in template:
        return template.format(db_id=db_id)
    # Backward compatibility with old "{}"-style template.
    return template.format(db_id)


def get_file_submit_topic(base_dir: Path | None = None) -> str:
    cfg = load_site_config(base_dir)
    return str(
        _get_nested(
            cfg,
            ["kafka", "file_submit_topic"],
            "test.damnit.file_submissions",
        )
    )


def get_default_context_python(base_dir: Path | None = None) -> str:
    cfg = load_site_config(base_dir)
    return str(
        _get_nested(
            cfg,
            ["runtime", "default_context_python"],
            DEFAULT_CONTEXT_PYTHON,
        )
    )


def get_default_damnit_python(base_dir: Path | None = None) -> str:
    cfg = load_site_config(base_dir)
    return str(
        _get_nested(
            cfg,
            ["runtime", "default_damnit_python"],
            DEFAULT_DAMNIT_PYTHON,
        )
    )


def proposal_is_required(base_dir: Path | None = None) -> bool:
    cfg = load_site_config(base_dir)
    return bool(_get_nested(cfg, ["lab", "proposal_required"], True))


def listener_auto_add_official_databases(base_dir: Path | None = None) -> bool:
    cfg = load_site_config(base_dir)
    return bool(_get_nested(cfg, ["listener", "auto_add_official_databases"], True))


def listener_kafka_conf(
    base_dir: Path | None = None,
    hostname: str | None = None,
) -> tuple[str, dict[str, Any]]:
    cfg = load_site_config(base_dir)
    kafka_cfg = cfg.get("kafka", {})
    listener_cfg = cfg.get("listener", {})

    if explicit := os.environ.get("DAMNIT_LISTENER_PROFILE"):
        profile_name = explicit
    else:
        host = hostname or socket.gethostname()
        profile_name = None
        for matcher in kafka_cfg.get("hostname_profiles", []):
            if fnmatch.fnmatch(host, str(matcher.get("pattern", ""))):
                profile_name = str(matcher.get("profile", ""))
                break
        if not profile_name:
            profile_name = str(listener_cfg.get("default_profile", "maxwell"))

    profile_cfg = (
        kafka_cfg.get("listener_profiles", {}).get(profile_name)
        or DEFAULT_SITE_CONFIG["kafka"]["listener_profiles"]["maxwell"]
    )
    return profile_name, profile_cfg


def _parse_proposal(proposal: int | str) -> int:
    if isinstance(proposal, str):
        prop_s = proposal.strip().lower()
        if prop_s.startswith("p"):
            prop_s = prop_s[1:]
        if not prop_s.isdigit():
            raise ValueError(f"Invalid proposal identifier: {proposal!r}")
        return int(prop_s)
    return int(proposal)


def find_proposal_dir(proposal: int | str, base_dir: Path | None = None) -> Path:
    proposal_num = _parse_proposal(proposal)
    cfg = load_site_config(base_dir)
    lab_cfg = cfg.get("lab", {})

    roots = [Path(x) for x in lab_cfg.get("data_roots", []) if x]
    if not roots:
        root_env = str(lab_cfg.get("data_root_env", "XFEL_DATA_ROOT"))
        root_default = str(lab_cfg.get("data_root_default", "/gpfs/exfel/exp"))
        root = os.environ.get(root_env, root_default)
        if root:
            roots.append(Path(root))

    pattern_tmpl = str(lab_cfg.get("proposal_glob", "*/*/p{proposal:06d}"))
    pattern = pattern_tmpl.format(proposal=proposal_num)

    matches = []
    for root in roots:
        if Path(pattern).is_absolute():
            paths = glob(pattern)
        else:
            paths = glob(str(root / pattern))
        matches.extend(Path(p) for p in paths)

    if not matches:
        raise FileNotFoundError(f"Couldn't find proposal dir for {proposal!r}")

    return sorted(matches)[0]


def official_damnit_dir_for_proposal(
    proposal: int | str, base_dir: Path | None = None
) -> Path:
    proposal_path = find_proposal_dir(proposal, base_dir=base_dir)
    cfg = load_site_config(base_dir)
    subdir = str(
        _get_nested(cfg, ["lab", "damnit_directory_name"], "usr/Shared/amore")
    )
    return proposal_path / subdir
