# Paper PDF Figures — Phase 2 (Manual bbox Crop) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `--mode manual`: crop figure regions from a PDF by bbox values read from a `config.yaml`, exporting each as a **vector-preserving PDF** plus a high-DPI PNG preview, recorded in `manifest.json` as `Figure` entries.

**Architecture:** `crop_export.py` holds the crop logic: for each figure in the config, create a new 1-page PDF whose single page is `doc.new_page(bbox_size)` then `page.show_pdf_page(rect, src_doc, pno, clip=bbox)` — this embeds the cropped region as a Form XObject, **preserving vector content and text**. Render PNG from that page at `--dpi`. `extract_pdf_figures.py` (Phase 1 dispatcher) gains a `manual` branch that reads `--config`, calls `crop_figures`, and adds `Figure` records to the manifest. SVG is Phase 3; `--formats` accepts `pdf,png` for now.

**Tech Stack:** Python ≥3.9, PyMuPDF (`fitz`) — `show_pdf_page` for vector crop, `get_pixmap(dpi=)` for PNG; PyYAML for config; pytest + jsonschema (installed). API verified on the real vector paper `2606.28301v1.pdf`: a crop of page 11 preserved 650 vector drawings + axis-label text.

## Global Constraints

(From the spec `paper-pdf-figure/docs/designs/paper-pdf-figure.md` — every task inherits these.)

- Skill root: `.claude/skills/paper-pdf-figures/`; tests run from there: `cd .claude/skills/paper-pdf-figures && pytest tests/ -v`
- Never modify the original PDF (open read-only; verify byte-identical after crop).
- Reuse Phase 0/1 modules: `manifest.py` (`Manifest`, `Figure`, `validate`), `extract_embedded.py` (unchanged). Do not duplicate.
- `Figure` fields (from `manifest.py`): `id, page, bbox_pdf_points, type, extraction_method, dpi, files{pdf,png,svg}, sha256{pdf,png,svg}, caption`. `page` is 1-based; `bbox_pdf_points` is `[x0,y0,x1,y1]` in PDF points; `dpi` is an int ≥1.
- File naming (spec §9.3): `figures/{figure_id}/{figure_id}.pdf` and `.png` (the config `id` is used as the directory and filename; SVG deferred to Phase 3).
- `type` for manual crops: the string `"page-crop"` (content-agnostic; the schema accepts any string). `extraction_method`: `"manual-bbox"`.
- sha256 is of the bytes written to disk (the cropped PDF bytes and the PNG bytes).
- Vector preservation: use `show_pdf_page` with a `clip` rect — do NOT rasterize the PDF (only the PNG is raster).
- `--overwrite` cleans `<out>/<slug>/` (same semantics as Phase 1); validate manifest before saving (same as Phase 1).
- Offline; no network; output confined to `--out`.

**Pre-req:** PyMuPDF installed (`pip install --user pymupdf`). `check_deps.py` reports `[OK] PyMuPDF`.

---

## File Structure

Phase 2 creates/modifies these files.

| Path | Responsibility |
| --- | --- |
| `.claude/skills/paper-pdf-figures/scripts/crop_export.py` | `FigureConfig`, `parse_config(path)`, `crop_figures(doc, figures, out_dir, paper_slug, dpi, formats, dry_run) -> list[Figure]` |
| `.claude/skills/paper-pdf-figures/scripts/extract_pdf_figures.py` | Modify: add `manual` mode + `--config`/`--dpi`/`--formats` args |
| `.claude/skills/paper-pdf-figures/templates/config.example.yaml` | Example bbox config |
| `.claude/skills/paper-pdf-figures/tests/conftest.py` | Modify: add `vector_pdf` fixture (draws shapes + text) |
| `.claude/skills/paper-pdf-figures/tests/test_crop_export.py` | Unit tests for crop_export.py |

`extract_embedded.py`, `manifest.py`, `check_deps.py`, schema are reused unchanged.

---

## Task 1: Crop core + config parsing + test fixture

**Files:**
- Create: `.claude/skills/paper-pdf-figures/scripts/crop_export.py`
- Modify: `.claude/skills/paper-pdf-figures/tests/conftest.py` (add `vector_pdf` fixture)
- Create: `.claude/skills/paper-pdf-figures/tests/test_crop_export.py`

