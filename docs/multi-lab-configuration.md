# Multi-Lab Configuration (XFEL, HZDR, and beyond)

DAMNIT now supports a site configuration file so deployments can move away from
hardcoded XFEL assumptions.

## Quick start for HZDR

From your DAMNIT database directory (or deployment root):

```bash
damnit site-config init --profile hzdr
```

This creates:

- `damnit-site.json` (editable non-secret config)
- `.damnit.env.example` (secret/env template)

Copy `.damnit.env.example` to `.damnit.env` and fill values.

## Main settings to adjust

`damnit-site.json` keys:

- `auth.provider`: `ldap`, `helmholtz`, `xfel`, or `none`
- `lab.proposal_required`: set `false` to allow DB setup without fixed proposal
- `kafka.listener_profiles`: broker/topics/events for listener triggers
- `kafka.update_brokers`: brokers for GUI/backend update messages
- `data_sources.mongodb`: named MongoDB sources (e.g. LabFrog/ShotSheet)
- `data_sources.planned_ingest`: placeholders for HDF5/Kafka/BigData ingest modes

## Proposal-optional setup

If `lab.proposal_required=false`, GUI/CLI DB setup no longer forces proposal
entry at creation time. You can still set it later:

```bash
damnit proposal 1234
```

## MongoDB from context files

`damnit_ctx` now includes helpers:

- `load_site_config()`
- `mongo_find()`
- `mongo_find_one()`
- `mongo_series_cell()`
- `mongo_json_cell()`

Example:

```python
from damnit_ctx import Variable, mongo_find, mongo_series_cell

@Variable(title="LabFrog/Signal", summary="nanmean")
def labfrog_signal(run, run_number: "meta#run_number"):
    docs = mongo_find(
        "labfrog",
        query={"run": run_number},
        projection={"_id": 0, "signal": 1},
        sort=[("shot", 1)],
    )
    return mongo_series_cell(docs, "signal")
```

This stores full 1D data and keeps a reduced table summary, while still
allowing detailed inspection on double-click.

See starter template: `damnit/ctx-templates/HZDR_labfrog.py`

## Synthetic test data

To validate setup quickly without live instruments:

```bash
damnit sample-data --runs 10 --start-run 1
```

This writes synthetic run fragments and ingests them into the DB/HDF5 store.

## Extension points for planned ingest modes

Current config includes placeholders for not-yet-implemented collection paths:

- `data_sources.planned_ingest.hdf5`
- `data_sources.planned_ingest.kafka`
- `data_sources.planned_ingest.bigdata`

Recommended code locations:

- Site config schema/loading: `damnit/site_config.py`
- Event-triggered backend ingestion: `damnit/backend/listener.py`
- Context-level data adapters: `damnit/ctxsupport/damnit_ctx.py`
- Optional web-auth integration hook (if using DAMNIT-web): consume
  `auth.*` settings there
