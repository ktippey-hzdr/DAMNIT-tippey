"""Utilities to generate synthetic data for quick DAMNIT smoke tests."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .backend.combine import gather_all_fragments
from .backend.db import DamnitDB
from .context import Cell, save_fragment


def generate_sample_data(
    db_dir: Path | str,
    *,
    runs: int = 5,
    start_run: int = 1,
    proposal: int | None = None,
    seed: int = 7,
) -> tuple[int, list[int]]:
    """Generate synthetic run fragments and ingest them into the database.

    Returns:
        tuple[int, list[int]]: resolved proposal number and generated run numbers
    """
    db_path = Path(db_dir).absolute()
    if runs < 1:
        raise ValueError("runs must be >= 1")

    with DamnitDB.from_dir(db_path) as db:
        resolved_proposal = proposal if proposal is not None else db.metameta.get("proposal")

    if resolved_proposal is None:
        raise ValueError(
            "No proposal configured for this database. Pass --proposal or set "
            "one with `damnit proposal <number>`."
        )

    rng = np.random.default_rng(seed)
    generated_runs = []

    for offset in range(runs):
        run_no = start_run + offset
        generated_runs.append(run_no)

        trend = np.clip(rng.normal(loc=100 + (offset * 2), scale=5, size=800), 0, None)
        image = rng.normal(loc=0.0, scale=1.0, size=(64, 64))
        status = "OK" if float(np.nanmean(trend)) >= 100 else "CHECK"

        cells = {
            "sample.trend": Cell(trend, summary="nanmean"),
            "sample.image": Cell(image),
            "sample.peak": Cell(float(np.nanmax(trend))),
            "sample.status": Cell(status),
            "sample.note": Cell(f"Synthetic dataset for run {run_no}"),
        }

        save_fragment(
            db_path,
            resolved_proposal,
            run_no,
            cells,
            errors={},
            provenance="sample-data",
        )

    gather_all_fragments(db_path)
    return resolved_proposal, generated_runs
