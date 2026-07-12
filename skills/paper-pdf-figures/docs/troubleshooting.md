# Troubleshooting

Common issues and fixes for the `paper-pdf-figures` skill.

## `auto` mode: "ERROR: --mode auto requires ML backend"

The ML dependencies (torch, doclayout-yolo, huggingface_hub) are not installed.

```bash
pip install -r ${CLAUDE_SKILL_DIR}/requirements-ml.txt
```

Verify with `python3 scripts/check_deps.py` - it should report `[OK] torch` and
`[OK] doclayout-yolo`. Without ML deps, use `manual` (with `detect` to find
bboxes) instead.

## `auto` mode: model weight download hangs / fails

`auto` downloads DocLayout-YOLO weights from HuggingFace Hub on first run. If
`huggingface.co` is unreachable (common in some WSL2 / firewall setups):

```bash
export HF_ENDPOINT=https://hf-mirror.com
```

Then re-run `auto`. The weights cache under `<skill>/models/huggingface/` (or
`--weights-dir` / `PAPER_PDF_FIGURES_WEIGHTS_DIR`) and subsequent runs are
fast.

If the mirror is also unreachable, download the weight file manually from
`huggingface.co/juliozhao/DocLayout-YOLO-DocStructBench` (filename
`doclayout_yolo_docstructbench_imgsz1024.pt`) and place it under the
`--weights-dir/huggingface/...` cache path.

## `auto` mode: 0 figures / tables detected

- Lower `--min-confidence` (default 0.3) to e.g. 0.2 to keep borderline regions.
- Add `--caption-driven-fallback` to rescue tables whose caption was detected
  but whose body the model missed.
- Inspect `candidates/page_NNNN_candidates.png` - the red boxes show what the
  model detected. If there are no `figure`/`table` boxes, the model may not
  recognize the layout; fall back to `detect` (heuristic) + `manual`.
- Check `warnings` in the summary: `WARN_NO_FIGURES` / `WARN_NO_TABLES` are
  expected when the PDF genuinely has none.

## `embedded` mode: 0 images extracted

The PDF may be **vector-only** (figures drawn as PDF vector ops, not image
XObjects). This is common for matplotlib/TikZ exports. `page.get_images()`
returns 0.

- Use `auto` (model detects figure regions) or `manual` (crop by bbox) instead.
- Confirm with: `python3 -c "import fitz; d=fitz.open('paper.pdf'); print(sum(len(d[p].get_images()) for p in range(len(d))))"`.

## Table caption missing from a crop

`auto` records `caption_source` per table in the manifest:

- `model` - the model paired a `table_caption` (best case).
- `text-rescan` - caption was misclassified as `plain text` and recovered.
- `caption-driven` - body inferred from adjacent text (with
  `--caption-driven-fallback`).
- `none` - no caption found. The crop is still the table body; the caption is
  just absent.

To improve caption coverage, add `--caption-driven-fallback`.

## A table was misclassified as an `algorithm`

The `classify_table_or_algorithm` heuristic checks the cropped text. If a
table's caption or body contains words like "for"/"while" in English prose, it
may have been misclassified. The rules were tightened (line-anchored keywords,
table-caption priority), so this is rare now. If it happens:

- Check the crop's text in `algorithms/<id>/<id>.pdf` - if it's a table, the
  classification was wrong.
- This is a heuristic limitation; the crop is still valid, just in the wrong
  directory. Move it manually or re-run without algorithm separation.

## `--overwrite` guard: "manifest.json already exists"

Re-running into an existing `<out>/<slug>/manifest.json` without `--overwrite`
exits 1 (protects prior output). Add `--overwrite` to replace the whole
`<out>/<slug>/` directory:

```bash
python3 .../extract_pdf_figures.py paper.pdf --mode auto --out ./out --overwrite
```

## `parse_pages` errors on `--pages`

`--pages` accepts `1,2,5-8` (comma-separated pages and ranges, 1-based).
Malformed input (`abc`, `1-2-3`, `-1`, `5-2`) raises a clean `ERROR:` and
exit 1. Fix the spec.

## Source PDF sha256 changed

It should not - the skill opens PDFs read-only via `fitz.open()`. If you
observe a change, check that nothing else wrote to the PDF. The acceptance
script (`paper-pdf-figure/scripts/accept_all_modes.sh`) verifies sha256
before/after for every mode.

## `check_deps.py` exit code

- `0` - all required deps present (all modes available).
- `1` - a required dep is missing (some modes unavailable). The report shows
  `[MISSING]` for required, `[WARN]` for optional (pdftocairo/pdfimages/mutool
  /torch/doclayout-yolo).

## Out of memory / slow on large PDFs

- `auto` runs the model per page at dpi=150 (detection). A 72-page paper takes
  ~10s on GPU, longer on CPU. Use `--pages` to limit scope, or `--device cuda`
  if a GPU is available.
- `render` at high `--dpi` (e.g. 600) produces large PNGs; use 150-300 unless
  you need print resolution.
- `--dry-run` skips all writes (useful to preview counts cheaply).

## Tests fail

```bash
cd ${CLAUDE_SKILL_DIR} && pytest tests/ -v
```

The real-model smoke test (`test_real_doclayout_detector_smoke`) needs ML deps
+ network; it's deselected by default (`-k "not real_doclayout"`). To run it:

```bash
export HF_ENDPOINT=https://hf-mirror.com
pytest tests/test_model_detect.py::test_real_doclayout_detector_smoke -v
```