**Interfaces:**
- Consumes: `manifest.Figure(id, page, bbox_pdf_points, type, extraction_method, dpi, files, sha256, caption)` from Phase 0. `tests/conftest.py` puts `scripts/` on `sys.path`.
- Produces: `crop_export.FigureConfig(id, page, bbox, caption, export)` dataclass.
- Produces: `crop_export.parse_config(path) -> list[FigureConfig]` — reads YAML, validates bbox has 4 numbers, `page` is int ≥1.
- Produces: `crop_export.crop_figures(doc, figures, out_dir, paper_slug, dpi=300, formats=None, dry_run=False) -> list[Figure]` — for each FigureConfig, builds a 1-page vector PDF via `show_pdf_page(clip=bbox)`, renders PNG at `dpi`, writes `figures/{id}/{id}.{ext}`, returns `Figure` records with sha256 of written bytes. Duplicate `id` raises `ValueError`.

- [ ] **Step 1: Extend `tests/conftest.py` with the `vector_pdf` fixture**

Append to the existing `conftest.py` (keep the `sys.path` block and `embedded_pdf` fixture intact):
```python
@pytest.fixture
def vector_pdf(tmp_path):
    """A 1-page PDF with drawn vector shapes + text, for crop testing.

    Page is US Letter (612x792). A red rect at (72,72)-(200,200) with the
    text 'FIGURE 1' inside it; a blue rect at (300,300)-(540,540).
    """
    import fitz

    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.draw_rect(fitz.Rect(72, 72, 200, 200), color=(1, 0, 0), width=2)
    page.insert_text((90, 130), "FIGURE 1", fontsize=14)
    page.draw_rect(fitz.Rect(300, 300, 540, 540), color=(0, 0, 1), width=2)
    p = tmp_path / "vector.pdf"
    doc.save(str(p))
    doc.close()
    return p
```

- [ ] **Step 2: Write the failing tests**

