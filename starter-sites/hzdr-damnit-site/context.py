"""Starter DAMNIT context for HZDR LabFrog/ShotSheet data.

This file is intentionally small and editable. Replace `_run_query()` and the
field names with the schema used by your HZDR MongoDB collections.
"""

import numpy as np
import plotly.express as px

from damnit_ctx import (
    Cell,
    Skip,
    Variable,
    load_site_config,
    mongo_find,
    mongo_find_one,
    mongo_json_cell,
    mongo_series_cell,
)


def _run_query(run_number: int) -> dict:
    """Build the MongoDB query for one DAMNIT run."""
    return {"run": run_number}


def reduced_image_cell(full_image, *, stride: int = 16) -> Cell:
    """Store a full image while showing a reduced preview in the table."""
    full_image = np.asarray(full_image)
    return Cell(full_image, summary="mean", preview=full_image[::stride, ::stride])


@Variable(title="LabFrog/Shots")
def labfrog_shot_count(run, run_number: "meta#run_number"):
    """Count LabFrog/ShotSheet documents associated with this run."""
    docs = mongo_find(
        "labfrog",
        query=_run_query(run_number),
        projection={"_id": 0, "shot": 1},
    )
    if not docs:
        raise Skip("No LabFrog entries for this run")
    return len(docs)


@Variable(title="LabFrog/Signal", summary="nanmean")
def labfrog_signal_series(run, run_number: "meta#run_number"):
    """Show a compact trend in the table and full series on double-click."""
    docs = mongo_find(
        "labfrog",
        query=_run_query(run_number),
        projection={"_id": 0, "shot": 1, "signal": 1},
        sort=[("shot", 1)],
    )
    if not docs:
        raise Skip("No signal values in LabFrog for this run")
    return mongo_series_cell(docs, "signal")


@Variable(title="LabFrog/Latest")
def labfrog_latest_record(run, run_number: "meta#run_number"):
    """Store the latest MongoDB record as JSON with a short table summary."""
    doc = mongo_find_one(
        "labfrog",
        query=_run_query(run_number),
        sort=[("timestamp", -1)],
    )
    if doc is None:
        raise Skip("No LabFrog record found")
    return mongo_json_cell(doc, summary_field="status")


@Variable(title="LabFrog/Interactive signal")
def labfrog_interactive_signal(run, run_number: "meta#run_number"):
    """Use a Plotly figure for double-click inspection of shot-level data."""
    docs = mongo_find(
        "labfrog",
        query=_run_query(run_number),
        projection={"_id": 0, "shot": 1, "signal": 1},
        sort=[("shot", 1)],
        limit=2000,
    )
    if not docs:
        raise Skip("No signal values in LabFrog for this run")

    shots = [doc.get("shot") for doc in docs]
    signal = [doc.get("signal") for doc in docs]
    fig = px.line(x=shots, y=signal, labels={"x": "Shot", "y": "Signal"})
    return Cell(np.asarray(signal, dtype=np.float64), summary="nanmean", preview=fig)


@Variable(title="Diagnostics/Detector preview")
def detector_preview(run):
    """Replace this stub with an HZDR detector source and reduced preview."""
    raise Skip("Replace detector_preview with your detector image source")

    # Example once `full_image` is loaded from your data source:
    # return reduced_image_cell(full_image, stride=16)


@Variable(title="Pipeline/Ingest mode")
def planned_ingest_mode(run):
    """Display which planned HZDR ingest modes are enabled in site config."""
    cfg = load_site_config()
    planned = cfg.get("data_sources", {}).get("planned_ingest", {})
    enabled = [name for name, details in planned.items() if details.get("enabled")]
    if not enabled:
        return "manual/context-only"
    return ", ".join(sorted(enabled))
