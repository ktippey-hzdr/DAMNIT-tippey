# HZDR DAMNIT starter site

This folder is a minimal HZDR-style DAMNIT database directory. It uses folder-based startup, not proposal numbers.

## First use

1. Edit `.damnit.env` and fill in the HZDR Kafka and MongoDB values. `.damnit.env.example` is the tracked reference copy.
2. Start the GUI from this folder or open this folder from the GUI:

```powershell
damnit gui .
```

DAMNIT will create `runs.sqlite` here on first open and use the existing `context.py`.

## Files

- `damnit-site.json`: HZDR site profile with `proposal_required` disabled.
- `.damnit.env.example`: local environment variables for Kafka, MongoDB, and optional auth.
- `context.py`: starter context file with LabFrog/ShotSheet MongoDB and preview examples.

Keep `.damnit.env` private. It may contain database credentials.

## Minimal test fixtures

This starter site includes tiny HZDR-style placeholder data in `test_files/`:

- `test_files/hdf5/hzdr_run_1.h5`
- `test_files/hdf5/hzdr_run_2.h5`
- `test_files/hdf5/hzdr_run_3.h5`
- `test_files/mongo/hzdr_shots.seed.json`

Each run has 3 shots with `shot_number`, `fired_at`, `signal`, `status`, and `target`.

Regenerate fixtures:

```powershell
uv run python test_files/generate_test_files.py
```

Seed MongoDB (example using `mongosh`):

```powershell
$seed = Get-Content .\test_files\mongo\hzdr_shots.seed.json | ConvertFrom-Json
mongosh "mongodb://localhost:27017" --eval "db = db.getSiblingDB('$($seed.database)'); db.getCollection('$($seed.collection)').deleteMany({}); db.getCollection('$($seed.collection)').insertMany($($seed.documents | ConvertTo-Json -Compress));"
```