File `.claude/skills/paper-pdf-figures/tests/test_crop_export.py`:
```python
import hashlib

import fitz
from PIL import Image

import crop_export
import manifest


def test_crop_preserves_vector_and_text(vector_pdf, tmp_path):
    doc = fitz.open(str(vector_pdf))
    figs = [crop_export.FigureConfig(
        id="fig_001", page=1, bbox=[60, 60, 210, 210], caption="A red box.",
    )]
    results = crop_export.crop_figures(doc, figs, tmp_path / "out", "paper", dpi=150)

    assert len(results) == 1
    r = results[0]
    assert r.id == "fig_001"
    assert r.page == 1
    assert r.bbox_pdf_points == [60, 60, 210, 210]
    assert r.type == "page-crop"
    assert r.extraction_method == "manual-bbox"
    assert r.dpi == 150
    assert r.caption == "A red box."

    # PDF: vector + text preserved
    pdf_path = tmp_path / "out" / "paper" / r.files["pdf"]
    assert pdf_path.is_file()
    cdoc = fitz.open(str(pdf_path))
    assert len(cdoc) == 1
    assert "FIGURE 1" in cdoc[0].get_text()           # text preserved
    assert len(cdoc[0].get_drawings()) > 0            # vector preserved
    # correct page size = bbox dimensions
    assert abs(cdoc[0].rect.width - 150) < 1 and abs(cdoc[0].rect.height - 150) < 1
    cdoc.close()

    # PNG: valid, non-trivial, sha matches file
    png_path = tmp_path / "out" / "paper" / r.files["png"]
    assert png_path.is_file()
    im = Image.open(png_path)
    assert im.format == "PNG"
    assert im.size[0] > 100 and im.size[1] > 100       # dpi=150 on 150pt region → ~312px
    assert r.sha256["pdf"] == hashlib.sha256(pdf_path.read_bytes()).hexdigest()
    assert r.sha256["png"] == hashlib.sha256(png_path.read_bytes()).hexdigest()
    doc.close()


def test_crop_records_are_manifest_valid(vector_pdf, tmp_path):
    doc = fitz.open(str(vector_pdf))
    figs = [
        crop_export.FigureConfig(id="fig_001", page=1, bbox=[60, 60, 210, 210]),
        crop_export.FigureConfig(id="fig_002", page=1, bbox=[290, 290, 550, 550]),
    ]
    m = manifest.Manifest("vector.pdf", "paper", "0.1.0")
    for r in crop_export.crop_figures(doc, figs, tmp_path / "out", "paper"):
        m.add_figure(r)
    assert manifest.validate(m.to_dict()) == []
    doc.close()


def test_formats_filter_skips_png(vector_pdf, tmp_path):
    doc = fitz.open(str(vector_pdf))
    figs = [crop_export.FigureConfig(id="fig_001", page=1, bbox=[60, 60, 210, 210])]
    results = crop_export.crop_figures(
        doc, figs, tmp_path / "out", "paper", formats=["pdf"]
    )
    r = results[0]
    assert r.files["pdf"] is not None
    assert r.files["png"] is None
    assert "png" not in r.sha256
    assert (tmp_path / "out" / "paper" / r.files["pdf"]).is_file()
    assert not (tmp_path / "out" / "paper" / "figures" / "fig_001" / "fig_001.png").exists()
    doc.close()


def test_dry_run_writes_no_files(vector_pdf, tmp_path):
    doc = fitz.open(str(vector_pdf))
    figs = [crop_export.FigureConfig(id="fig_001", page=1, bbox=[60, 60, 210, 210])]
    results = crop_export.crop_figures(
        doc, figs, tmp_path / "out", "paper", dry_run=True
    )
    assert len(results) == 1
    assert results[0].files == {"pdf": None, "png": None, "svg": None}
    assert not (tmp_path / "out").exists() or not any((tmp_path / "out").rglob("*.pdf"))
    doc.close()


def test_duplicate_figure_id_raises(vector_pdf, tmp_path):
    doc = fitz.open(str(vector_pdf))
    figs = [
        crop_export.FigureConfig(id="fig_001", page=1, bbox=[60, 60, 210, 210]),
        crop_export.FigureConfig(id="fig_001", page=1, bbox=[290, 290, 550, 550]),
    ]
    import pytest
    with pytest.raises(ValueError, match="duplicate figure id"):
        crop_export.crop_figures(doc, figs, tmp_path / "out", "paper")
    doc.close()


def test_parse_config_reads_yaml(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "pdf: paper.pdf\n"
        "figures:\n"
        "  - id: fig_001\n"
        "    page: 3\n"
        "    bbox: [72, 110, 540, 410]\n"
        "    caption: Figure 1.\n"
        "    export: [pdf, png]\n"
        "  - id: fig_002\n"
        "    page: 5\n"
        "    bbox: [60, 95, 550, 690]\n"
    )
    figs = crop_export.parse_config(cfg)
    assert len(figs) == 2
    assert figs[0].id == "fig_001" and figs[0].page == 3
    assert figs[0].bbox == [72, 110, 540, 410]
    assert figs[0].caption == "Figure 1."
    assert figs[0].export == ["pdf", "png"]
    assert figs[1].export is None                    # None when omitted -> uses global --formats


def test_per_figure_export_overrides_global_formats(vector_pdf, tmp_path):
    """fig.export, when set, overrides the global formats for that figure."""
    doc = fitz.open(str(vector_pdf))
    figs = [crop_export.FigureConfig(
        id="fig_001", page=1, bbox=[60, 60, 210, 210], export=["pdf"],
    )]
    results = crop_export.crop_figures(
        doc, figs, tmp_path / "out", "paper", formats=["pdf", "png"]
    )
    r = results[0]
    assert r.files["pdf"] is not None
    assert r.files["png"] is None, "per-figure export=[pdf] must override global formats=[pdf,png]"
    assert (tmp_path / "out" / "paper" / r.files["pdf"]).is_file()
    assert not (tmp_path / "out" / "paper" / "figures" / "fig_001" / "fig_001.png").exists()
    doc.close()
```

- [ ] **Step 3: Run tests to verify they fail**

Run:
```bash
cd /home/imalne/learn_vibe_coding/.claude/skills/paper-pdf-figures
pytest tests/test_crop_export.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'crop_export'`.

- [ ] **Step 4: Write `scripts/crop_export.py`**

