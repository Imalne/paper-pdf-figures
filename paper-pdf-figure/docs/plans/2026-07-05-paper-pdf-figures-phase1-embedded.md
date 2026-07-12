# Paper PDF Figures — Phase 1 (Embedded Extraction) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `--mode embedded`: extract embedded raster images from a PDF using PyMuPDF, dedup by xref, compute sha256, write files with the spec naming convention, and record them in `manifest.json` — wired through a thin `extract_pdf_figures.py` dispatcher.

**Architecture:** `extract_pdf_figures.py` is a thin CLI dispatcher (argparse → mode). `extract_embedded.py` holds the extraction logic: iterate pages, `page.get_images()` → `doc.extract_image(xref)`, dedup seen xrefs, save bytes, build `EmbeddedImage` records. Reuses the Phase 0 `manifest.py` (`Manifest`, `EmbeddedImage`, `validate`). Other modes (`manual`/`detect`/`render`/`auto`) print "not implemented in Phase 1" — they get their own later plans.

**Tech Stack:** Python ≥3.9, PyMuPDF (`fitz`), Pillow (test fixture only), pytest + jsonschema (already installed from Phase 0).

## Global Constraints

(From the spec `paper-pdf-figure/docs/designs/paper-pdf-figure.md` — every task inherits these.)

- Skill root: `.claude/skills/paper-pdf-figures/`; tests run from there: `cd .claude/skills/paper-pdf-figures && pytest tests/ -v`
- Never modify the original PDF (open read-only; verify byte-identical after extraction).
- `manifest.json` is the single source of truth; reuse Phase 0 `manifest.py` dataclasses — do not duplicate them.
- `EmbeddedImage` fields (from `manifest.py`): `id, page, xref, format, width, height, file, sha256` — `page` is 1-based (schema `minimum: 1`).
- File naming (spec §9.2): `embedded/p{page:04d}_xref{xref:06d}.{ext}` — page is 1-based, matching the manifest `page` value.
- Dedup: same xref referenced from multiple pages → saved once, recorded once, under the first page it appears on.
- Offline; no network; output confined to `--out`; subprocess list-form calls; sanitize nothing user-supplied into a shell (argparse handles paths).
- `tool_version` read from `VERSION` file (currently `0.1.0`).
- **PyMuPDF API note:** `page.get_images(full=True)` returns tuples `(xref, smask, width, height, bpc, colorspace, alt_colorspace, name, filter, referencer)`; `doc.extract_image(xref)` returns `{"ext": "png", "image": b"...", "width": w, "height": h, ...}`. If the installed PyMuPDF's tuple/dict shape differs, adjust the indexing in `extract_embedded.py` — the tests below will catch any mismatch.
- **sha256 semantics:** `doc.extract_image(xref)` RE-ENCODES the image (it is not the raw embedded byte stream). The `sha256` recorded in the manifest is therefore the sha of the bytes actually written to disk (the re-encoded image), NOT the sha of the original embedded stream. Tests must assert `rec.sha256 == sha256(saved_file_bytes)`, never `== sha256(original_input_bytes)`.

**Pre-req:** PyMuPDF must be installed (`pip install --user pymupdf`). `check_deps.py` should report `[OK] PyMuPDF` before starting.

---

## File Structure

Phase 1 creates/modifies these files.

| Path | Responsibility |
| --- | --- |
| `.claude/skills/paper-pdf-figures/scripts/extract_embedded.py` | Core extraction: `extract_embedded_images(doc, out_dir, paper_slug, pages=None, dry_run=False) -> list[EmbeddedImage]` |
| `.claude/skills/paper-pdf-figures/scripts/extract_pdf_figures.py` | CLI dispatcher: argparse, `--mode embedded`, parse `--pages`, build Manifest, save, print summary |
| `.claude/skills/paper-pdf-figures/tests/conftest.py` | Extend: add `embedded_pdf` fixture (generates a tiny PDF with one PNG on two pages) |
| `.claude/skills/paper-pdf-figures/tests/test_extract_embedded.py` | Unit tests for extract_embedded.py |
| `.claude/skills/paper-pdf-figures/tests/test_extract_pdf_figures.py` | Integration tests for the dispatcher (subprocess) |

