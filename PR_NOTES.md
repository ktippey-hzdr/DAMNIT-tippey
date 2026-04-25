# PR Notes

## Summary

This PR prepares DAMNIT for an HZDR-style deployment where users open DAMNIT folders directly instead of proposal numbers. It also adds the dependency/config scaffolding needed for a Windows HZDR developer workflow with Kafka and MongoDB access.

## Reviewer-Facing Changes

- **Non-proposal GUI flow**
  - `OpenDBDialog` hides proposal controls when `lab.proposal_required` is false.
  - The default HZDR wording guides users to an existing `HZDR DAMNIT folder`.
  - `NewContextFileDialog` hides proposal-copy controls for non-proposal sites and shows short guidance for context templates.

- **HZDR site configuration**
  - Adds repo-root `damnit-site.json` and `.damnit.env.example` for HZDR defaults.
  - Adds `starter-sites/hzdr-damnit-site/` as a folder-based starter site with:
    - `damnit-site.json`
    - `.damnit.env.example`
    - editable `context.py`
    - short `README.md`
  - HZDR LabFrog/ShotSheet MongoDB defaults use `database: shotsheet` and `collection: shots`.

- **Context authoring support**
  - Adds HZDR context examples for LabFrog/ShotSheet MongoDB values, Plotly previews, and reduced-resolution table thumbnails with full details on double-click.
  - Runtime Python placeholders such as `$DAMNIT_CONTEXT_PYTHON` fall back to the active interpreter when unset.

- **Dependency and Windows startup cleanup**
  - `requires-python` is now `>=3.11` to match the dependency floor.
  - GUI extras include Kafka, Windows-compatible Qt runtime pins, and `QScintilla==2.14.1`.
  - `pymongo` is included for MongoDB context helpers.
  - Unix-only permission handling is guarded on Windows.
  - XFEL-only `extra_data` / `extra_proposal` imports are lazy so HZDR GUI startup is not blocked by their Unix-specific import chain.

## How To Try It

```powershell
uv sync --extra test --extra gui --extra backend
damnit gui starter-sites\hzdr-damnit-site
```

Edit `.damnit.env` locally for real HZDR Kafka/MongoDB endpoints. `.damnit.env` remains ignored; `.damnit.env.example` is the tracked reference.

## Validation

- `uv sync --extra test --extra gui --extra backend`
- `uv run --no-sync --extra test --extra gui --extra backend pytest -q -s tests/test_gui.py -k "open_dialog or new_context_dialog"`
  - `6 passed, 32 deselected`
- `uv run --no-sync --extra test --extra gui --extra backend pytest -q -s tests/test_site_config.py`
  - `6 passed`
- Smoke checks:
  - GUI imports on Windows.
  - `DamnitDB.from_dir()` initializes on Windows.
  - HZDR open dialog hides proposal controls from repo/starter config.
  - Root and starter site configs expand Kafka/MongoDB values from `.damnit.env`.

## Caveats

- Running `damnit gui` from an arbitrary directory still requires a nearby `damnit-site.json` or `DAMNIT_SITE_CONFIG` pointing to one.
- `.damnit.env` is local-only and may contain secrets; do not commit it.
- Detailed work log and intermediate validation history are in `STATUS_NOTES.md`.

## Suggested Commit Split

- `build(pyproject): make gui extra install Windows Qt and Kafka dependencies`
- `fix(backend): guard Unix-only permission handling on Windows`
- `fix(ctxrunner): lazy-load XFEL-only context dependencies`
- `feat(gui): support HZDR folder-based startup`
- `feat(config): add HZDR site defaults and starter site`