File `.claude/skills/paper-pdf-figures/scripts/crop_export.py`:
```python
"""Crop figure regions from a PDF by bbox (Phase 2: --mode manual).

Uses page.show_pdf_page(clip=bbox) to embed the cropped region as a Form
XObject in a fresh 1-page PDF, preserving vector content and text. Renders a
PNG preview from that page at the requested DPI.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import fitz
import yaml

from manifest import Figure

DEFAULT_FORMATS = ["pdf", "png"]


@dataclass
class FigureConfig:
    id: str
    page: int
    bbox: list[float]
    caption: str = ""
    export: list[str] | None = None


def parse_config(path: str | Path) -> list[FigureConfig]:
    data = yaml.safe_load(Path(path).read_text())
    figures = []
    for f in data.get("figures", []):
        bbox = [float(x) for x in f["bbox"]]
        if len(bbox) != 4:
            raise ValueError(f"figure {f.get('id')} bbox must have 4 values, got {len(bbox)}")
        page = int(f["page"])
        if page < 1:
            raise ValueError(f"figure {f.get('id')} page must be >= 1, got {page}")
        figures.append(FigureConfig(
            id=str(f["id"]),
            page=page,
            bbox=bbox,
            caption=str(f.get("caption", "")),
            export=list(f["export"]) if f.get("export") else None,
        ))
    return figures


def crop_figures(
    doc: "fitz.Document",
    figures: list[FigureConfig],
    out_dir: Path | str,
    paper_slug: str,
    dpi: int = 300,
    formats: list[str] | None = None,
    dry_run: bool = False,
) -> list[Figure]:
    """Crop each figure's bbox region into a vector PDF + PNG preview.

    Returns one Figure per FigureConfig (in order). Duplicate ids raise ValueError.
    """
    if formats is None:
        formats = list(DEFAULT_FORMATS)
    out_dir = Path(out_dir)
    figs_dir = out_dir / paper_slug / "figures"
    if not dry_run:
        figs_dir.mkdir(parents=True, exist_ok=True)

    seen_ids: set[str] = set()
    results: list[Figure] = []

    for fig in figures:
        if fig.id in seen_ids:
            raise ValueError(f"duplicate figure id: {fig.id}")
        seen_ids.add(fig.id)

        if fig.page < 1 or fig.page > len(doc):
            raise ValueError(f"figure {fig.id} page {fig.page} out of range (1..{len(doc)})")

        clip = fitz.Rect(*fig.bbox)
        # Build a 1-page PDF containing the cropped region (vector-preserving).
        pdf_doc = fitz.open()
        p = pdf_doc.new_page(width=clip.width, height=clip.height)
        p.show_pdf_page(p.rect, doc, fig.page - 1, clip=clip)
        pdf_bytes = pdf_doc.tobytes()
        png_bytes = p.get_pixmap(dpi=dpi).tobytes("png")
        pdf_doc.close()

        files = {"pdf": None, "png": None, "svg": None}
        sha: dict[str, str] = {}
        fig_formats = fig.export if fig.export is not None else formats
        if not dry_run:
            fig_dir = figs_dir / fig.id
            fig_dir.mkdir(parents=True, exist_ok=True)
            if "pdf" in fig_formats:
                (fig_dir / f"{fig.id}.pdf").write_bytes(pdf_bytes)
                files["pdf"] = f"figures/{fig.id}/{fig.id}.pdf"
                sha["pdf"] = hashlib.sha256(pdf_bytes).hexdigest()
            if "png" in fig_formats:
                (fig_dir / f"{fig.id}.png").write_bytes(png_bytes)
                files["png"] = f"figures/{fig.id}/{fig.id}.png"
                sha["png"] = hashlib.sha256(png_bytes).hexdigest()

        results.append(Figure(
            id=fig.id,
            page=fig.page,
            bbox_pdf_points=list(fig.bbox),
            type="page-crop",
            extraction_method="manual-bbox",
            dpi=dpi,
            files=files,
            sha256=sha,
            caption=fig.caption,
        ))
    return results
```

- [ ] **Step 5: Run tests to verify they pass**

Run:
```bash
cd /home/imalne/learn_vibe_coding/.claude/skills/paper-pdf-figures
pytest tests/test_crop_export.py -v
```
Expected: 6 passed.

- [ ] **Step 6: Commit**

```bash
cd /home/imalne/learn_vibe_coding
git add .claude/skills/paper-pdf-figures/scripts/crop_export.py .claude/skills/paper-pdf-figures/tests/test_crop_export.py .claude/skills/paper-pdf-figures/tests/conftest.py
git commit -m "feat(paper-pdf-figures): crop figures by bbox preserving vector + text (Phase 2)"
```

