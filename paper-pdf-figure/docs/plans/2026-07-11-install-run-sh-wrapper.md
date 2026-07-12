# Install Script Fix: run.sh wrapper for Python env coherence

## Goal
When the user installs with a specific Python env (e.g., conda env "myenv"), generate a `scripts/run.sh` wrapper so the skill always runs with that Python -- regardless of which `python3` the calling shell finds.

## Design
1. **install.py**: after extracting the .skill package, always generate `scripts/run.sh` in the installed skill dir. Content: `exec <runtime_python> "$SCRIPT_DIR/extract_pdf_figures.py" "$@"`. `runtime_python` = ML env if chosen and different, else `sys.executable` (absolute path).
2. **install.py**: patch the extracted `SKILL.md` to replace `python3 ${CLAUDE_SKILL_DIR}/scripts/extract_pdf_figures.py` with `bash ${CLAUDE_SKILL_DIR}/scripts/run.sh` (and `check_deps.py` call similarly -> `bash ${CLAUDE_SKILL_DIR}/scripts/run.sh --check-deps` or a separate `check_deps.sh`). Simpler: only change the `extract_pdf_figures.py` call; `check_deps.py` already runs from verify() with the right python.
3. **tests**: verify run.sh generated + executable + points to correct python; SKILL.md patched.

## Task 1: generate run.sh + patch SKILL.md in install.py

**Files:**
- Modify: `scripts/install.py`
- Modify: `tests/test_install.py`

### Steps:
1. Write tests: `test_generates_run_sh` (run.sh exists, contains the right python, is executable) + `test_skill_md_uses_run_sh` (SKILL.md references `run.sh` not `python3 ... extract_pdf_figures.py`).
2. Run -> FAIL.
3. In `install.py` `main()`, after `extract_package`, add `generate_run_sh(skill_dir, runtime_python)` + `patch_skill_md(skill_dir)`.
   - `generate_run_sh(skill_dir, python)`: writes `scripts/run.sh` with `#!/usr/bin/env bash\nSCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"\nexec {python} "$SCRIPT_DIR/extract_pdf_figures.py" "$@"\n`. chmod +x.
   - `patch_skill_md(skill_dir)`: reads SKILL.md, replaces `python3 ${CLAUDE_SKILL_DIR}/scripts/extract_pdf_figures.py "$ARGUMENTS"` with `bash ${CLAUDE_SKILL_DIR}/scripts/run.sh "$ARGUMENTS"`. Also replaces `python3 ${CLAUDE_SKILL_DIR}/scripts/check_deps.py` with `bash ${CLAUDE_SKILL_DIR}/scripts/check_deps.sh` and generates `check_deps.sh` too (same pattern). Or simpler: just replace extract_pdf_figures.py call; check_deps.py is only called from SKILL.md workflow step 2, and verify() already uses the right python.
4. Run tests -> PASS.
5. Commit.

## Constraints
- `runtime_python` is always absolute (`Path(...).resolve()`).
- If no ML env chosen, `runtime_python = sys.executable` (absolute) -> run.sh uses that.
- SKILL.md patch is idempotent (if already patched, no-op).
- run.sh + check_deps.sh are generated post-extract, not packaged in .skill (they're install-specific).
