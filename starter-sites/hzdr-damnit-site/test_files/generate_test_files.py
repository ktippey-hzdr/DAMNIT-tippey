"""Generate minimal HZDR-style HDF5 and Mongo test fixtures.

This keeps test data small, deterministic, and easy to regenerate.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import h5py
import numpy as np


@dataclass(frozen=True)
class ShotEntry:
    """Single shot record used by both HDF5 and Mongo fixtures."""

    run: int
    shot_number: int
    fired_at: str
    signal: float
    status: str
    target: str


def _build_shots() -> list[ShotEntry]:
    """Create a tiny, readable sequence of placeholder shot records."""
    base_time = datetime(2026, 5, 1, 9, 0, tzinfo=UTC)
    shots: list[ShotEntry] = []
    run_to_shot_start = {1: 1001, 2: 2001, 3: 3001}

    for run_number, start_shot in run_to_shot_start.items():
        for index in range(3):
            fired_at = base_time + timedelta(minutes=run_number * 10 + index)
            shots.append(
                ShotEntry(
                    run=run_number,
                    shot_number=start_shot + index,
                    fired_at=fired_at.isoformat(),
                    signal=round(0.5 * run_number + 0.1 * index, 3),
                    status="ok" if index < 2 else "needs-review",
                    target=f"target-{run_number}",
                )
            )
    return shots


def _write_hdf5_files(output_dir: Path, shots: list[ShotEntry]) -> None:
    """Write one compact HDF5 file per run with shot-level datasets."""
    output_dir.mkdir(parents=True, exist_ok=True)
    shots_by_run: dict[int, list[ShotEntry]] = {}
    for shot in shots:
        shots_by_run.setdefault(shot.run, []).append(shot)

    for run_number, run_shots in shots_by_run.items():
        file_path = output_dir / f"hzdr_run_{run_number}.h5"
        with h5py.File(file_path, "w") as handle:
            handle.attrs["profile"] = "hzdr"
            handle.attrs["record_type"] = "shots"
            handle.attrs["run_number"] = run_number
            handle.create_dataset(
                "shot_number",
                data=np.asarray([entry.shot_number for entry in run_shots], dtype=np.int64),
            )
            handle.create_dataset(
                "fired_at",
                data=np.asarray([entry.fired_at.encode("utf-8") for entry in run_shots]),
            )
            handle.create_dataset(
                "signal",
                data=np.asarray([entry.signal for entry in run_shots], dtype=np.float64),
            )
            handle.create_dataset(
                "status",
                data=np.asarray([entry.status.encode("utf-8") for entry in run_shots]),
            )
            handle.create_dataset(
                "target",
                data=np.asarray([entry.target.encode("utf-8") for entry in run_shots]),
            )


def _write_mongo_seed(seed_path: Path, shots: list[ShotEntry]) -> None:
    """Write Mongo insertMany payload mirroring the HDF5 shot placeholders."""
    seed_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "database": "shotsheet",
        "collection": "shots",
        "documents": [asdict(shot) for shot in shots],
    }
    seed_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main() -> None:
    """Generate all fixture artifacts under starter-site test_files/."""
    root_dir = Path(__file__).resolve().parent
    shots = _build_shots()
    _write_hdf5_files(root_dir / "hdf5", shots)
    _write_mongo_seed(root_dir / "mongo" / "hzdr_shots.seed.json", shots)
    print(f"Generated {len(shots)} shots across HDF5 and Mongo fixtures in {root_dir}")


if __name__ == "__main__":
    main()
