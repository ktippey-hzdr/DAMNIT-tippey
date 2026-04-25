# PR Notes

## Scope
Enable and harden the HZDR non-proposal GUI workflow, while aligning site config defaults and dependency metadata.

## Proposed Changes
1. **Python compatibility floor** (`pyproject.toml`)
   - Set `requires-python` to `>=3.11`.
   - Reason: dependency resolution was unsatisfiable with `>=3.10` because `fpcs==1.0.0` requires Python 3.11+.

2. **Non-proposal dialog behavior** (`damnit/gui/open_dialog.py`, `damnit/gui/new_context_dialog.py`, `tests/test_gui.py`)
   - Hide proposal-centric controls when `proposal_required` is `false`.
   - Default to folder mode and adapt label with lab name (for example: `Open HZDR DAMNIT folder:`).
   - Reason: remove proposal prompts for HZDR-style deployments.

3. **Open-dialog config fallback fix** (`damnit/gui/open_dialog.py`, `tests/test_gui.py`)
   - Resolve site config from `cwd` first, then fall back to `Path.home()`.
   - Reason: users launching `damnit gui` outside a configured directory should still get the correct non-proposal behavior.

4. **HZDR template MongoDB correction** (`damnit/site_config.py`, `tests/test_site_config.py`)
   - Corrected LabFrog defaults to:
     - `database: shotsheet`
     - `collection: shots`
   - Reason: previous values were swapped.

5. **Ignore local-only artifacts** (`.gitignore`)
   - Keep `.damnit.env` and `STATUS_NOTES.md` ignored.
   - Reason: avoid committing local secrets and local implementation notes.

## Validation
- `uv run --extra test --extra gui --extra backend pytest -q -s tests/test_gui.py -k 'open_dialog or non_proposal'`
  - Result: `4 passed, 32 deselected`
- `uv run --extra test --extra backend pytest -q -s tests/test_site_config.py`
  - Result: `4 passed`
- `uv run --extra test --extra gui --extra backend pytest -q`
  - Result: `107 passed, 19 failed, 1 error, 1 skipped`
  - Main failures were environment/runtime-related in this workspace (`dbm.gnu` module mismatch for GUI settings shelf, plus one timeout-sensitive GUI hover test).

## Commit Map (Current)
- `832b221` build(pyproject): require Python 3.11+ to match dependency floor
- `556e2de` feat(gui): hide proposal-based controls for non-proposal site profiles
- `aa50129` fix(site-config): correct HZDR LabFrog MongoDB database/collection defaults
- `9e7f091` chore(gitignore): ignore local env and implementation notes
- `17af3ba` fix(gui): resolve open dialog site profile from home fallback
