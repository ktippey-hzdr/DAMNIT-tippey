import json
from pathlib import Path

from damnit.backend.db import DamnitDB, initialize_proposal
from damnit.site_config import (
    find_proposal_dir,
    format_update_topic,
    get_update_brokers,
    listener_kafka_conf,
    load_site_config,
)


def test_load_site_config_expands_env(tmp_path):
    (tmp_path / "damnit-site.json").write_text(
        json.dumps(
            {
                "site_env_file": ".damnit.env",
                "kafka": {
                    "update_brokers": ["$TEST_BROKER"],
                    "update_topic_template": "damnit.db.{db_id}",
                },
                "data_sources": {
                    "mongodb": {
                        "labfrog": {
                            "uri": "$MONGO_URI",
                            "database": "shotsheet",
                            "collection": "shots",
                        }
                    }
                },
            }
        )
    )
    (tmp_path / ".damnit.env").write_text(
        "TEST_BROKER=test-broker:9092\nMONGO_URI=mongodb://localhost:27017\n"
    )

    cfg = load_site_config(tmp_path)
    assert cfg["kafka"]["update_brokers"] == ["test-broker:9092"]
    assert cfg["data_sources"]["mongodb"]["labfrog"]["uri"] == "mongodb://localhost:27017"
    assert get_update_brokers(tmp_path) == ["test-broker:9092"]
    assert format_update_topic("abc123", tmp_path) == "damnit.db.abc123"


def test_find_proposal_dir_uses_site_config(tmp_path):
    data_root = tmp_path / "data-root"
    proposal_dir = data_root / "p001234"
    proposal_dir.mkdir(parents=True)

    (tmp_path / "damnit-site.json").write_text(
        json.dumps(
            {
                "lab": {
                    "data_roots": [str(data_root)],
                    "proposal_glob": "p{proposal:06d}",
                }
            }
        )
    )

    assert find_proposal_dir(1234, tmp_path) == proposal_dir
    assert find_proposal_dir("p001234", tmp_path) == proposal_dir


def test_initialize_proposal_allows_missing_proposal_when_configured(tmp_path):
    db_dir = tmp_path / "db"
    db_dir.mkdir()
    (db_dir / "damnit-site.json").write_text(
        json.dumps({"lab": {"proposal_required": False}})
    )

    initialize_proposal(db_dir, proposal=None)
    db = DamnitDB.from_dir(db_dir)

    assert "proposal" not in set(db.metameta.keys())
    assert (db_dir / "context.py").is_file()


def test_listener_profile_resolution_from_site_config(tmp_path):
    (tmp_path / "damnit-site.json").write_text(
        json.dumps(
            {
                "kafka": {
                    "listener_profiles": {
                        "hzdr": {
                            "brokers": ["hzdr-kafka:9092"],
                            "topics": ["hzdr.topic"],
                            "events": ["hzdr_done"],
                        }
                    },
                    "hostname_profiles": [{"pattern": "hzdr-*", "profile": "hzdr"}],
                },
                "listener": {"default_profile": "hzdr"},
            }
        )
    )

    profile, conf = listener_kafka_conf(tmp_path, hostname="hzdr-node01")
    assert profile == "hzdr"
    assert conf["brokers"] == ["hzdr-kafka:9092"]
    assert conf["topics"] == ["hzdr.topic"]
    assert conf["events"] == ["hzdr_done"]