---

## Task 2: Dispatcher `manual` mode + config template + integration tests

**Files:**
- Modify: `.claude/skills/paper-pdf-figures/scripts/extract_pdf_figures.py` (add `manual` branch + `--config`/`--dpi`/`--formats` args; phase-agnostic "not implemented" message)
- Modify: `.claude/skills/paper-pdf-figures/tests/test_extract_pdf_figures.py` (update unimplemented-mode assertion; add 3 manual-mode tests)
- Create: `.claude/skills/paper-pdf-figures/templates/config.example.yaml`

**Interfaces:**
- Consumes: `crop_export.crop_figures` + `crop_export.parse_config` from Task 1; Phase 1 `extract_embedded_images`; Phase 0 `Manifest`/`validate`.
- Produces: `--mode manual` end-to-end: reads `--config`, crops each figure, writes `figures/<id>/{<id>.pdf,<id>.png}`, saves `manifest.json` with `figures[]`, prints `figures: N` summary.
- Produces: `parse_formats(spec) -> list[str]` (helper, `"pdf,png"` → `["pdf","png"]`).

- [ ] **Step 1: Write the failing integration tests + update one Phase 1 assertion**

Append to `.claude/skills/paper-pdf-figures/tests/test_extract_pdf_figures.py`:
```python
def test_manual_mode_crops_figures_from_config(vector_pdf, tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        f"pdf: {vector_pdf}\n"
        "figures:\n"
        "  - id: fig_001\n"
        "    page: 1\n"
        "    bbox: [60, 60, 210, 210]\n"
        "    caption: Red box.\n"
        "  - id: fig_002\n"
        "    page: 1\n"
        "    bbox: [290, 290, 550, 550]\n"
    )
    out = tmp_path / "out"
    r = _run(vector_pdf, out, "--mode", "manual", "--config", str(cfg),
             "--paper-slug", "p", "--dpi", "150")
    assert r.returncode == 0, r.stderr
    assert "figures: 2" in r.stdout
    m = manifest.Manifest.load(out / "p" / "manifest.json")
    assert len(m.figures) == 2
    assert m.figures[0].id == "fig_001"
    assert m.figures[0].bbox_pdf_points == [60, 60, 210, 210]
    assert m.figures[0].extraction_method == "manual-bbox"
    assert m.figures[0].dpi == 150
    assert (out / "p" / "figures" / "fig_001" / "fig_001.pdf").is_file()
    assert (out / "p" / "figures" / "fig_001" / "fig_001.png").is_file()
    assert (out / "p" / "figures" / "fig_002" / "fig_002.pdf").is_file()
    assert manifest.validate(m.to_dict()) == []


def test_manual_mode_requires_config(embedded_pdf, tmp_path):
    pdf_path, _ = embedded_pdf
    r = _run(pdf_path, tmp_path / "out", "--mode", "manual")
    assert r.returncode == 1
    assert "requires --config" in r.stderr


def test_manual_mode_formats_filter(vector_pdf, tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "figures:\n"
        "  - id: fig_001\n"
        "    page: 1\n"
        "    bbox: [60, 60, 210, 210]\n"
    )
    out = tmp_path / "out"
    r = _run(vector_pdf, out, "--mode", "manual", "--config", str(cfg),
             "--paper-slug", "p", "--formats", "pdf")
    assert r.returncode == 0, r.stderr
    assert (out / "p" / "figures" / "fig_001" / "fig_001.pdf").is_file()
    assert not (out / "p" / "figures" / "fig_001" / "fig_001.png").exists()


def test_manual_mode_missing_config_clean_error(vector_pdf, tmp_path):
    r = _run(vector_pdf, tmp_path / "out", "--mode", "manual",
             "--config", str(tmp_path / "nonexistent.yaml"), "--paper-slug", "p")
    assert r.returncode == 1
    assert "ERROR:" in r.stderr
    assert "Traceback" not in r.stderr


def test_manual_mode_malformed_yaml_clean_error(vector_pdf, tmp_path):
    cfg = tmp_path / "bad.yaml"
    cfg.write_text("figures: [this is not valid yaml: : :\n")
    r = _run(vector_pdf, tmp_path / "out", "--mode", "manual",
             "--config", str(cfg), "--paper-slug", "p")
    assert r.returncode == 1
    assert "ERROR:" in r.stderr
    assert "Traceback" not in r.stderr


def test_dpi_validation(vector_pdf, tmp_path):
    cfg = tmp_path / "c.yaml"
    cfg.write_text("figures:\n  - id: fig_001\n    page: 1\n    bbox: [60, 60, 210, 210]\n")
    r = _run(vector_pdf, tmp_path / "out", "--mode", "manual", "--config", str(cfg),
             "--paper-slug", "p", "--dpi", "0")
    assert r.returncode == 1
    assert "dpi" in r.stderr.lower()
```

