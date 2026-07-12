# Paper PDF Figures — Robustness Patch (Categories 1+2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the deferred Category 1 (real-PDF robustness / error handling) and Category 2 (input validation gaps) items so every failure path produces a clean `ERROR:` message or a manifest warning instead of a Python traceback or silent misbehavior.

**Architecture:** Two tasks. Task 1 hardens the dispatcher (`extract_pdf_figures.py`): wraps `fitz.open`, centralizes `parse_pages` with error handling, sanitizes `--paper-slug`, collects warnings from the extract/crop functions, and warns on unknown formats + out-of-range pages. It also adds a backward-compatible `warnings` param to `extract_embedded_images` and `crop_figures` (plumbing only — no behavior change yet). Task 2 uses that plumbing in `extract_embedded.py` (skip bad xref + zero-dim image, append warnings) and `crop_export.py` (`pdf_doc` try/finally, skip a failed figure + clean up its partial files + warn).

**Tech Stack:** Python ≥3.9, PyMuPDF, opencv, pytest + jsonschema (all installed). 59 tests currently pass.

## Global Constraints

- Skill root: `.claude/skills/paper-pdf-figures/`; tests run from there.
- Never modify the original PDF.
- Reuse existing modules; do not duplicate. Backward compatibility: existing tests (59) must keep passing — the `warnings` param defaults to `None` and is optional.
- Warning tuples: `(code: str, page: int | None, detail: str | None)`, added to the manifest via `Manifest.add_warning(code, page, detail)`. New warning codes: `WARN_EXTRACT_IMAGE_FAILED`, `WARN_ZERO_DIMENSION_IMAGE`, `WARN_CROP_FAILED`, `WARN_UNKNOWN_FORMAT`, `WARN_PAGE_OUT_OF_RANGE`. (The schema's `warnings[]` allows any `code` string + optional `page`/`detail` — no schema change needed.)
- Clean error convention: `print(f"ERROR: ...", file=sys.stderr); return 1` — no tracebacks for user-input failures.
- `--paper-slug` must be sanitized (non-alnum/`-_` → `_`) so `--paper-slug ../../x` cannot escape `--out`.
- Offline; no network; output confined to `--out`.

---

## File Structure

| Path | Responsibility |
| --- | --- |
| `.claude/skills/paper-pdf-figures/scripts/extract_pdf_figures.py` | Task 1: harden open/parse_pages/slug + validation warnings + warnings collection |
| `.claude/skills/paper-pdf-figures/scripts/extract_embedded.py` | Task 1: add `warnings` param (plumbing); Task 2: skip bad xref + zero-dim |
| `.claude/skills/paper-pdf-figures/scripts/crop_export.py` | Task 1: add `warnings` param (plumbing); Task 2: `pdf_doc` try/finally + skip failed figure |
| `.claude/skills/paper-pdf-figures/tests/test_extract_pdf_figures.py` | Task 1: dispatcher hardening + validation tests |
| `.claude/skills/paper-pdf-figures/tests/test_extract_embedded.py` | Task 2: bad-xref + zero-dim tests (FakeDoc) |
| `.claude/skills/paper-pdf-figures/tests/test_crop_export.py` | Task 2: crop-failure test |

---

## Task 1: Dispatcher hardening + validation warnings + warnings plumbing

**Files:**
- Modify: `.claude/skills/paper-pdf-figures/scripts/extract_pdf_figures.py`
- Modify: `.claude/skills/paper-pdf-figures/scripts/extract_embedded.py` (add `warnings=None` param only)
- Modify: `.claude/skills/paper-pdf-figures/scripts/crop_export.py` (add `warnings=None` param only)
- Modify: `.claude/skills/paper-pdf-figures/tests/test_extract_pdf_figures.py` (append tests)

**Interfaces:**
- `extract_embedded.extract_embedded_images(..., warnings: list | None = None)` — optional list the function appends `(code, page, detail)` tuples to. Default `None` = no collection (backward compatible).
- `crop_export.crop_figures(..., warnings: list | None = None)` — same.
- Dispatcher collects `warnings = []`, passes to both functions, then `for w in warnings: m.add_warning(*w)`.

- [ ] **Step 1: Add `warnings` param to `extract_embedded.py` and `crop_export.py` (plumbing only)**

In `scripts/extract_embedded.py`, change the signature:
```python
def extract_embedded_images(
    doc: "fitz.Document",
    out_dir: Path | str,
    paper_slug: str,
    pages: Iterable[int] | None = None,
    dry_run: bool = False,
    warnings: list | None = None,
) -> list[EmbeddedImage]:
```
(No body change in Task 1 — the param is accepted but not yet used. Task 2 uses it.)

In `scripts/crop_export.py`, change the signature:
```python
def crop_figures(
    doc: "fitz.Document",
    figures: list[FigureConfig],
    out_dir: Path | str,
    paper_slug: str,
    dpi: int = 300,
    formats: list[str] | None = None,
    dry_run: bool = False,
    warnings: list | None = None,
) -> list[Figure]:
```
(No body change in Task 1.)

- [ ] **Step 2: Write the failing dispatcher tests**

Append to `.claude/skills/paper-pdf-figures/tests/test_extract_pdf_figures.py`:
```python
def test_missing_pdf_clean_error(tmp_path):
    r = _run(tmp_path / "nonexistent.pdf", tmp_path / "out", "--mode", "embedded")
    assert r.returncode == 1
    assert "ERROR:" in r.stderr
    assert "cannot open" in r.stderr.lower()
    assert "Traceback" not in r.stderr


def test_non_pdf_clean_error(tmp_path):
    bad = tmp_path / "not-a-pdf.pdf"
    bad.write_bytes(b"this is not a pdf")
    r = _run(bad, tmp_path / "out", "--mode", "embedded")
    assert r.returncode == 1
    assert "ERROR:" in r.stderr
    assert "Traceback" not in r.stderr


def test_bad_pages_spec_clean_error(embedded_pdf, tmp_path):
    pdf_path, _ = embedded_pdf
    r = _run(pdf_path, tmp_path / "out", "--mode", "embedded", "--pages", "abc")
    assert r.returncode == 1
    assert "ERROR:" in r.stderr
    assert "pages" in r.stderr.lower()
    assert "Traceback" not in r.stderr


def test_paper_slug_sanitized_no_path_escape(embedded_pdf, tmp_path):
    pdf_path, _ = embedded_pdf
    out = tmp_path / "out"
    r = _run(pdf_path, out, "--mode", "embedded", "--paper-slug", "../../evil")
    assert r.returncode == 0, r.stderr
    # slug must be sanitized (no "..") and stay under out
    assert ".." not in str((out / "___evil").resolve())
    assert (out / "___evil" / "manifest.json").is_file()


def test_unknown_format_warning(detect_pdf, tmp_path):
    r = _run(detect_pdf, tmp_path / "out", "--mode", "detect", "--paper-slug", "p",
             "--min-area-ratio", "0.02", "--formats", "svg,tiff")
    assert r.returncode == 0, r.stderr
    m = manifest.Manifest.load(tmp_path / "out" / "p" / "manifest.json")
    codes = [w.code for w in m.warnings]
    assert codes.count("WARN_UNKNOWN_FORMAT") == 2


def test_page_out_of_range_warning(embedded_pdf, tmp_path):
    pdf_path, _ = embedded_pdf
    r = _run(pdf_path, tmp_path / "out", "--mode", "embedded", "--paper-slug", "p",
             "--pages", "1,99")
    assert r.returncode == 0, r.stderr
    m = manifest.Manifest.load(tmp_path / "out" / "p" / "manifest.json")
    codes = [w.code for w in m.warnings]
    assert "WARN_PAGE_OUT_OF_RANGE" in codes
    assert any(w.page == 99 for w in m.warnings if w.code == "WARN_PAGE_OUT_OF_RANGE")


def test_pages_zero_clean_error(embedded_pdf, tmp_path):
    pdf_path, _ = embedded_pdf
    r = _run(pdf_path, tmp_path / "out", "--mode", "embedded", "--paper-slug", "p", "--pages", "0")
    assert r.returncode == 1
    assert "ERROR:" in r.stderr
    assert ">= 1" in r.stderr or "page" in r.stderr.lower()
    assert "Traceback" not in r.stderr


def test_pages_negative_clean_error(embedded_pdf, tmp_path):
    pdf_path, _ = embedded_pdf
    r = _run(pdf_path, tmp_path / "out", "--mode", "embedded", "--paper-slug", "p", "--pages", "1,-5")
    assert r.returncode == 1
    assert "ERROR:" in r.stderr
    assert "Traceback" not in r.stderr


def test_overwrite_missing_pdf_preserves_existing(embedded_pdf, tmp_path):
    pdf_path, _ = embedded_pdf
    out = tmp_path / "out"
    assert _run(pdf_path, out, "--paper-slug", "p").returncode == 0
    manifest_before = (out / "p" / "manifest.json").read_text()
    r = _run(tmp_path / "nonexistent.pdf", out, "--paper-slug", "p", "--overwrite")
    assert r.returncode == 1
    assert (out / "p" / "manifest.json").is_file()
    assert (out / "p" / "manifest.json").read_text() == manifest_before
```

- [ ] **Step 3: Run tests to verify they fail**

Run:
```bash
cd /home/imalne/learn_vibe_coding/.claude/skills/paper-pdf-figures
pytest tests/test_extract_pdf_figures.py -k "missing_pdf or non_pdf or bad_pages or slug_sanitized or unknown_format or out_of_range" -v
```
Expected: 6 FAIL (missing-PDF/non-PDF/bad-pages give tracebacks; slug not sanitized; no warnings).

- [ ] **Step 4: Rewrite `scripts/extract_pdf_figures.py` with hardening + warnings collection**

Replace the entire file with:
```python
#!/usr/bin/env python3
"""CLI dispatcher for paper-pdf-figures.

Phase 1: --mode embedded.  Phase 2: --mode manual.  Phase 4: --mode detect.
render / auto are not yet implemented. All user-input failures produce a clean
ERROR: line and exit 1; recoverable per-item failures become manifest warnings.
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
from figure_detect import detect_candidates, draw_candidates_preview
from manifest import Manifest, validate

VERSION_FILE = Path(__file__).resolve().parent.parent / "VERSION"
DEFAULT_FORMATS = ["pdf", "png"]
KNOWN_FORMATS = {"pdf", "png"}  # svg is Phase 3
DETECT_DPI = 100


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
        try:
            if "-" in part:
                lo_s, hi_s = part.split("-", 1)
                lo, hi = int(lo_s), int(hi_s)
            else:
                lo = hi = int(part)
        except ValueError:
            raise ValueError(f"invalid page spec '{part}'")
        if lo < 1 or hi < 1:
            raise ValueError(f"page numbers must be >= 1, got '{part}'")
        if lo > hi:
            raise ValueError(f"invalid page range '{part}' (start > end)")
        pages.update(range(lo, hi + 1))
    return pages or None


def parse_formats(spec: str | None) -> list[str]:
    if not spec:
        return list(DEFAULT_FORMATS)
    return [f.strip() for f in spec.split(",") if f.strip()]


def _sanitize_slug(s: str) -> str:
    return "".join(c if (c.isalnum() or c in "-_") else "_" for c in s)


def paper_slug_from_pdf(pdf_path: Path) -> str:
    return _sanitize_slug(pdf_path.stem)


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
    parser.add_argument("--min-area-ratio", type=float, default=0.03)
    parser.add_argument("--max-area-ratio", type=float, default=0.85)
    parser.add_argument("--merge-distance", type=float, default=20.0)
    parser.add_argument("--exclude-margins", type=float, default=30.0)
    parser.add_argument("--two-column", default="auto", choices=["auto", "true", "false"])
    args = parser.parse_args(argv)

    if args.mode not in ("embedded", "manual", "detect"):
        print(f"mode '{args.mode}' is not implemented yet", file=sys.stderr)
        return 1
    if args.mode == "manual" and not args.config:
        print("ERROR: --mode manual requires --config CONFIG.yaml", file=sys.stderr)
        return 1
    if args.dpi < 1:
        print(f"ERROR: --dpi must be >= 1, got {args.dpi}", file=sys.stderr)
        return 1
    if args.mode == "detect":
        if not (0 < args.min_area_ratio < 1) or not (0 < args.max_area_ratio <= 1):
            print("ERROR: --min-area-ratio and --max-area-ratio must be in (0, 1]",
                  file=sys.stderr)
            return 1
        if args.min_area_ratio > args.max_area_ratio:
            print(f"ERROR: --min-area-ratio ({args.min_area_ratio}) must be <= "
                  f"--max-area-ratio ({args.max_area_ratio})", file=sys.stderr)
            return 1

    # parse --pages early so malformed input is a clean error
    try:
        pages_set = parse_pages(args.pages)
    except ValueError as e:
        print(f"ERROR: invalid --pages spec '{args.pages}': {e}", file=sys.stderr)
        return 1

    pdf_path = Path(args.pdf_path)
    out_dir = Path(args.out)
    slug = _sanitize_slug(args.paper_slug) if args.paper_slug else paper_slug_from_pdf(pdf_path)
    paper_dir = out_dir / slug
    manifest_path = paper_dir / "manifest.json"

    if not args.dry_run and manifest_path.exists() and not args.overwrite:
        print(f"ERROR: {manifest_path} already exists; use --overwrite to replace",
              file=sys.stderr)
        return 1

    formats = parse_formats(args.formats)
    warnings: list[tuple[str, int | None, str | None]] = []
    if args.mode in ("manual", "detect"):
        for f in formats:
            if f not in KNOWN_FORMATS:
                warnings.append(("WARN_UNKNOWN_FORMAT", None, f"format '{f}' not supported, skipped"))

    try:
        doc = fitz.open(str(pdf_path))
    except (OSError, RuntimeError) as e:
        print(f"ERROR: cannot open PDF '{pdf_path}': {e}", file=sys.stderr)
        return 1

    # --overwrite: clear existing output only AFTER the PDF opens successfully,
    # so a bad/missing PDF cannot delete the user's prior output.
    if not args.dry_run and args.overwrite and paper_dir.exists():
        shutil.rmtree(paper_dir)

    if pages_set:
        for p in pages_set:
            if p < 1 or p > len(doc):
                warnings.append(("WARN_PAGE_OUT_OF_RANGE", p,
                                 f"page {p} out of range (1..{len(doc)}), skipped"))

    try:
        if args.mode == "embedded":
            records = extract_embedded_images(
                doc, out_dir, slug, pages=pages_set, dry_run=args.dry_run, warnings=warnings,
            )
        elif args.mode == "manual":
            try:
                figures = parse_config(args.config)
                records = crop_figures(
                    doc, figures, out_dir, slug,
                    dpi=args.dpi, formats=formats, dry_run=args.dry_run, warnings=warnings,
                )
            except (OSError, yaml.YAMLError, ValueError, KeyError) as e:
                print(f"ERROR: {e}", file=sys.stderr)
                return 1
        else:  # detect
            indices = (sorted(p - 1 for p in pages_set) if pages_set is not None
                       else list(range(len(doc))))
            candidates_dir = paper_dir / "candidates"
            if not args.dry_run:
                candidates_dir.mkdir(parents=True, exist_ok=True)
            import json
            records = []
            pages_with_hits = 0
            for pno in indices:
                if pno < 0 or pno >= len(doc):
                    continue
                hits = detect_candidates(
                    pno + 1, doc[pno], dpi=DETECT_DPI,
                    min_area_ratio=args.min_area_ratio,
                    max_area_ratio=args.max_area_ratio,
                    merge_distance=args.merge_distance,
                    exclude_margins=args.exclude_margins,
                )
                if hits:
                    pages_with_hits += 1
                records.extend(hits)
                if not args.dry_run:
                    png = draw_candidates_preview(doc[pno], hits, dpi=DETECT_DPI)
                    (candidates_dir / f"page_{pno + 1:04d}_candidates.png").write_bytes(png)
            if not args.dry_run:
                (candidates_dir / "candidates.json").write_text(
                    json.dumps({"candidates": [
                        {"page": c.page, "bbox_pdf_points": c.bbox_pdf_points,
                         "score": c.score}
                        for c in records
                    ]}, indent=2, ensure_ascii=False)
                )
    finally:
        doc.close()

    m = Manifest(
        source_pdf=str(pdf_path),
        paper_slug=slug,
        tool_version=read_version(),
        run_args={
            "mode": args.mode, "pages": args.pages, "config": args.config,
            "dpi": args.dpi, "formats": args.formats, "dry_run": args.dry_run,
            "min_area_ratio": args.min_area_ratio, "max_area_ratio": args.max_area_ratio,
            "merge_distance": args.merge_distance, "exclude_margins": args.exclude_margins,
            "two_column": args.two_column,
        },
    )
    if args.mode == "embedded":
        for rec in records:
            m.add_embedded_image(rec)
        if not records:
            m.add_warning("WARN_NO_EMBEDDED_IMAGES")
    elif args.mode == "manual":
        for rec in records:
            m.add_figure(rec)
        if not records:
            m.add_warning("WARN_NO_FIGURES")
    else:  # detect
        for rec in records:
            m.add_candidate(rec)
        if not records:
            m.add_warning("WARN_NO_FIGURE_CANDIDATES")

    for code, page, detail in warnings:
        m.add_warning(code, page, detail)

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
    elif args.mode == "manual":
        print(f"figures: {len(records)}")
    else:  # detect
        print(f"candidates: {len(records)} across {pages_with_hits} pages")
    if not args.dry_run:
        print(f"manifest: {manifest_path}")
    print(f"warnings: {[w.code for w in m.warnings]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run tests to verify they pass**

Run:
```bash
cd /home/imalne/learn_vibe_coding/.claude/skills/paper-pdf-figures
pytest tests/test_extract_pdf_figures.py -v
pytest tests/ -q
```
Expected: all dispatcher tests pass (18 prior + 6 new = 24 in the file); full suite 65 passed (was 59; +6). The binding check is "all green, no regressions".

- [ ] **Step 6: Commit**

```bash
cd /home/imalne/learn_vibe_coding
git add .claude/skills/paper-pdf-figures/scripts/extract_pdf_figures.py .claude/skills/paper-pdf-figures/scripts/extract_embedded.py .claude/skills/paper-pdf-figures/scripts/crop_export.py .claude/skills/paper-pdf-figures/tests/test_extract_pdf_figures.py
git commit -m "fix(paper-pdf-figures): clean errors for bad PDF/pages/slug + format/page warnings (robustness Task 1)"
```

---

## Task 2: Extraction + crop robustness (use warnings plumbing)

**Files:**
- Modify: `.claude/skills/paper-pdf-figures/scripts/extract_embedded.py` (skip bad xref + zero-dim, append warnings)
- Modify: `.claude/skills/paper-pdf-figures/scripts/crop_export.py` (`pdf_doc` try/finally, skip failed figure + cleanup)
- Modify: `.claude/skills/paper-pdf-figures/tests/test_extract_embedded.py` (append FakeDoc tests)
- Modify: `.claude/skills/paper-pdf-figures/tests/test_crop_export.py` (append crop-failure test)

**Interfaces:**
- `extract_embedded.extract_embedded_images(..., warnings=None)`: on `doc.extract_image(xref)` exception → append `("WARN_EXTRACT_IMAGE_FAILED", page, detail)` and skip; on `width<1 or height<1` → append `("WARN_ZERO_DIMENSION_IMAGE", page, detail)` and skip. Other xrefs continue.
- `crop_export.crop_figures(..., warnings=None)`: wrap per-figure `pdf_doc` in `try/finally` (always close); on `show_pdf_page`/`get_pixmap`/`tobytes` exception → remove that figure's partial directory (if created), append `("WARN_CROP_FAILED", page, detail)`, skip (continue to next figure). Duplicate-id and out-of-range-page still raise `ValueError` (config errors, caught by dispatcher).

- [ ] **Step 1: Write the failing tests**

Append to `.claude/skills/paper-pdf-figures/tests/test_extract_embedded.py`:
```python
class _FakePage:
    def __init__(self, images):
        self._images = images

    def get_images(self, full=True):
        return self._images


class _FakeDoc:
    """Mimics the fitz.Document interface extract_embedded_images uses."""
    def __init__(self, pages, extract):
        self._pages = pages          # list of lists of (xref,) tuples
        self._extract = extract      # dict xref -> dict | Exception

    def __len__(self):
        return len(self._pages)

    def __getitem__(self, i):
        return _FakePage(self._pages[i])

    def extract_image(self, xref):
        r = self._extract.get(xref)
        if isinstance(r, Exception):
            raise r
        return r


def test_extract_skips_bad_xref_with_warning(tmp_path):
    fake = _FakeDoc(
        pages=[[(1,), (2,), (3,)]],
        extract={
            1: {"ext": "png", "image": b"\x89PNG\r\n\x1a\n", "width": 10, "height": 10},
            2: RuntimeError("corrupt xref"),
            3: {"ext": "png", "image": b"\x89PNG\r\n\x1a\n", "width": 5, "height": 5},
        },
    )
    warnings = []
    results = extract_embedded.extract_embedded_images(
        fake, tmp_path / "out", "p", warnings=warnings)
    assert len(results) == 2                       # xref 2 skipped
    assert {r.xref for r in results} == {1, 3}
    assert any(w[0] == "WARN_EXTRACT_IMAGE_FAILED" and w[1] == 1 for w in warnings)


def test_extract_skips_zero_dimension_with_warning(tmp_path):
    fake = _FakeDoc(
        pages=[[(10,)]],
        extract={10: {"ext": "png", "image": b"\x89PNG\r\n\x1a\n", "width": 0, "height": 0}},
    )
    warnings = []
    results = extract_embedded.extract_embedded_images(
        fake, tmp_path / "out", "p", warnings=warnings)
    assert results == []
    assert any(w[0] == "WARN_ZERO_DIMENSION_IMAGE" for w in warnings)
```

Append to `.claude/skills/paper-pdf-figures/tests/test_crop_export.py`:
```python
def test_crop_skips_failed_figure_and_cleans_stale_dir(vector_pdf, tmp_path):
    """A failed crop must skip the figure, warn, and remove any stale dir for it.

    Pre-creates fig_bad/ with a sentinel file to exercise the rmtree cleanup
    (the dir is otherwise created only after a successful crop).
    """
    doc = fitz.open(str(vector_pdf))
    figs_dir = tmp_path / "out" / "p" / "figures"
    fig_bad_dir = figs_dir / "fig_bad"
    fig_bad_dir.mkdir(parents=True, exist_ok=True)
    (fig_bad_dir / "stale.pdf").write_bytes(b"stale")

    figs = [
        crop_export.FigureConfig(id="fig_ok", page=1, bbox=[60, 60, 210, 210]),
        crop_export.FigureConfig(id="fig_bad", page=1, bbox=[300, 300, 100, 100]),
    ]
    warnings = []
    results = crop_export.crop_figures(doc, figs, tmp_path / "out", "p", warnings=warnings)
    assert len(results) == 1
    assert results[0].id == "fig_ok"
    assert any(w[0] == "WARN_CROP_FAILED" for w in warnings)
    assert not fig_bad_dir.exists(), "stale fig_bad dir must be cleaned up"
    assert (figs_dir / "fig_ok" / "fig_ok.pdf").is_file()
    doc.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd /home/imalne/learn_vibe_coding/.claude/skills/paper-pdf-figures
pytest tests/test_extract_embedded.py -k "bad_xref or zero_dimension" -v
pytest tests/test_crop_export.py -k "failed_figure" -v
```
Expected: FAIL (extract_embedded raises on bad xref / doesn't warn; crop_export raises on inverted bbox instead of skipping).

- [ ] **Step 3: Update `extract_embedded.py` — skip bad xref + zero-dim**

In `scripts/extract_embedded.py`, inside the per-image loop, replace the extraction block. The current block is:
```python
            info = doc.extract_image(xref)
            ext = info.get("ext", "bin")
            image_bytes = info["image"]
            width = int(info.get("width", 0))
            height = int(info.get("height", 0))
```
Replace with:
```python
            try:
                info = doc.extract_image(xref)
            except Exception as e:
                if warnings is not None:
                    warnings.append(("WARN_EXTRACT_IMAGE_FAILED", page_1based,
                                     f"xref {xref}: {e}"))
                continue
            ext = info.get("ext", "bin")
            image_bytes = info["image"]
            width = int(info.get("width", 0))
            height = int(info.get("height", 0))
            if width < 1 or height < 1:
                if warnings is not None:
                    warnings.append(("WARN_ZERO_DIMENSION_IMAGE", page_1based,
                                     f"xref {xref}: {width}x{height}"))
                continue
```
(Leave the rest of the loop — sha, file write, `EmbeddedImage` construction — unchanged. `page_1based` is already computed later in the loop; if it's computed after this block, move its computation above the `try`.)

**Note:** verify `page_1based` is defined before the `try`. In the current code it's computed as `page_1based = pno + 1` later in the loop — move that line to just before the `try` block.

- [ ] **Step 4: Update `crop_export.py` — `pdf_doc` try/finally + skip failed figure**

In `scripts/crop_export.py`, replace the per-figure body. The current body is:
```python
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
        if not dry_run:
            fig_dir = figs_dir / fig.id
            fig_dir.mkdir(parents=True, exist_ok=True)
            ...
```
Replace with:
```python
        clip = fitz.Rect(*fig.bbox)
        fig_dir = figs_dir / fig.id if not dry_run else None
        try:
            pdf_doc = fitz.open()
            try:
                p = pdf_doc.new_page(width=clip.width, height=clip.height)
                p.show_pdf_page(p.rect, doc, fig.page - 1, clip=clip)
                pdf_bytes = pdf_doc.tobytes()
                png_bytes = p.get_pixmap(dpi=dpi).tobytes("png")
            finally:
                pdf_doc.close()
        except Exception as e:
            if warnings is not None:
                warnings.append(("WARN_CROP_FAILED", fig.page, f"{fig.id}: {e}"))
            if fig_dir is not None and fig_dir.exists():
                shutil.rmtree(fig_dir)
            continue

        files = {"pdf": None, "png": None, "svg": None}
        sha: dict[str, str] = {}
        if not dry_run:
            fig_dir.mkdir(parents=True, exist_ok=True)
            ...
```
(Add `import shutil` at the top of `crop_export.py` if not present. The `fig_dir` is computed before the try so the except can clean it up. The rest of the loop — file writes + `Figure` construction — is unchanged.)

- [ ] **Step 5: Run tests to verify they pass**

Run:
```bash
cd /home/imalne/learn_vibe_coding/.claude/skills/paper-pdf-figures
pytest tests/test_extract_embedded.py -v
pytest tests/test_crop_export.py -v
pytest tests/ -q
```
Expected: all extract/crop tests pass; full suite 68 passed (was 65 after Task 1; +3 new). Binding check: "all green, no regressions".

- [ ] **Step 6: Commit**

```bash
cd /home/imalne/learn_vibe_coding
git add .claude/skills/paper-pdf-figures/scripts/extract_embedded.py .claude/skills/paper-pdf-figures/scripts/crop_export.py .claude/skills/paper-pdf-figures/tests/test_extract_embedded.py .claude/skills/paper-pdf-figures/tests/test_crop_export.py
git commit -m "fix(paper-pdf-figures): skip bad xref/zero-dim/failed-crop with warnings (robustness Task 2)"
```

---

## Self-Review Notes

**Coverage (Category 1 + 2 items):**
- `fitz.open` missing/non-PDF → clean ERROR (Task 1). ✓
- `extract_image` corrupt xref → skip + WARN_EXTRACT_IMAGE_FAILED (Task 2). ✓
- `parse_pages` malformed → clean ERROR (Task 1). ✓
- `--paper-slug` sanitize → no path escape (Task 1). ✓
- partial-failure orphans → failed figure's dir cleaned (Task 2). ✓
- `pdf_doc` try/finally → no leak (Task 2). ✓
- `width`/`height=0` → skip + WARN_ZERO_DIMENSION_IMAGE (Task 2). ✓
- unknown `--formats` → WARN_UNKNOWN_FORMAT (Task 1). ✓
- invalid `--pages` → WARN_PAGE_OUT_OF_RANGE (Task 1). ✓

**Not covered (intentionally, Category 3-5):** `--two-column` wiring (feature, Phase 3+), dead config fields, `parse_formats` unconditional computation, date-time FormatChecker, dead `ALL_MODES`, etc. — non-blocking, deferred.

**Backward compatibility:** `warnings` param defaults to `None`; existing tests that don't pass it are unaffected. The dispatcher's embedded/manual/detect behavior is unchanged on the happy path (verified by the 59 existing tests still passing).

**Type consistency:** warning tuples `(code, page, detail)` match `Manifest.add_warning(code, page=None, detail=None)`. New codes are strings (schema allows any). `pages_set` is now computed once and passed to both embedded and detect (previously each branch called `parse_pages`).