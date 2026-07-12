# paper-pdf-figures

A Claude Code skill that extracts and saves figures from academic PDF papers: embedded raster images, vector-preserving page crops, model-based figure/table/algorithm detection, and high-DPI PNG renders. Offline; never modifies the source PDF.

## Install

### From the .skill package (one-click)

```bash
# interactive (asks: install target, ML deps, Python env, HF mirror)
bash scripts/install.sh

# or non-interactive
bash scripts/install.sh --yes --target ~/.claude/skills --no-ml
```

The installer automatically:
- Extracts the skill to the chosen target (`~/.claude/skills/` or project `.claude/skills/`).
- Installs Python deps (basic + optional ML) into the chosen Python env (current / conda / venv).
- Generates `scripts/run.sh` so the skill always runs with the correct Python (Claude Code calls `run.sh`, not bare `python3`).
- If ML is enabled and `huggingface.co` is unreachable, the installer asks which mirror to use and writes it into `run.sh`. At runtime, `auto` mode auto-falls-back between endpoints on failure.

Flags: `--yes` (non-interactive), `--package PATH`, `--target PATH`, `--ml`/`--no-ml`, `--ml-env PYTHON`, `--dry-run`.

### Manual

```bash
pip install -r requirements.txt           # required (all modes)
pip install -r requirements-ml.txt        # optional (auto mode)
bash scripts/install_deps.sh              # system deps (poppler)
python3 scripts/check_deps.py            # verify
```

Then place this directory under `.claude/skills/` (project) or `~/.claude/skills/` (user).

## Modes

| Mode | What it does |
| --- | --- |
| `auto` | **Recommended.** Model-based (DocLayout-YOLO): detects figure / table / algorithm regions, merges captions, crops vector PDF + PNG. Requires ML deps. |
| `embedded` | Extract embedded raster images (JPEG/PNG/JP2/TIFF). |
| `manual` | Crop figure regions from a `config.yaml` of bbox values. |
| `detect` | Dry-run: heuristic candidate figure bboxes + preview images (no model needed). |
| `render` | Render full pages (`--pages`) or bbox regions (`--config`) to PNG + a contact sheet. |

## Security

No network, no uploads, no unrequested deletes. Output is confined to the user-specified directory. External commands are called with argument lists (no shell). See the design doc at `paper-pdf-figure/docs/designs/paper-pdf-figure.md`.