Also update the existing Phase 1 assertion (the message becomes phase-agnostic). In `test_unimplemented_mode_errors`, change:
```python
    assert "not implemented in Phase 1" in r.stderr
```
to:
```python
    assert "not implemented" in r.stderr
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd /home/imalne/learn_vibe_coding/.claude/skills/paper-pdf-figures
pytest tests/test_extract_pdf_figures.py -v
```
Expected: the 3 new manual-mode tests FAIL (no `--config`/`--dpi`/`--formats` args yet, "not implemented" for manual). The updated assertion may also fail until the dispatcher changes.

- [ ] **Step 3: Rewrite `scripts/extract_pdf_figures.py` with the `manual` branch**

Replace the entire file `.claude/skills/paper-pdf-figures/scripts/extract_pdf_figures.py` with:
```python
#!/usr/bin/env python3
"""CLI dispatcher for paper-pdf-figures.

Phase 1: --mode embedded (extract embedded raster images).
Phase 2: --mode manual  (crop figure regions by bbox from config.yaml -> PDF+PNG).
detect / render / auto are not yet implemented.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import fitz
import yaml

from crop_export import crop_figures, parse_config
from extract_embedded import extract_embedded_images
from manifest import Manifest, validate

VERSION_FILE = Path(__file__).resolve().parent.parent / "VERSION"
DEFAULT_FORMATS = ["pdf", "png"]


def read_version() -> str:
    try:
        return VERSION_FILE.read_text().strip()
    except OSError:
        return "0.0.0"


def parse_pages(spec: str | None) -> set[int] | None:
    if not spec:
        return None
    pages: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo, hi = part.split("-", 1)
            pages.update(range(int(lo), int(hi) + 1))
        else:
            pages.add(int(part))
    return pages or None


def parse_formats(spec: str | None) -> list[str]:
    if not spec:
        return list(DEFAULT_FORMATS)
    return [f.strip() for f in spec.split(",") if f.strip()]


def paper_slug_from_pdf(pdf_path: Path) -> str:
    name = pdf_path.stem
    return "".join(c if (c.isalnum() or c in "-_") else "_" for c in name)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="extract_pdf_figures")
    parser.add_argument("pdf_path")
    parser.add_argument("--mode", default="embedded",
                        choices=["embedded", "manual", "detect", "render", "auto"])
    parser.add_argument("--out", required=True)
    parser.add_argument("--paper-slug", default=None)
    parser.add_argument("--pages", default=None)
    parser.add_argument("--config", default=None)
    parser.add_argument("--dpi", type=int, default=300)
    parser.add_argument("--formats", default=None)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    if args.mode not in ("embedded", "manual"):
        print(f"mode '{args.mode}' is not implemented yet", file=sys.stderr)
        return 1
    if args.mode == "manual" and not args.config:
        print("ERROR: --mode manual requires --config CONFIG.yaml", file=sys.stderr)
        return 1
    if args.dpi < 1:
        print(f"ERROR: --dpi must be >= 1, got {args.dpi}", file=sys.stderr)
        return 1

    pdf_path = Path(args.pdf_path)
    out_dir = Path(args.out)
    slug = args.paper_slug or paper_slug_from_pdf(pdf_path)
    paper_dir = out_dir / slug
    manifest_path = paper_dir / "manifest.json"

    if not args.dry_run and manifest_path.exists() and not args.overwrite:
        print(f"ERROR: {manifest_path} already exists; use --overwrite to replace",
              file=sys.stderr)
        return 1
    if not args.dry_run and args.overwrite and paper_dir.exists():
        shutil.rmtree(paper_dir)

    formats = parse_formats(args.formats)

    doc = fitz.open(str(pdf_path))
    try:
        if args.mode == "embedded":
            pages = parse_pages(args.pages)
            records = extract_embedded_images(
                doc, out_dir, slug, pages=pages, dry_run=args.dry_run
            )
        else:  # manual
            try:
                figures = parse_config(args.config)
                records = crop_figures(
                    doc, figures, out_dir, slug,
                    dpi=args.dpi, formats=formats, dry_run=args.dry_run,
                )
            except (OSError, yaml.YAMLError, ValueError, KeyError) as e:
                print(f"ERROR: {e}", file=sys.stderr)
                return 1
    finally:
        doc.close()

    m = Manifest(
        source_pdf=str(pdf_path),
        paper_slug=slug,
        tool_version=read_version(),
        run_args={
            "mode": args.mode, "pages": args.pages, "config": args.config,
            "dpi": args.dpi, "formats": args.formats, "dry_run": args.dry_run,
        },
    )
    if args.mode == "embedded":
        for rec in records:
            m.add_embedded_image(rec)
        if not records:
            m.add_warning("WARN_NO_EMBEDDED_IMAGES")
    else:  # manual
        for rec in records:
            m.add_figure(rec)
        if not records:
            m.add_warning("WARN_NO_FIGURES")

    if not args.dry_run:
        errs = validate(m.to_dict())
        if errs:
            print("ERROR: manifest failed schema validation:", file=sys.stderr)
            for e in errs:
                print(f"  {e}", file=sys.stderr)
            return 1
        m.save(manifest_path)

    print(f"source_pdf: {pdf_path}")
    print(f"paper_slug: {slug}")
    if args.mode == "embedded":
        print(f"embedded_images: {len(records)}")
    else:
        print(f"figures: {len(records)}")
    if not args.dry_run:
        print(f"manifest: {manifest_path}")
    print(f"warnings: {[w.code for w in m.warnings]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Write `templates/config.example.yaml`**

File `.claude/skills/paper-pdf-figures/templates/config.example.yaml`:
```yaml
# Configuration for --mode manual: crop figure regions by bbox.
# Usage:
#   python3 extract_pdf_figures.py paper.pdf --mode manual \
#       --config config.yaml --out ./figures
#
# bbox is [x0, y0, x1, y1] in PDF points (origin top-left; 1 point = 1/72 inch).
# page is 1-based. id is used as the output directory and filename.

