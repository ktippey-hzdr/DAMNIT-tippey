"""Starter context template for HZDR + LabFrog/ShotSheet integrations.

This intentionally keeps assumptions light. Adjust the queries and field names
to match your MongoDB schema.
"""

from damnit_ctx import (
    Skip,
    Variable,
    load_site_config,
    mongo_find,
    mongo_find_one,
    mongo_json_cell,
    mongo_series_cell,
)


def _run_query(run_number: int) -> dict:
    # Adjust this to your actual schema in LabFrog/ShotSheet.
    return {"run": run_number}


@Variable(title="LabFrog/Shots")
def labfrog_shot_count(run, run_number: "meta#run_number"):
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
    docs = mongo_find(
        "labfrog",
        query=_run_query(run_number),
        projection={"_id": 0, "signal": 1},
        sort=[("shot", 1)],
    )
    if not docs:
        raise Skip("No signal values in LabFrog for this run")
    return mongo_series_cell(docs, "signal")


@Variable(title="LabFrog/Latest")
def labfrog_latest_record(run, run_number: "meta#run_number"):
    doc = mongo_find_one(
        "labfrog",
        query=_run_query(run_number),
        sort=[("timestamp", -1)],
    )
    if doc is None:
        raise Skip("No LabFrog record found")
    return mongo_json_cell(doc, summary_field="status")


@Variable(title="Pipeline/Ingest mode")
def planned_ingest_mode(run):
    cfg = load_site_config()
    planned = cfg.get("data_sources", {}).get("planned_ingest", {})

    enabled = [name for name, details in planned.items() if details.get("enabled")]
    if not enabled:
        return "manual/context-only"
    return ", ".join(sorted(enabled))
