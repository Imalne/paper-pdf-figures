---
name: paper-pdf-figures
description: Extract and save figures from academic PDF papers, including embedded raster images and vector-preserving page crops. Use when the user wants to extract, crop, archive, or batch-save images/figures from research papers.
allowed-tools:
  - Bash(python3 *)
  - Read
  - Write
---

# Paper PDF Figures

Use this skill when the user wants to extract or save figures from academic PDF files.

## Main workflow

1. Identify the input PDF path and output directory.
2. **First-time setup**: check if `${CLAUDE_SKILL_DIR}/scripts/run.sh` exists.
   * **If `run.sh` exists**: read it -- it contains the Python interpreter with all dependencies installed. That interpreter is the single source of truth. Do NOT run `check_deps.py` with a different `python3`.
   * **If `run.sh` does NOT exist** (e.g., installed via `/plugin install` without running the installer): run the installer interactively (do NOT add `--yes` -- the user needs to choose ML deps, Python env, and HF mirror):
     ```bash
     bash ${CLAUDE_SKILL_DIR}/scripts/install.sh
     ```
     The installer will ask: install target (user/project), whether to install ML deps (recommended for `auto` mode), which Python env to install ML deps into (current/conda/venv), and which HuggingFace download endpoint (direct/mirror/custom). After this, `run.sh` exists and all subsequent runs use it.
3. Choose a mode:
   * `auto` - **recommended**. Model-based: detects figure / table / algorithm regions, merges each with its caption, and crops vector PDF + PNG automatically (no config needed). Requires ML deps.
   * `embedded` - extract original embedded raster images (JPEG/PNG/JP2/TIFF). No model needed.
   * `manual` - crop figure regions by bbox from a `--config CONFIG.yaml`. Vector-preserving.
   * `detect` - heuristic candidate detection, dry-run only (writes candidate bboxes + preview PNGs, no crop). No model needed; use to find bboxes for `manual`.
   * `render` - render whole pages (`--pages`) or bbox regions (`--config`) to PNG + a contact sheet.
4. Run (parse the user's request into CLI flags, then execute):
   ```bash
   bash ${CLAUDE_SKILL_DIR}/scripts/run.sh <PDF_PATH> --mode <MODE> --out <OUT_DIR> [FLAGS]
   ```
   Example: `bash ${CLAUDE_SKILL_DIR}/scripts/run.sh paper.pdf --mode auto --out ./figures --dpi 300`
   **If `run.sh` reports a missing dependency, install it into `run.sh`'s interpreter** (shown in `run.sh`'s `exec` line), not the system `python3`.
   Common flags: `--out DIR`, `--paper-slug NAME`, `--dpi 300`, `--pages 1,2,5-8`, `--overwrite`, `--dry-run`.
   `auto` flags: `--min-confidence 0.3`, `--labels figure,table`, `--caption-driven-fallback` (rescue tables the model missed).
   If `huggingface.co` is unreachable, set `HF_ENDPOINT=https://hf-mirror.com` before running `auto`.
   If model weights are already cached but network/proxy is broken, set `HF_HUB_OFFLINE=1`.
5. Report from the printed summary:
   * counts (`embedded_images` / `figures` / `tables` / `algorithms` / `candidates` / `rendered`);
   * output directory and `manifest.json` path;
   * warnings (e.g. `WARN_NO_FIGURES`, `WARN_NO_TABLES`).

## Important rules

* **First check `run.sh`** -- if it doesn't exist, run `install.sh` first (step 2). If it exists, it defines the Python interpreter with installed deps. All dep checks and execution must use that interpreter, not the system `python3`.
* Never modify the original PDF (opened read-only; verified by sha256 in acceptance).
* Do not upload PDFs or images to external services; offline except first-run model weight download.
* Prefer `auto` for figure extraction; fall back to `manual` (with `detect` to find bboxes) when ML deps are unavailable.
* Vector content is preserved in cropped PDFs (figures/tables/algorithms); PNG is a raster preview only.
* `detect` is dry-run by design — it never crops. To crop, use its candidate bboxes in a `manual` config, or use `auto`.

## Additional references

* Detailed workflow: docs/workflow.md
* Extraction modes: docs/extraction-modes.md
* Troubleshooting: docs/troubleshooting.md