pdf: paper.pdf
paper_slug: my_paper_2026
figures:
  - id: fig_001
    page: 3
    bbox: [72, 110, 540, 410]
    caption: "Figure 1: Overview of the proposed framework."
    export: [pdf, png]

  - id: fig_002
    page: 5
    bbox: [60, 95, 550, 690]
    caption: "Figure 2: Quantitative and qualitative comparison."
    export: [pdf, png]
```

- [ ] **Step 5: Run tests to verify they pass**

Run:
```bash
cd /home/imalne/learn_vibe_coding/.claude/skills/paper-pdf-figures
pytest tests/test_extract_pdf_figures.py -v
```
Expected: 12 passed (9 from Phase 1 + Task 2 fix + 3 new manual tests). Then run the full suite:
```bash
pytest tests/ -q
```
Expected: 46 passed (34 from Phase 0+1 + 6 crop_export + 6 new/updated here = 46). Adjust the count if it differs — the binding check is "all green, no regressions".

- [ ] **Step 6: Commit**

```bash
cd /home/imalne/learn_vibe_coding
git add .claude/skills/paper-pdf-figures/scripts/extract_pdf_figures.py .claude/skills/paper-pdf-figures/tests/test_extract_pdf_figures.py .claude/skills/paper-pdf-figures/templates/config.example.yaml
git commit -m "feat(paper-pdf-figures): CLI manual mode + config template (Phase 2)"
```

---

## Task 3: Source-PDF-unchanged guard for manual mode + Phase 2 acceptance

**Files:**
- Modify: `.claude/skills/paper-pdf-figures/tests/test_extract_pdf_figures.py` (append one test)

**Interfaces:**
- Consumes: Task 2's `manual` mode + `vector_pdf` fixture.

- [ ] **Step 1: Append the source-PDF-unchanged test for manual mode**

Append to `.claude/skills/paper-pdf-figures/tests/test_extract_pdf_figures.py`:
```python
def test_manual_mode_leaves_source_pdf_unchanged(vector_pdf, tmp_path):
    import hashlib

    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "figures:\n"
        "  - id: fig_001\n"
        "    page: 1\n"
        "    bbox: [60, 60, 210, 210]\n"
    )
    before = hashlib.sha256(vector_pdf.read_bytes()).hexdigest()
    r = _run(vector_pdf, tmp_path / "out", "--mode", "manual", "--config", str(cfg),
             "--paper-slug", "p")
    assert r.returncode == 0, r.stderr
    after = hashlib.sha256(vector_pdf.read_bytes()).hexdigest()
    assert before == after
