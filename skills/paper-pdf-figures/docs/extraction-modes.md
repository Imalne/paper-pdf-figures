# Extraction Modes

The skill has five modes, selected with `--mode`. All open the source PDF
read-only and write outputs under `--out/<paper-slug>/`.

## Comparison

| Mode | What it does | Needs model? | Outputs | Typical use |
| --- | --- | --- | --- | --- |
| `auto` | Model detects figure / table / algorithm regions, merges captions, crops vector PDF + PNG | yes (ML deps) | `figures/`, `tables/`, `algorithms/`, `candidates/`, `manifest.json` | Default figure extraction |
| `embedded` | Pull original embedded raster images (image XObjects) | no | `embedded/`, `manifest.json` | Get raw photos / rasterized plots out of the PDF |
| `manual` | Crop figure regions by bbox from a `config.yaml` | no | `figures/`, `manifest.json` | Precise control when you know the bboxes |
| `detect` | Heuristic candidate detection, dry-run | no | `candidates/`, `manifest.json` | Find candidate bboxes to feed into `manual` |
| `render` | Rasterize whole pages or bbox regions to PNG + contact sheet | no | `pages/` or `regions/`, `summary_contact_sheet.png`, `manifest.json` | Page thumbnails / region screenshots |

## `auto` (recommended)

Model-based. Uses DocLayout-YOLO to detect layout regions, then:

1. For each page: detect regions (`figure`, `figure_caption`, `table`,
   `table_caption`, `plain text`, `title`, `isolate_formula`, ...).
2. **Pair + merge**: each `figure` pairs with its nearest `figure_caption`
   (vertical distance); each `table` with its nearest `table_caption`. The
   caption bbox is unioned into the primary's bbox so the crop includes the
   caption text.
3. **Caption recovery** (three layers):
   - `model` - the model detected a `*_caption` region and it paired.
   - `text-rescan` - no caption paired, but a `plain text`/`title` region
     starting with `Table N:` was found and merged.
   - `caption-driven` (with `--caption-driven-fallback`) - the model detected
     a caption but missed the table body; the body is inferred from adjacent
     text blocks.
4. **Algorithm separation**: each cropped table's text is classified; if it
   looks like pseudocode (`Algorithm N`, `Input:`+`Output:`, `Require:`, or
   line-anchored `for`/`while`/`return`), it moves to `algorithms/` with
   `type="page-crop-algorithm"` and id prefix `alg_`.
5. Crop via `crop_figures` (vector-preserving PDF + PNG).

`caption_source` on every table/algorithm records which layer produced the
caption.

### `auto` flags

- `--min-confidence 0.3` - drop regions below this confidence (lower e.g. 0.2
  to recover borderline tables).
- `--labels figure,table` - which primaries to crop. Caption labels are
  auto-inferred as `{primary}_caption`. Caption labels passed directly
  (`figure_caption`) are ignored.
- `--caption-driven-fallback` - enable the caption-driven rescue (default off).
- `--device auto|cpu|cuda` - inference device.
- `--weights-dir PATH` - model weight cache (default `<skill>/models/`).

## `embedded`

Extracts image XObjects via PyMuPDF `page.get_images()` + `doc.extract_image()`.

- Dedups by xref (same image on multiple pages -> one file, recorded under the
  first page).
- `sha256` is of the extracted (possibly re-encoded) bytes, not the original
  embedded stream.
- Vector-only PDFs (e.g. matplotlib exports as Form XObjects) yield 0 images -
  use `auto` or `manual` for those.

```bash
python3 .../extract_pdf_figures.py paper.pdf --mode embedded --out ./out
```

## `manual`

Crops bbox regions listed in a `config.yaml` into vector PDF + PNG. The crop
uses `page.show_pdf_page(clip=bbox)`, which embeds the region as a Form XObject
- **vector content and text are preserved** (zoomable, searchable).

`config.yaml` format (see `templates/config.example.yaml`):

```yaml
pdf: paper.pdf
figures:
  - id: fig_001
    page: 3
    bbox: [72, 110, 540, 410]   # [x0, y0, x1, y1] in PDF points
    caption: "Figure 1: Overview."
    export: [pdf, png]          # optional; default both
```

```bash
python3 .../extract_pdf_figures.py paper.pdf --mode manual --config config.yaml --out ./out --dpi 300
```

## `detect`

Heuristic dry-run. Per page: low-DPI render -> Otsu threshold -> morphological
close -> connected components -> filter by area ratio / aspect / margins ->
merge nearby. Writes candidate bboxes + preview PNGs but **never crops**.

Use it to find bboxes for `manual`: read `candidates.json`, pick a bbox, copy
it into a `config.yaml`.

```bash
python3 .../extract_pdf_figures.py paper.pdf --mode detect --out ./out --min-area-ratio 0.03
```

Flags: `--min-area-ratio`, `--max-area-ratio`, `--merge-distance`,
`--exclude-margins`, `--two-column` (accepted, not yet wired into the
algorithm). `--two-column` is stored in `run_args` for forward-compat.

## `render`

Rasterizes pages to PNG (no vector output). Two behaviors:

- **No `--config`**: render whole pages -> `pages/p{page:04d}.png` (filter with
  `--pages`).
- **With `--config`**: render each config figure's bbox region ->
  `regions/{id}.png` (same config format as `manual`, but raster output).

Always produces a `summary_contact_sheet.png` (4-column grid of thumbnails).

```bash
# whole pages
python3 .../extract_pdf_figures.py paper.pdf --mode render --out ./out --pages 1,11 --dpi 150
# regions
python3 .../extract_pdf_figures.py paper.pdf --mode render --config config.yaml --out ./out
```

## Manifest

Every mode writes `manifest.json` (the single source of truth). Arrays:

- `figures[]` - cropped figures (`manual`/`auto`).
- `tables[]` - cropped tables (`auto`).
- `algorithms[]` - separated algorithm blocks (`auto`).
- `embedded_images[]` - extracted raster images (`embedded`).
- `candidates[]` - detected regions with `label`/`confidence` (`auto`/`detect`).
- `rendered[]` - rendered pages/regions (`render`).
- `warnings[]` - `WARN_NO_FIGURES`, `WARN_NO_TABLES`, `WARN_NO_EMBEDDED_IMAGES`,
  `WARN_NO_RENDERED`, `WARN_SVG_EXPORT_FAILED`, etc.

`run_args` records the exact CLI flags for reproducibility.
