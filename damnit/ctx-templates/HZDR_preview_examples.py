"""HZDR context examples for thumbnails with full-detail previews.

DAMNIT stores the value returned by each Variable, while table cells show a
small summary or thumbnail. Returning Cell(..., preview=...) lets the table stay
compact and still open fuller details when users double-click the cell.
"""

import numpy as np
import plotly.express as px

from damnit_ctx import Cell, Skip, Variable, mongo_find, mongo_series_cell


def _run_query(run_number: int) -> dict:
    """Return the LabFrog/ShotSheet query for a DAMNIT run number."""
    return {"run": run_number}


def reduced_image_cell(full_image, *, stride: int = 16) -> Cell:
    """Store a full image while showing a reduced thumbnail in the table."""
    full_image = np.asarray(full_image)
    preview_image = full_image[::stride, ::stride]
    return Cell(full_image, summary="mean", preview=preview_image)


@Variable(title="Diagnostics/Shot trend")
def shot_trend(run, run_number: "meta#run_number"):
    """Show a downsampled trend in the table and full series on double-click."""
    docs = mongo_find(
        "labfrog",
        query=_run_query(run_number),
        projection={"_id": 0, "shot": 1, "signal": 1},
        sort=[("shot", 1)],
    )
    if not docs:
        raise Skip("No LabFrog signal values for this run")
    return mongo_series_cell(docs, "signal")


@Variable(title="Diagnostics/Detector preview")
def detector_preview(run):
    """Connect real detector data, then return a compact table thumbnail."""
    raise Skip("Replace detector_preview with your HZDR detector image source")

    # Example once `full_image` is loaded from your data source:
    # return reduced_image_cell(full_image, stride=16)


@Variable(title="Diagnostics/Interactive plot")
def interactive_plot(run, run_number: "meta#run_number"):
    """Use a Plotly figure as the double-click preview for richer inspection."""
    docs = mongo_find(
        "labfrog",
        query=_run_query(run_number),
        projection={"_id": 0, "shot": 1, "signal": 1},
        sort=[("shot", 1)],
        limit=2000,
    )
    if not docs:
        raise Skip("No LabFrog signal values for this run")

    shots = [doc.get("shot") for doc in docs]
    signal = [doc.get("signal") for doc in docs]
    fig = px.line(x=shots, y=signal, labels={"x": "Shot", "y": "Signal"})
    return Cell(np.asarray(signal, dtype=np.float64), summary="nanmean", preview=fig)