`manifest.py`, `manifest.schema.json`, `check_deps.py` are reused from Phase 0 unchanged.

---

## Task 1: Embedded extraction core + test fixture

**Files:**
- Create: `.claude/skills/paper-pdf-figures/scripts/extract_embedded.py`
- Modify: `.claude/skills/paper-pdf-figures/tests/conftest.py` (add `embedded_pdf` fixture)
- Create: `.claude/skills/paper-pdf-figures/tests/test_extract_embedded.py`

**Interfaces:**
- Consumes: `manifest.EmbeddedImage(id, page, xref, format, width, height, file, sha256)` from Phase 0 `scripts/manifest.py`. `tests/conftest.py` already puts `scripts/` on `sys.path`.
- Produces: `extract_embedded.extract_embedded_images(doc, out_dir, paper_slug, pages=None, dry_run=False) -> list[EmbeddedImage]`.
  - `doc`: an open `fitz.Document`.
  - `out_dir`: root output directory (the `paper_slug/embedded/` tree is created inside it).
  - `pages`: `set[int]` of 1-based page numbers to restrict to, or `None` for all pages.
  - `dry_run`: if True, compute records but do NOT write files.
  - Returns one `EmbeddedImage` per unique xref; `file` is the path relative to `out_dir`; `page` is 1-based (first page the xref appears on).

- [ ] **Step 1: Extend `tests/conftest.py` with the `embedded_pdf` fixture**

The current `conftest.py` is:
```python
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
```

Append the fixture (keep the existing block intact):
```python
import io
import pytest


@pytest.fixture
def embedded_pdf(tmp_path):
    """A tiny PDF with one PNG embedded on two pages (for dedup testing).

    Returns (path, original_png_bytes). The same image bytes are inserted on
    both pages so the extractor should dedup to a single output file.
    """
    import fitz
    from PIL import Image

    img = Image.new("RGB", (12, 10), "red")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    img_bytes = buf.getvalue()

    doc = fitz.open()
    for _ in range(2):
        page = doc.new_page()
        page.insert_image(fitz.Rect(0, 0, 120, 100), stream=img_bytes)
    pdf_path = tmp_path / "fixture.pdf"
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path, img_bytes
```

- [ ] **Step 2: Write the failing tests**

