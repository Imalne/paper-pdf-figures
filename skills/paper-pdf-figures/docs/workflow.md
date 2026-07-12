# Workflow

End-to-end workflow for extracting figures from an academic PDF with the
`paper-pdf-figures` skill. All commands use `python3` (the skill's
`allowed-tools` grants `Bash(python3 *)`).

## 1. Check dependencies

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/check_deps.py
```

- `[OK]` for PyMuPDF / Pillow / PyYAML / numpy / opencv -> all modes work.
- `[WARN]` for torch / doclayout-yolo -> `auto` mode needs the ML backend:
  ```bash
  pip install -r ${CLAUDE_SKILL_DIR}/requirements-ml.txt
  ```
- `[WARN]` for pdftocairo -> SVG export unavailable (PDF+PNG still work).
- Exit code 1 means a required dep is missing; exit 0 means all green.

## 2. Choose a mode

See [extraction-modes.md](extraction-modes.md) for the full comparison. Quick
guide:

- **`auto`** (recommended): model detects figure / table / algorithm regions,
  merges each with its caption, crops vector PDF + PNG. No config needed.
- **`embedded`**: pull the original raster images out of the PDF.
- **`manual`**: crop specific bbox regions you list in a `config.yaml`.
- **`detect`**: heuristic dry-run that outputs candidate bboxes + previews
  (use to find bboxes for `manual`).
- **`render`**: rasterize whole pages or bbox regions to PNG + a contact sheet.

## 3. Run

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/extract_pdf_figures.py PAPER.pdf \
    --out ./out --mode auto --dpi 300 --paper-slug my_paper
```

Common flags:
- `--out DIR` (required) - output directory.
- `--paper-slug NAME` - subdirectory name (defaults to a sanitized PDF stem).
- `--dpi 300` - render resolution (affects PNG size; PDF stays vector).
- `--pages 1,2,5-8` - restrict to specific pages.
- `--overwrite` - replace an existing output directory for this slug.
- `--dry-run` - compute results without writing files (no manifest, no images).

`auto`-specific flags:
- `--min-confidence 0.3` - drop model regions below this confidence.
- `--labels figure,table` - which layout categories to crop (captions auto-inferred as `{primary}_caption`).
- `--caption-driven-fallback` - rescue tables whose body the model missed but
  whose caption was detected (default off).

### Network note for `auto`

`auto` downloads the DocLayout-YOLO model weights from HuggingFace Hub on first
run. If `huggingface.co` is unreachable, set a mirror before running:

```bash
export HF_ENDPOINT=https://hf-mirror.com
```

Weights are cached under `--weights-dir` (default
`${CLAUDE_SKILL_DIR}/models/`, or the `PAPER_PDF_FIGURES_WEIGHTS_DIR` env var).

## 4. Inspect outputs

The output tree (for `auto`):

```
out/<slug>/
├── figures/          # cropped figures (vector PDF + PNG preview each)
│   └── fig_p0011_01/{fig_p0011_01.pdf, fig_p0011_01.png}
├── tables/           # cropped tables (caption merged into bbox)
├── algorithms/       # algorithm pseudocode blocks separated from tables
├── candidates/       # per-page preview PNGs + candidates.json (all regions)
│   ├── page_0011_candidates.png
│   └── candidates.json
└── manifest.json     # single source of truth for all outputs
```

Other modes produce subsets: `embedded/` (embedded), `figures/` (manual),
`candidates/` (detect), `pages/` + `regions/` + `summary_contact_sheet.png`
(render).

## 5. Verify the manifest

```bash
python3 -c "
import sys; sys.path.insert(0, '${CLAUDE_SKILL_DIR}/scripts')
import manifest
m = manifest.Manifest.load('out/<slug>/manifest.json')
print('figures:', len(m.figures), 'tables:', len(m.tables),
      'algorithms:', len(m.algorithms))
print('schema errors:', manifest.validate(m.to_dict()))
"
```

`manifest.json` records every output item with page, bbox (PDF points),
sha256, `extraction_method`, and `caption_source` (for tables/algorithms:
`model` / `text-rescan` / `caption-driven` / `none`).

## 6. Tips

- **Source PDF is never modified** - the skill opens it read-only. Verify with
  `sha256sum PAPER.pdf` before and after.
- **Vector preservation**: cropped PDFs (figures/tables/algorithms) keep vector
  content + searchable text; the PNG is a raster preview only.
- **Caption recovery**: `auto` has three layers - model `table_caption` pairing,
  text-rescan for misclassified captions, and `--caption-driven-fallback` for
  missing table bodies.
- **Reproducibility**: `manifest.json` `run_args` records the exact CLI flags.