```

- [ ] **Step 2: Run the test, then the full suite**

Run:
```bash
cd /home/imalne/learn_vibe_coding/.claude/skills/paper-pdf-figures
pytest tests/test_extract_pdf_figures.py::test_manual_mode_leaves_source_pdf_unchanged -v
pytest tests/ -q
```
Expected: 1 passed, then 47 passed total (46 + 1 new).

- [ ] **Step 3: Commit**

```bash
cd /home/imalne/learn_vibe_coding
git add .claude/skills/paper-pdf-figures/tests/test_extract_pdf_figures.py
git commit -m "test(paper-pdf-figures): guard source PDF unchanged in manual mode (Phase 2)"
```

---

## Phase 2 Acceptance

After all 3 tasks, verify the spec's Phase 2 acceptance (§11 Phase 2):

- [ ] **A1: vector figures crop correctly, cropped PDF zoomable.** Open `figures/fig_001/fig_001.pdf` — it must contain vector drawings + text (verified in `test_crop_preserves_vector_and_text`: `get_drawings()` > 0 and `"FIGURE 1" in get_text()`).
- [ ] **A2: PNG preview clear.** `fig_001.png` is a valid PNG at `--dpi` resolution (verified: PIL opens it, dimensions scale with dpi).
- [ ] **A3: manifest records bbox + exported files.** `manifest.json` `figures[]` has `bbox_pdf_points`, `files{pdf,png}`, `sha256`, `extraction_method="manual-bbox"`, `dpi` (verified in `test_manual_mode_crops_figures_from_config`).
- [ ] **A4: source PDF not modified.** sha256 before == after (verified in `test_manual_mode_leaves_source_pdf_unchanged`).
- [ ] **A5: full suite passes.** `pytest tests/ -q` → 47 passed.
- [ ] **A6: `check_deps` reports `[OK] PyMuPDF`.**

**Real-paper smoke (manual, not automated):** on `2606.28301v1.pdf` (the vector paper), write a `config.yaml` with a bbox over a figure on page 11 (e.g. `bbox: [50, 100, 550, 400]`), run `--mode manual`, and confirm the cropped PDF opens zoomable with axis labels intact. This is the use case Phase 1 could not serve.

---

## Self-Review Notes

**Spec coverage (Phase 2 scope):**
- §7.2 (crop complete figure, PDF+PNG, vector-preserving) → Task 1 `crop_figures` via `show_pdf_page(clip=)`.
- §7.3 (manual bbox config.yaml) → Task 1 `parse_config` + Task 2 `--config` + `templates/config.example.yaml`.
- §9.3 naming (`figures/fig_NNN/`) → Task 1 uses `figures/{id}/{id}.{ext}`.
- §11 Phase 2 acceptance → Task 3 + Phase 2 Acceptance section.
- SVG export is NOT in Phase 2 (deferred to Phase 3); `--formats` accepts `pdf,png` only for now (svg path left as None).

**Placeholder scan:** none — every code step has complete code, every command has expected output.

**Type consistency:** `crop_figures` returns `manifest.Figure` records with `extraction_method="manual-bbox"`, `type="page-crop"`, `files={pdf,png,svg}` (svg None), matching `manifest.schema.json`. `FigureConfig` fields (`id, page, bbox, caption, export`) match `config.example.yaml`. `parse_formats` and `parse_pages` are distinct helpers (no name clash). The dispatcher's `--dpi` (int, default 300) flows to `crop_figures(dpi=)` and into `Figure.dpi`.

**Phase 1 compatibility:** the dispatcher rewrite preserves all Phase 1 `embedded` behavior (same args, same overwrite/validate-before-save semantics, same summary). Only the unimplemented-mode message changes ("Phase 1" → "yet"), and the one Phase 1 assertion is updated to match.