File `.claude/skills/paper-pdf-figures/tests/test_extract_embedded.py`:
```python
import hashlib
import json

import fitz

import extract_embedded
import manifest


def test_extract_dedups_same_xref_across_pages(embedded_pdf, tmp_path):
    pdf_path, _ = embedded_pdf
    doc = fitz.open(str(pdf_path))
    out_dir = tmp_path / "out"

    results = extract_embedded.extract_embedded_images(doc, out_dir, "paper")

    assert len(results) == 1, "same image on 2 pages must dedup to 1 record"
    rec = results[0]
    assert rec.page == 1                      # first page it appears on, 1-based
    assert rec.format == "png"
    assert rec.width == 12 and rec.height == 10
    assert rec.id == f"embedded_p{rec.page:04d}_xref{rec.xref:06d}"
    # file written with the spec naming convention, relative to out_dir
    expected_name = f"embedded/p{rec.page:04d}_xref{rec.xref:06d}.png"
    assert rec.file == expected_name
    saved = (out_dir / "paper" / expected_name).read_bytes()
    assert saved[:8] == b"\x89PNG\r\n\x1a\n"              # valid PNG magic
    assert rec.sha256 == hashlib.sha256(saved).hexdigest()  # sha matches saved file
    doc.close()


def test_extract_records_are_manifest_valid(embedded_pdf, tmp_path):
    pdf_path, _ = embedded_pdf
    doc = fitz.open(str(pdf_path))

    m = manifest.Manifest("fixture.pdf", "paper", "0.1.0")
    for rec in extract_embedded.extract_embedded_images(doc, tmp_path / "out", "paper"):
        m.add_embedded_image(rec)

    assert manifest.validate(m.to_dict()) == []
    doc.close()


def test_dry_run_writes_no_files(embedded_pdf, tmp_path):
    pdf_path, _ = embedded_pdf
    doc = fitz.open(str(pdf_path))
    out_dir = tmp_path / "out"

    results = extract_embedded.extract_embedded_images(
        doc, out_dir, "paper", dry_run=True
    )

    assert len(results) == 1
    assert not out_dir.exists() or not any(out_dir.rglob("*"))
    doc.close()


def test_pages_filter_restricts_extraction(embedded_pdf, tmp_path):
    # Build a PDF with DIFFERENT images on two pages, then extract only page 2.
    import io
    from PIL import Image
    import fitz as _fitz

    buf1 = io.BytesIO(); Image.new("RGB", (8, 8), "red").save(buf1, "PNG")
    buf2 = io.BytesIO(); Image.new("RGB", (9, 7), "blue").save(buf2, "PNG")
    doc = _fitz.open()
    p1 = doc.new_page(); p1.insert_image(_fitz.Rect(0, 0, 80, 80), stream=buf1.getvalue())
    p2 = doc.new_page(); p2.insert_image(_fitz.Rect(0, 0, 90, 70), stream=buf2.getvalue())

    results = extract_embedded.extract_embedded_images(
        doc, tmp_path / "out", "paper", pages={2}
    )
    assert len(results) == 1
    assert results[0].page == 2
    assert results[0].width == 9 and results[0].height == 7
    doc.close()


def test_pages_filter_assigns_lowest_page_for_shared_xref(tmp_path):
    """Same image on pages 1 and 2; pass pages as an unordered set {2, 1}."""
    import io
    from PIL import Image

    buf = io.BytesIO(); Image.new("RGB", (8, 8), "green").save(buf, "PNG")
    doc = fitz.open()
    for _ in range(2):
        page = doc.new_page()
        page.insert_image(fitz.Rect(0, 0, 80, 80), stream=buf.getvalue())

    results = extract_embedded.extract_embedded_images(
        doc, tmp_path / "out", "paper", pages={2, 1}
    )
    assert len(results) == 1
    assert results[0].page == 1, "shared xref must be assigned to the lowest page"
    doc.close()
```

- [ ] **Step 3: Run tests to verify they fail**

Run:
```bash
cd /home/imalne/learn_vibe_coding/.claude/skills/paper-pdf-figures
pytest tests/test_extract_embedded.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'extract_embedded'`.

- [ ] **Step 4: Write `scripts/extract_embedded.py`**

