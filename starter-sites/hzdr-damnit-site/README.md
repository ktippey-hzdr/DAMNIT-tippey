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
