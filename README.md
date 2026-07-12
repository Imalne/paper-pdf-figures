# Paper PDF Figures

Extract figures, tables, and algorithms from academic PDF papers. Five modes: auto (DocLayout-YOLO model), embedded, manual, detect, render. Offline; preserves vectors.

## Install

### Option A: Claude Code Plugin (recommended)

```bash
# In Claude Code:
/plugin marketplace add https://github.com/Imalne/paper-pdf-figures
/plugin install paper-pdf-figures
```

### Option B: .skill package

Download `dist/paper-pdf-figures-0.1.0.skill`, then:

```bash
unzip paper-pdf-figures-0.1.0.skill -d ~/.claude/skills/
cd ~/.claude/skills/paper-pdf-figures
bash scripts/install.sh
```

Or non-interactive:

```bash
bash scripts/install.sh --yes --target ~/.claude/skills --no-ml
```

## Modes

| Mode | Description | ML deps? |
| --- | --- | --- |
| `auto` | Model-based: detects figure/table/algorithm, merges captions, crops vector PDF+PNG | Yes |
| `embedded` | Extract embedded raster images (JPEG/PNG/JP2/TIFF) | No |
| `manual` | Crop figure regions by bbox from config.yaml | No |
| `detect` | Heuristic candidate detection (dry-run) | No |
| `render` | Render pages/regions to PNG + contact sheet | No |

## Usage

```bash
bash scripts/run.sh paper.pdf --mode auto --out ./figures --dpi 300
```

See [skills/paper-pdf-figures/SKILL.md](skills/paper-pdf-figures/SKILL.md) for full workflow.

## License

MIT