File `.claude/skills/paper-pdf-figures/scripts/extract_embedded.py`:
```python
"""Extract embedded raster images from a PDF (Phase 1: --mode embedded)."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable

import fitz

from manifest import EmbeddedImage


def extract_embedded_images(
    doc: "fitz.Document",
    out_dir: Path | str,
    paper_slug: str,
    pages: Iterable[int] | None = None,
    dry_run: bool = False,
) -> list[EmbeddedImage]:
    """Extract every unique embedded image xref in `doc`.

    Args:
        doc: open fitz.Document (read-only; not modified).
        out_dir: root output directory; writes to `<out_dir>/<paper_slug>/embedded/`.
        paper_slug: subdirectory name for this paper's outputs.
        pages: iterable of 1-based page numbers to restrict to, or None for all.
        dry_run: if True, return records without writing files.

    Returns:
        One EmbeddedImage per unique xref, in first-seen order. `page` is 1-based
        (first page the xref appears on); `file` is relative to `out_dir`.
    """
    out_dir = Path(out_dir)
    embedded_dir = out_dir / paper_slug / "embedded"
    if not dry_run:
        embedded_dir.mkdir(parents=True, exist_ok=True)

    if pages is None:
        page_indices = range(len(doc))
    else:
        page_indices = sorted(p - 1 for p in pages if 1 <= p <= len(doc))

    seen: set[int] = set()
    results: list[EmbeddedImage] = []

    for pno in page_indices:
        page = doc[pno]
        for img in page.get_images(full=True):
            xref = img[0]
            if xref in seen:
                continue
            seen.add(xref)
            info = doc.extract_image(xref)
            ext = info.get("ext", "bin")
            image_bytes = info["image"]
            width = int(info.get("width", 0))
            height = int(info.get("height", 0))
            sha = hashlib.sha256(image_bytes).hexdigest()
            page_1based = pno + 1
            rel_path = f"embedded/p{page_1based:04d}_xref{xref:06d}.{ext}"
            if not dry_run:
                (embedded_dir / f"p{page_1based:04d}_xref{xref:06d}.{ext}").write_bytes(image_bytes)
            results.append(EmbeddedImage(
                id=f"embedded_p{page_1based:04d}_xref{xref:06d}",
                page=page_1based,
                xref=xref,
                format=ext,
                width=width,
                height=height,
                file=rel_path,
                sha256=sha,
            ))
    return results
```

- [ ] **Step 5: Run tests to verify they pass**

Run:
```bash
cd /home/imalne/learn_vibe_coding/.claude/skills/paper-pdf-figures
pytest tests/test_extract_embedded.py -v
```
Expected: 5 passed. If a test fails on the PyMuPDF tuple/dict shape, adjust the indexing in `extract_embedded.py` (xref is `img[0]`; `info["image"]`, `info.get("ext")`, `info.get("width")`, `info.get("height")`) until green — the API note in Global Constraints covers this.

- [ ] **Step 6: Commit**

```bash
cd /home/imalne/learn_vibe_coding
git add .claude/skills/paper-pdf-figures/scripts/extract_embedded.py .claude/skills/paper-pdf-figures/tests/test_extract_embedded.py .claude/skills/paper-pdf-figures/tests/conftest.py
git commit -m "feat(paper-pdf-figures): extract embedded images with xref dedup + sha256 (Phase 1)"
```

---

## Task 2: CLI dispatcher (`extract_pdf_figures.py`)

**Files:**
- Create: `.claude/skills/paper-pdf-figures/scripts/extract_pdf_figures.py`
- Create: `.claude/skills/paper-pdf-figures/tests/test_extract_pdf_figures.py`

**Interfaces:**
- Consumes: `extract_embedded.extract_embedded_images(...)` from Task 1; `manifest.Manifest`, `manifest.validate` from Phase 0; `VERSION` file.
- Produces: a CLI `python3 extract_pdf_figures.py PDF_PATH --out DIR --mode embedded [--paper-slug S] [--pages 1,2,5-8] [--overwrite] [--dry-run]` that writes `<out>/<slug>/embedded/*` and `<out>/<slug>/manifest.json` and prints a summary. `--mode` values other than `embedded` exit 1 with "not implemented in Phase 1".
- Produces: `parse_pages(spec) -> set[int] | None` (1-based), `paper_slug_from_pdf(path) -> str`, `read_version() -> str` — used by later phases too.

- [ ] **Step 1: Write the failing integration tests**

