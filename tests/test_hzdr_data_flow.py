import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import h5py
import pytest

from damnit.backend.combine import FileSubmissionProcessor
from damnit.backend.db import DamnitDB, MsgKind, initialize_proposal
from damnit.backend.extract_data import file_submit_msg
from damnit.backend.extraction_control import reprocess
from damnit.backend.listener import EventProcessor
from damnit.context import Cell, RunData, save_fragment


def write_hzdr_site_config(root):
    """Write the smallest local site config needed for HZDR data-flow tests."""
    (root / "damnit-site.json").write_text(
        json.dumps(
            {
                "profile": "hzdr-test",
                "lab": {"proposal_required": False},
                "listener": {
                    "auto_add_official_databases": False,
                    "default_profile": "hzdr",
                },
                "runtime": {
                    "default_context_python": "$UNSET_TEST_CONTEXT_PYTHON",
                    "default_damnit_python": "$UNSET_TEST_DAMNIT_PYTHON",
                },
                "kafka": {
                    "update_brokers": ["test-broker:9092"],
                    "file_submit_topic": "damnit.test.file_submissions",
                    "listener_profiles": {
                        "hzdr": {
                            "brokers": ["test-broker:9092"],
                            "topics": ["hzdr.test.runs"],
                            "events": ["hzdr_run_complete"],
                        }
                    },
                    "hostname_profiles": [{"pattern": "*", "profile": "hzdr"}],
                },
            }
        )
    )


def test_hzdr_kafka_run_complete_submits_all_data_extraction(tmp_path):
    """A run-ready Kafka event records the run and submits one extraction job."""
    write_hzdr_site_config(tmp_path)
    db_dir = tmp_path / "damnit-db"
    initialize_proposal(db_dir, proposal=1234)

    with patch("damnit.backend.listener.KafkaConsumer"):
        processor = EventProcessor(tmp_path)
    processor.db.add_proposal_db(1234, db_dir, official=False)

    record = MagicMock(
        timestamp=1_700_000_000_000,
        value=json.dumps(
            {"event": "hzdr_run_complete", "proposal": 1234, "run": 42}
        ).encode(),
    )

    with patch(
        "damnit.backend.extraction_control.ExtractionSubmitter.submit",
        return_value=("9876", "local"),
    ) as submit:
        processor._process_kafka_event(record)

    submitted_request = submit.call_args.args[0]
    assert submitted_request.proposal == 1234
    assert submitted_request.run == 42
    assert submitted_request.run_data is RunData.ALL

    with DamnitDB.from_dir(db_dir) as db:
        row = db.conn.execute(
            "SELECT proposal, run FROM run_info WHERE proposal=? AND run=?",
            (1234, 42),
        ).fetchone()
    assert tuple(row) == (1234, 42)


def test_ready_hdf5_fragment_message_combines_file_and_updates_db(tmp_path):
    """A ready HDF5 fragment is the payload DAMNIT combines into a run file."""
    write_hzdr_site_config(tmp_path)
    db_dir = tmp_path / "damnit-db"
    initialize_proposal(db_dir, proposal=1234)

    fragment_path = save_fragment(
        db_dir,
        1234,
        42,
        {
            "detector.mean": Cell(7.5),
            "detector.trace": Cell([1, 2, 3], summary="size"),
        },
        errors={},
        provenance="hzdr-test",
    )
    message = file_submit_msg(db_dir, 1234, 42, str(fragment_path))["data"]

    with patch("damnit.backend.combine.KafkaConsumer"), patch(
        "damnit.backend.combine.KafkaProducer"
    ):
        processor = FileSubmissionProcessor(tmp_path)
    processor.producer = MagicMock()

    processor.process_file_submission_msg(
        message,
        datetime.fromtimestamp(1_700_000_000, tz=timezone.utc),
    )

    combined_path = db_dir / "extracted_data" / "p1234_r42.h5"
    assert combined_path.is_file()
    assert not fragment_path.exists()
    with h5py.File(combined_path) as h5:
        assert h5["detector.mean/data"][()] == pytest.approx(7.5)
        assert h5[".reduced/detector.mean"][()] == pytest.approx(7.5)
        assert h5[".reduced/detector.trace"][()] == 3

    with DamnitDB.from_dir(db_dir) as db:
        rows = db.conn.execute(
            """
            SELECT name, value, provenance FROM run_variables
            WHERE proposal=? AND run=?
            ORDER BY name
            """,
            (1234, 42),
        ).fetchall()
    assert [(row["name"], row["value"], row["provenance"]) for row in rows] == [
        ("detector.mean", 7.5, "hzdr-test"),
        ("detector.trace", 3, "hzdr-test"),
    ]

    update_topic, update_message = processor.producer.send.call_args.args
    assert update_topic.startswith("test.damnit.db-")
    assert update_message["msg_kind"] == MsgKind.run_values_updated.value
    assert update_message["data"]["values"] == {
        "detector.mean": None,
        "detector.trace": None,
    }


def test_reprocess_only_submits_runs_that_exist_on_disk(tmp_path, monkeypatch, capsys):
    """Reprocessing real data still filters requested run numbers by run folders."""
    write_hzdr_site_config(tmp_path)
    db_dir = tmp_path / "damnit-db"
    initialize_proposal(db_dir, proposal=1234)
    monkeypatch.chdir(db_dir)

    monkeypatch.setattr(
        "damnit.backend.extraction_control.proposal_runs",
        lambda proposal: {42},
    )

    with patch(
        "damnit.backend.extraction_control.ExtractionSubmitter.submit_multi",
        return_value=[("9876", "local")],
    ) as submit_multi:
        reprocess(["42", "43"], proposal=1234)

    captured = capsys.readouterr()
    assert "skipping 1 runs because they don't exist: [43]" in captured.out

    submitted_requests = submit_multi.call_args.args[0]
    assert [(request.proposal, request.run) for request in submitted_requests] == [
        (1234, 42)
    ]