File `.claude/skills/paper-pdf-figures/tests/test_extract_pdf_figures.py`:
```python
import hashlib
import io
import subprocess
import sys
from pathlib import Path

import fitz
from PIL import Image

import manifest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "extract_pdf_figures.py"


def _run(pdf_path, out_dir, *extra):
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(pdf_path), "--out", str(out_dir), *extra],
        capture_output=True, text=True,
    )


def _two_image_pdf(tmp_path):
    buf1 = io.BytesIO(); Image.new("RGB", (8, 8), "red").save(buf1, "PNG")
    buf2 = io.BytesIO(); Image.new("RGB", (9, 7), "blue").save(buf2, "PNG")
    pdf_path = tmp_path / "two.pdf"
    doc = fitz.open()
    p1 = doc.new_page(); p1.insert_image(fitz.Rect(0, 0, 80, 80), stream=buf1.getvalue())
    p2 = doc.new_page(); p2.insert_image(fitz.Rect(0, 0, 90, 70), stream=buf2.getvalue())
    doc.save(str(pdf_path)); doc.close()
    return pdf_path, buf1.getvalue(), buf2.getvalue()


def test_embedded_mode_writes_manifest_and_files(embedded_pdf, tmp_path):
    pdf_path, _ = embedded_pdf
    out = tmp_path / "out"
    r = _run(pdf_path, out, "--mode", "embedded", "--paper-slug", "paper")
    assert r.returncode == 0, r.stderr
    manifest_path = out / "paper" / "manifest.json"
    assert manifest_path.is_file()
    m = manifest.Manifest.load(manifest_path)
    assert len(m.embedded_images) == 1
    rec = m.embedded_images[0]
    saved = (out / "paper" / rec.file).read_bytes()
    assert saved[:8] == b"\x89PNG\r\n\x1a\n"              # valid PNG
    assert rec.sha256 == hashlib.sha256(saved).hexdigest()  # sha matches saved file
    assert manifest.validate(m.to_dict()) == []
    assert "embedded_images: 1" in r.stdout


def test_pages_filter_via_cli(tmp_path):
    pdf_path, _, _ = _two_image_pdf(tmp_path)
    out = tmp_path / "out"
    r = _run(pdf_path, out, "--mode", "embedded", "--paper-slug", "p", "--pages", "2")
    assert r.returncode == 0, r.stderr
    m = manifest.Manifest.load(out / "p" / "manifest.json")
    assert len(m.embedded_images) == 1
    assert m.embedded_images[0].page == 2


def test_overwrite_protection(embedded_pdf, tmp_path):
    pdf_path, _ = embedded_pdf
    out = tmp_path / "out"
    assert _run(pdf_path, out, "--paper-slug", "p").returncode == 0
    r2 = _run(pdf_path, out, "--paper-slug", "p")
    assert r2.returncode == 1
    assert "already exists" in r2.stderr


def test_overwrite_flag_replaces(embedded_pdf, tmp_path):
    pdf_path, _ = embedded_pdf
    out = tmp_path / "out"
    assert _run(pdf_path, out, "--paper-slug", "p").returncode == 0
    r2 = _run(pdf_path, out, "--paper-slug", "p", "--overwrite")
    assert r2.returncode == 0, r2.stderr


def test_unimplemented_mode_errors(embedded_pdf, tmp_path):
    pdf_path, _ = embedded_pdf
    r = _run(pdf_path, tmp_path / "out", "--mode", "detect")
    assert r.returncode == 1
    assert "not implemented in Phase 1" in r.stderr


def test_paper_slug_default_from_filename(embedded_pdf, tmp_path):
    pdf_path, _ = embedded_pdf
    out = tmp_path / "out"
    r = _run(pdf_path, out)
    assert r.returncode == 0, r.stderr
    assert (out / "fixture" / "manifest.json").is_file()


def test_overwrite_clears_stale_files(tmp_path):
    """--overwrite must remove orphan image files from a prior run."""
    import io
    from PIL import Image

    buf1 = io.BytesIO(); Image.new("RGB", (8, 8), "red").save(buf1, "PNG")
    buf2 = io.BytesIO(); Image.new("RGB", (9, 7), "blue").save(buf2, "PNG")
    pdf_path = tmp_path / "two.pdf"
    doc = fitz.open()
    p1 = doc.new_page(); p1.insert_image(fitz.Rect(0, 0, 80, 80), stream=buf1.getvalue())
    p2 = doc.new_page(); p2.insert_image(fitz.Rect(0, 0, 90, 70), stream=buf2.getvalue())
    doc.save(str(pdf_path)); doc.close()

    out = tmp_path / "out"
    assert _run(pdf_path, out, "--paper-slug", "p", "--pages", "1").returncode == 0
    embedded_dir = out / "p" / "embedded"
    assert len(list(embedded_dir.glob("*.png"))) == 1

    r2 = _run(pdf_path, out, "--paper-slug", "p", "--pages", "2", "--overwrite")
    assert r2.returncode == 0, r2.stderr
    files = list(embedded_dir.glob("*.png"))
    assert len(files) == 1, f"stale orphan files left behind: {[f.name for f in files]}"
    m = manifest.Manifest.load(out / "p" / "manifest.json")
    assert len(m.embedded_images) == 1
    assert m.embedded_images[0].page == 2


def test_validation_failure_leaves_no_manifest(embedded_pdf, tmp_path, monkeypatch):
    """If schema validation fails, no manifest.json must be written (M2)."""
    import extract_pdf_figures

    pdf_path, _ = embedded_pdf
    out = tmp_path / "out"
    monkeypatch.setattr(extract_pdf_figures, "validate", lambda d: ["fake validation error"])
    rc = extract_pdf_figures.main([str(pdf_path), "--out", str(out), "--paper-slug", "p"])
    assert rc == 1
    assert not (out / "p" / "manifest.json").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd /home/imalne/learn_vibe_coding/.claude/skills/paper-pdf-figures
pytest tests/test_extract_pdf_figures.py -v
```
Expected: FAIL (script does not exist, non-zero exit).

- [ ] **Step 3: Write `scripts/extract_pdf_figures.py`**

File `.claude/skills/paper-pdf-figures/scripts/extract_pdf_figures.py`:
```python
#!/usr/bin/env python3
"""CLI dispatcher for paper-pdf-figures (Phase 1: --mode embedded)."""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import fitz

from extract_embedded import extract_embedded_images
from manifest import Manifest, validate

VERSION_FILE = Path(__file__).resolve().parent.parent / "VERSION"


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
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    if args.mode != "embedded":
        print(f"mode '{args.mode}' is not implemented in Phase 1", file=sys.stderr)
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

    pages = parse_pages(args.pages)

    doc = fitz.open(str(pdf_path))
    try:
        records = extract_embedded_images(
            doc, out_dir, slug, pages=pages, dry_run=args.dry_run
        )
    finally:
        doc.close()

    m = Manifest(
        source_pdf=str(pdf_path),
        paper_slug=slug,
        tool_version=read_version(),
        run_args={"mode": args.mode, "pages": args.pages, "dry_run": args.dry_run},
    )
    for rec in records:
        m.add_embedded_image(rec)
    if not records:
        m.add_warning("WARN_NO_EMBEDDED_IMAGES")

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
    print(f"embedded_images: {len(records)}")
    if not args.dry_run:
        print(f"manifest: {manifest_path}")
    print(f"warnings: {[w.code for w in m.warnings]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
cd /home/imalne/learn_vibe_coding/.claude/skills/paper-pdf-figures
pytest tests/test_extract_pdf_figures.py -v
```
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
cd /home/imalne/learn_vibe_coding
git add .claude/skills/paper-pdf-figures/scripts/extract_pdf_figures.py .claude/skills/paper-pdf-figures/tests/test_extract_pdf_figures.py
git commit -m "feat(paper-pdf-figures): CLI dispatcher with --mode embedded (Phase 1)"
```

---

## Task 3: Source-PDF-unchanged guard + Phase 1 acceptance

**Files:**
- Modify: `.claude/skills/paper-pdf-figures/tests/test_extract_pdf_figures.py` (append one test)

**Interfaces:**
- No new public interface — this task adds a regression test asserting the source PDF is byte-identical after extraction (spec §2.2 "不修改原 PDF").

- [ ] **Step 1: Append the failing test**

Append to `.claude/skills/paper-pdf-figures/tests/test_extract_pdf_figures.py`:
```python
def test_source_pdf_unchanged_after_extraction(embedded_pdf, tmp_path):
    pdf_path, _ = embedded_pdf
    before = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
    r = _run(pdf_path, tmp_path / "out", "--paper-slug", "p")
    assert r.returncode == 0, r.stderr
    after = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
    assert before == after, "source PDF must not be modified"
```

- [ ] **Step 2: Run the new test to verify it passes**

Run:
```bash
cd /home/imalne/learn_vibe_coding/.claude/skills/paper-pdf-figures
pytest tests/test_extract_pdf_figures.py::test_source_pdf_unchanged_after_extraction -v
```
Expected: 1 passed.

- [ ] **Step 3: Commit**

```bash
cd /home/imalne/learn_vibe_coding
git add .claude/skills/paper-pdf-figures/tests/test_extract_pdf_figures.py
git commit -m "test(paper-pdf-figures): guard source PDF is unchanged after extraction (Phase 1)"
```

---

## Phase 1 Acceptance

After all 3 tasks, verify the Phase 1 acceptance criteria from the spec (§11 Phase 1):

- [ ] **A1: extracts embedded images.** `python3 scripts/extract_pdf_figures.py <pdf> --out /tmp/p1out --mode embedded` writes `embedded/*.png` and `manifest.json`. (Covered by `test_embedded_mode_writes_manifest_and_files`.)
- [ ] **A2: duplicate images deduped.** Same xref on two pages → one record + one file. (Covered by `test_extract_dedups_same_xref_across_pages`.)
- [ ] **A3: manifest records page, xref, width, height, format, sha256.** (Covered by `test_extract_dedups_same_xref_across_pages` + `test_extract_records_are_manifest_valid`.)
- [ ] **A4: source PDF not modified.** (Covered by `test_source_pdf_unchanged_after_extraction`.)
- [ ] **A5: full suite passes.** Run:
  ```bash
  cd /home/imalne/learn_vibe_coding/.claude/skills/paper-pdf-figures
  pip install -q -r requirements-dev.txt   # if not already installed
  pytest tests/ -v
  ```
  Expected: **34 passed** (20 from Phase 0 + 5 extract_embedded + 9 extract_pdf_figures).
- [ ] **A6: check_deps reports PyMuPDF OK.** `python3 scripts/check_deps.py` → `[OK] PyMuPDF` and exit 0 for the required-Python-dep check (exit code depends on opencv/etc., but PyMuPDF must be OK).

Phase 1 does NOT implement `manual`/`detect`/`render`/`auto` modes — those are later phases. Invoking them exits 1 with "not implemented in Phase 1".

---

## Self-Review Notes

**Spec coverage (Phase 1 scope):**
- §7.1 Function 1 (extract embedded) → Task 1 (`extract_embedded.py`) + Task 2 (dispatcher `embedded` mode).
- §9.2 naming `embedded/p{page:04d}_xref{xref:06d}.{ext}` → Task 1 (1-based page, matches manifest `page`).
- §11 Phase 1 acceptance (extract JPEG/PNG, dedup, manifest fields, PDF unchanged) → Tasks 1–3 + acceptance A1–A6.
- §2.2 不修改原 PDF → Task 3 regression test.
- Phase 1 does NOT cover: manual crop, detect, render, auto, caption, batch, packaging — those are Phase 2+.

**Placeholder scan:** none — every code step contains complete code; every command has expected output.

**Type consistency:** `extract_embedded_images(doc, out_dir, paper_slug, pages=None, dry_run=False) -> list[EmbeddedImage]` matches the Task 1 interface and the Task 2 call site. `EmbeddedImage` fields (`id, page, xref, format, width, height, file, sha256`) match Phase 0 `manifest.py` exactly. `parse_pages`, `paper_slug_from_pdf`, `read_version` are defined in Task 2 and not referenced earlier. `page` is 1-based everywhere (schema `minimum: 1`).
