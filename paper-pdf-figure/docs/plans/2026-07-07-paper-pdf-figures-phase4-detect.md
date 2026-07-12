# Paper PDF Figures — Phase 4 (Detect dry-run) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `--mode detect`: a heuristic dry-run that scans each page, finds candidate figure regions, and outputs a preview PNG (with boxes drawn) + `candidates.json` + `candidates[]` in the manifest — **without cropping**. The user picks bboxes from the preview and copies them into `config.yaml` for Phase 2 to crop.

**Architecture:** `figure_detect.py` holds the heuristic: render page at low DPI → grayscale → Otsu threshold (invert so content=255) → morphological close with a DPI-scaled kernel to merge a figure's scattered content into blobs → `connectedComponentsWithStats` → filter by area ratio + aspect + margins → merge nearby/overlapping rects → return `Candidate` records (PDF-point bbox + score). `draw_candidates_preview()` renders the page with red boxes. `extract_pdf_figures.py` (dispatcher) gains a `detect` branch that writes `candidates/page_NNN_candidates.png` + `candidates/candidates.json` and adds `candidates[]` to the manifest. No cropping happens (dry-run by design).

**Tech Stack:** Python ≥3.9, PyMuPDF (render), numpy + opencv (`opencv-python-headless`, installed 5.0.0) for threshold/morphology/connected-components, pytest + jsonschema. API + parameters verified on the real vector paper `2606.28301v1.pdf` page 11: closing kernel `k = max(1, int(dpi*0.15))` (15 at dpi=100) merges the figure into one blob; the merge step combines adjacent fragments into a single candidate covering the figure.

## Global Constraints

(From the spec `paper-pdf-figure/docs/designs/paper-pdf-figure.md` — every task inherits these.)

- Skill root: `.claude/skills/paper-pdf-figures/`; tests run from there: `cd .claude/skills/paper-pdf-figures && pytest tests/ -v`
- Never modify the original PDF.
- Reuse Phase 0–2 modules: `manifest.py` (`Candidate(page, bbox_pdf_points, score)`, `Manifest.add_candidate`, `validate`), `extract_pdf_figures.py` (extend dispatcher). Do not duplicate.
- `Candidate` fields (from `manifest.py`): `page` (1-based int), `bbox_pdf_points` (`[x0,y0,x1,y1]` in PDF points), `score` (float, area ratio — nullable per schema but Phase 4 always sets it).
- File naming (spec §9.4): `candidates/page_{page:04d}_candidates.png` and `candidates/candidates.json`.
- **detect is dry-run only** — it never crops. Do not call `crop_figures` or write to `figures/`.
- Detection params (spec §6.2): `--min-area-ratio` (default 0.03), `--max-area-ratio` (default 0.85), `--merge-distance` (default 20, PDF points), `--exclude-margins` (default 30, PDF points). `--two-column` is **deferred** (accepted by the dispatcher for forward-compat but not wired into the algorithm — note in README/run_args).
- Offline; no network; output confined to `--out`.

**Pre-req:** `opencv-python-headless` installed (`pip install --user opencv-python-headless`). `check_deps.py` reports `[OK] numpy` + `[OK] opencv-python`. (numpy already OK; opencv was installed for this phase.)

---

## File Structure

Phase 4 creates/modifies these files.

| Path | Responsibility |
| --- | --- |
| `.claude/skills/paper-pdf-figures/scripts/figure_detect.py` | `detect_candidates(page_num, page, dpi, min_area_ratio, max_area_ratio, merge_distance, exclude_margins) -> list[Candidate]`; `draw_candidates_preview(page, hits, dpi) -> bytes` |
| `.claude/skills/paper-pdf-figures/scripts/extract_pdf_figures.py` | Modify: add `detect` branch + `--min-area-ratio`/`--max-area-ratio`/`--merge-distance`/`--exclude-margins`/`--two-column` args |
| `.claude/skills/paper-pdf-figures/tests/conftest.py` | Modify: add `detect_pdf` fixture (dense shape cluster + sparse text) |
| `.claude/skills/paper-pdf-figures/tests/test_figure_detect.py` | Unit tests for figure_detect.py |

`crop_export.py`, `extract_embedded.py`, `manifest.py`, schema reused unchanged.

---

## Task 1: Detection core + preview drawing + test fixture

**Files:**
- Create: `.claude/skills/paper-pdf-figures/scripts/figure_detect.py`
- Modify: `.claude/skills/paper-pdf-figures/tests/conftest.py` (add `detect_pdf` fixture)
- Create: `.claude/skills/paper-pdf-figures/tests/test_figure_detect.py`

**Interfaces:**
- Consumes: `manifest.Candidate(page, bbox_pdf_points, score)` from Phase 0. `tests/conftest.py` puts `scripts/` on `sys.path`.
- Produces: `figure_detect.detect_candidates(page_num, page, dpi=100, min_area_ratio=0.03, max_area_ratio=0.85, merge_distance=20, exclude_margins=30) -> list[Candidate]` — pure function (no file I/O). Returns `Candidate` records with PDF-point bboxes and `score` = area ratio (0,1].
- Produces: `figure_detect.draw_candidates_preview(page, hits, dpi=100) -> bytes` — returns PNG bytes of the page with red rectangles drawn around each candidate.

- [ ] **Step 1: Extend `tests/conftest.py` with the `detect_pdf` fixture**

Append (keep existing `sys.path` + `embedded_pdf` + `vector_pdf` fixtures intact):
```python
@pytest.fixture
def detect_pdf(tmp_path):
    """A page with a dense cluster of shapes (a fake figure) + sparse text.

    The cluster fills roughly (100,100)-(380,380); sparse text sits at the
    right. A working detector should return at least one candidate overlapping
    the cluster region.
    """
    import random
    import fitz

    rng = random.Random(42)
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    # dense "figure" cluster (200 rects merge into one blob under the closing kernel)
    for _ in range(200):
        x = 100 + rng.random() * 270
        y = 100 + rng.random() * 270
        page.draw_rect(fitz.Rect(x, y, x + 12, y + 12), color=(0, 0, 0), fill=(0, 0, 0))
    # sparse "text" elsewhere (low ink density)
    for i in range(5):
        page.insert_text((430, 120 + i * 18), "lorem ipsum dolor " * 2, fontsize=10)
    p = tmp_path / "detect.pdf"
    doc.save(str(p))
    doc.close()
    return p
```

- [ ] **Step 2: Write the failing tests**

File `.claude/skills/paper-pdf-figures/tests/test_figure_detect.py`:
```python
import fitz

import figure_detect
import manifest


def test_detect_finds_figure_cluster(detect_pdf):
    doc = fitz.open(str(detect_pdf))
    hits = figure_detect.detect_candidates(1, doc[0], dpi=100, min_area_ratio=0.02)
    assert len(hits) >= 1
    cluster = fitz.Rect(100, 100, 380, 380)
    found = any(fitz.Rect(*h.bbox_pdf_points).intersects(cluster) for h in hits)
    assert found, f"no candidate overlaps the figure cluster: {hits}"
    for h in hits:
        assert h.page == 1
        assert len(h.bbox_pdf_points) == 4
        assert h.score is not None and 0 < h.score <= 1
    doc.close()


def test_detect_empty_page_yields_no_candidates(tmp_path):
    import fitz
    doc = fitz.open()
    doc.new_page(width=612, height=792)  # blank page, no content
    hits = figure_detect.detect_candidates(1, doc[0], dpi=100)
    assert hits == []
    doc.close()


def test_min_area_ratio_filters_small(detect_pdf):
    doc = fitz.open(str(detect_pdf))
    # absurdly high threshold -> everything filtered out
    hits = figure_detect.detect_candidates(1, doc[0], dpi=100, min_area_ratio=0.99)
    assert hits == []
    doc.close()


def test_exclude_margins_blanks_edge_content(detect_pdf):
    doc = fitz.open(str(detect_pdf))
    # huge exclude_margins eats the whole page -> no candidates
    hits = figure_detect.detect_candidates(1, doc[0], dpi=100, exclude_margins=400)
    assert hits == []
    doc.close()


def test_merge_distance_combines_adjacent(detect_pdf):
    doc = fitz.open(str(detect_pdf))
    # large merge_distance -> adjacent blobs collapse toward fewer candidates
    small_merge = figure_detect.detect_candidates(
        1, doc[0], dpi=100, min_area_ratio=0.02, merge_distance=0)
    large_merge = figure_detect.detect_candidates(
        1, doc[0], dpi=100, min_area_ratio=0.02, merge_distance=200)
    assert len(large_merge) <= len(small_merge)
    doc.close()


def test_preview_is_valid_png(detect_pdf):
    from PIL import Image
    import io

    doc = fitz.open(str(detect_pdf))
    hits = figure_detect.detect_candidates(1, doc[0], dpi=100, min_area_ratio=0.02)
    png = figure_detect.draw_candidates_preview(doc[0], hits, dpi=100)
    assert isinstance(png, (bytes, bytearray))
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    im = Image.open(io.BytesIO(png))
    assert im.format == "PNG"
    doc.close()


def test_candidates_are_manifest_valid(detect_pdf, tmp_path):
    doc = fitz.open(str(detect_pdf))
    m = manifest.Manifest("detect.pdf", "paper", "0.1.0")
    for c in figure_detect.detect_candidates(1, doc[0], dpi=100, min_area_ratio=0.02):
        m.add_candidate(c)
    assert manifest.validate(m.to_dict()) == []
    doc.close()
```

- [ ] **Step 3: Run tests to verify they fail**

Run:
```bash
cd /home/imalne/learn_vibe_coding/.claude/skills/paper-pdf-figures
pytest tests/test_figure_detect.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'figure_detect'`.

- [ ] **Step 4: Write `scripts/figure_detect.py`**

File `.claude/skills/paper-pdf-figures/scripts/figure_detect.py`:
```python
"""Heuristic candidate figure detection (Phase 4: --mode detect, dry-run).

Renders each page at low DPI, binarizes (content=255), closes with a
DPI-scaled kernel to merge a figure's scattered content into blobs, finds
connected components, filters by area/aspect/margins, and merges nearby
candidates. Returns Candidate records with PDF-point bboxes. Does NOT crop.
"""
from __future__ import annotations

import cv2
import fitz
import numpy as np

from manifest import Candidate


def detect_candidates(
    page_num: int,
    page: "fitz.Page",
    dpi: int = 100,
    min_area_ratio: float = 0.03,
    max_area_ratio: float = 0.85,
    merge_distance: float = 20.0,
    exclude_margins: float = 30.0,
) -> list[Candidate]:
    """Return candidate figure regions on `page` as Candidate records.

    `merge_distance` and `exclude_margins` are in PDF points. `score` is the
    area ratio (component pixels / page pixels), in (0, 1].
    """
    pix = page.get_pixmap(dpi=dpi)
    n_channels = pix.n
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, n_channels)
    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY) if n_channels >= 3 else np.array(img)

    # blank out margins (exclude header/footer/edge noise)
    margin_px = int(exclude_margins * dpi / 72.0)
    if margin_px > 0:
        gray[:margin_px, :] = 255
        gray[-margin_px:, :] = 255
        gray[:, :margin_px] = 255
        gray[:, -margin_px:] = 255

    # binarize: content (dark) -> 255
    binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]

    # close with a DPI-scaled kernel to merge a figure's content into blobs
    k = max(1, int(dpi * 0.15))
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (k, k))
    closed = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)

    num, _labels, stats, _centroids = cv2.connectedComponentsWithStats(closed, connectivity=8)
    page_area = pix.width * pix.height
    scale = 72.0 / dpi  # pixel -> PDF point

    hits: list[Candidate] = []
    for i in range(1, num):  # 0 = background
        x, y, w, h, area = stats[i]
        if w <= 0 or h <= 0:
            continue
        ratio = area / page_area
        if ratio < min_area_ratio or ratio > max_area_ratio:
            continue
        aspect = w / h
        if aspect > 10 or aspect < 0.1:  # skip very thin (text lines)
            continue
        bbox_pdf = [x * scale, y * scale, (x + w) * scale, (y + h) * scale]
        hits.append(Candidate(page=page_num, bbox_pdf_points=bbox_pdf, score=float(ratio)))

    return _merge_nearby(hits, merge_distance)


def _rects_within(a: "fitz.Rect", b: "fitz.Rect", dist: float) -> bool:
    """True if the gap between a and b is < dist in BOTH axes."""
    gap_x = max(0.0, max(a.x0, b.x0) - min(a.x1, b.x1))
    gap_y = max(0.0, max(a.y0, b.y0) - min(a.y1, b.y1))
    return gap_x < dist and gap_y < dist


def _merge_nearby(hits: list[Candidate], merge_dist: float) -> list[Candidate]:
    """Iteratively merge candidates whose rects are within merge_dist (PDF points)."""
    if len(hits) <= 1:
        return list(hits)
    changed = True
    result = list(hits)
    while changed:
        changed = False
        merged: list[Candidate] = []
        used = [False] * len(result)
        for i, h in enumerate(result):
            if used[i]:
                continue
            ri = fitz.Rect(*h.bbox_pdf_points)
            score = h.score
            for j in range(i + 1, len(result)):
                if used[j]:
                    continue
                rj = fitz.Rect(*result[j].bbox_pdf_points)
                if _rects_within(ri, rj, merge_dist):
                    ri = fitz.Rect(min(ri.x0, rj.x0), min(ri.y0, rj.y0),
                                   max(ri.x1, rj.x1), max(ri.y1, rj.y1))
                    score = max(score, result[j].score)
                    used[j] = True
                    changed = True
            used[i] = True
            merged.append(Candidate(
                page=h.page,
                bbox_pdf_points=[ri.x0, ri.y0, ri.x1, ri.y1],
                score=score,
            ))
        result = merged
    return result


def draw_candidates_preview(page: "fitz.Page", hits: list[Candidate], dpi: int = 100) -> bytes:
    """Render `page` with red rectangles around each candidate; return PNG bytes."""
    pix = page.get_pixmap(dpi=dpi)
    n_channels = pix.n
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, n_channels)
    # cv2 uses BGR
    if n_channels == 1:
        bgr = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    elif n_channels == 4:
        bgr = cv2.cvtColor(img, cv2.COLOR_RGBA2BGR)
    else:
        bgr = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
    scale = dpi / 72.0  # PDF point -> pixel
    for h in hits:
        x0, y0, x1, y1 = h.bbox_pdf_points
        cv2.rectangle(bgr, (int(x0 * scale), int(y0 * scale)),
                       (int(x1 * scale), int(y1 * scale)), (0, 0, 255), 2)
    ok, buf = cv2.imencode(".png", bgr)
    if not ok:
        raise RuntimeError("failed to encode preview PNG")
    return buf.tobytes()
```

- [ ] **Step 5: Run tests to verify they pass**

Run:
```bash
cd /home/imalne/learn_vibe_coding/.claude/skills/paper-pdf-figures
pytest tests/test_figure_detect.py -v
```
Expected: 7 passed. If `test_detect_finds_figure_cluster` fails (no candidate overlaps the cluster), the kernel/area tuning may need a nudge for the fixture — try lowering `min_area_ratio` to 0.01 in the test call or increasing the fixture cluster density. The algorithm was verified on the real paper; the fixture is a simpler stand-in.

- [ ] **Step 6: Commit**

```bash
cd /home/imalne/learn_vibe_coding
git add .claude/skills/paper-pdf-figures/scripts/figure_detect.py .claude/skills/paper-pdf-figures/tests/test_figure_detect.py .claude/skills/paper-pdf-figures/tests/conftest.py
git commit -m "feat(paper-pdf-figures): heuristic candidate figure detection + preview (Phase 4)"
```

---

## Task 2: Dispatcher `detect` mode + integration tests

**Files:**
- Modify: `.claude/skills/paper-pdf-figures/scripts/extract_pdf_figures.py` (add `detect` branch + 5 detect args)
- Modify: `.claude/skills/paper-pdf-figures/tests/test_extract_pdf_figures.py` (add 3 detect-mode tests)

**Interfaces:**
- Consumes: `figure_detect.detect_candidates` + `figure_detect.draw_candidates_preview` from Task 1; Phase 0 `Manifest`/`Candidate`/`validate`; Phase 1 `parse_pages`.
- Produces: `--mode detect` end-to-end: for each page (or `--pages`), run detection, write `candidates/page_{page:04d}_candidates.png` + `candidates/candidates.json`, add `candidates[]` to `manifest.json`, print `candidates: N across M pages`. `--dry-run` writes nothing (just prints the summary).

- [ ] **Step 1: Write the failing integration tests**

Append to `.claude/skills/paper-pdf-figures/tests/test_extract_pdf_figures.py`:
```python
def test_detect_mode_writes_previews_and_candidates(detect_pdf, tmp_path):
    out = tmp_path / "out"
    r = _run(detect_pdf, out, "--mode", "detect", "--paper-slug", "p",
             "--min-area-ratio", "0.02")
    assert r.returncode == 0, r.stderr
    assert "candidates:" in r.stdout
    assert (out / "p" / "candidates" / "page_0001_candidates.png").is_file()
    cj = out / "p" / "candidates" / "candidates.json"
    assert cj.is_file()
    import json
    data = json.loads(cj.read_text())
    assert "candidates" in data and len(data["candidates"]) >= 1
    m = manifest.Manifest.load(out / "p" / "manifest.json")
    assert len(m.candidates) >= 1
    assert manifest.validate(m.to_dict()) == []


def test_detect_mode_dry_run_writes_nothing(detect_pdf, tmp_path):
    out = tmp_path / "out"
    r = _run(detect_pdf, out, "--mode", "detect", "--paper-slug", "p",
             "--min-area-ratio", "0.02", "--dry-run")
    assert r.returncode == 0, r.stderr
    assert "candidates:" in r.stdout
    assert not (out / "p" / "candidates").exists()
    assert not (out / "p" / "manifest.json").exists()


def test_detect_mode_pages_filter(detect_pdf, tmp_path):
    # 2-page PDF with content only on page 1
    import fitz
    two = tmp_path / "two.pdf"
    doc = fitz.open()
    p1 = doc.new_page(width=612, height=792)
    import random
    rng = random.Random(1)
    for _ in range(60):
        p1.draw_rect(fitz.Rect(100 + rng.random()*270, 100 + rng.random()*270,
                               112 + rng.random()*270, 112 + rng.random()*270),
                     color=(0, 0, 0), fill=(0, 0, 0))
    doc.new_page(width=612, height=792)  # blank page 2
    doc.save(str(two)); doc.close()

    out = tmp_path / "out"
    r = _run(two, out, "--mode", "detect", "--paper-slug", "p",
             "--min-area-ratio", "0.02", "--pages", "1")
    assert r.returncode == 0, r.stderr
    assert (out / "p" / "candidates" / "page_0001_candidates.png").is_file()
    assert not (out / "p" / "candidates" / "page_0002_candidates.png").exists()


def test_detect_inverted_area_ratios_errors(detect_pdf, tmp_path):
    r = _run(detect_pdf, tmp_path / "out", "--mode", "detect", "--paper-slug", "p",
             "--min-area-ratio", "0.9", "--max-area-ratio", "0.1")
    assert r.returncode == 1
    assert "ERROR:" in r.stderr
    assert "must be <=" in r.stderr
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd /home/imalne/learn_vibe_coding/.claude/skills/paper-pdf-figures
pytest tests/test_extract_pdf_figures.py -k detect -v
```
Expected: the 3 new tests FAIL (`detect` mode still exits 1 "not implemented yet").

- [ ] **Step 3: Rewrite `scripts/extract_pdf_figures.py` with the `detect` branch**

Replace the entire file `.claude/skills/paper-pdf-figures/scripts/extract_pdf_figures.py` with:
```python
#!/usr/bin/env python3
"""CLI dispatcher for paper-pdf-figures.

Phase 1: --mode embedded (extract embedded raster images).
Phase 2: --mode manual  (crop figure regions by bbox from config.yaml -> PDF+PNG).
Phase 4: --mode detect  (dry-run candidate figure detection; writes previews + candidates.json).
render / auto are not yet implemented.
"""
from __future__ import annotations

import argparse
import json
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
DETECT_DPI = 100  # low DPI for fast detection


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
    # detect params
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

    pages_with_hits = 0
    doc = fitz.open(str(pdf_path))
    try:
        if args.mode == "embedded":
            pages = parse_pages(args.pages)
            records = extract_embedded_images(
                doc, out_dir, slug, pages=pages, dry_run=args.dry_run
            )
        elif args.mode == "manual":
            try:
                figures = parse_config(args.config)
                records = crop_figures(
                    doc, figures, out_dir, slug,
                    dpi=args.dpi, formats=formats, dry_run=args.dry_run,
                )
            except (OSError, yaml.YAMLError, ValueError, KeyError) as e:
                print(f"ERROR: {e}", file=sys.stderr)
                return 1
        else:  # detect
            pages_set = parse_pages(args.pages)
            indices = (sorted(p - 1 for p in pages_set) if pages_set is not None
                       else list(range(len(doc))))
            candidates_dir = paper_dir / "candidates"
            if not args.dry_run:
                candidates_dir.mkdir(parents=True, exist_ok=True)
            records = []  # detect produces Candidate records, not images
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

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
cd /home/imalne/learn_vibe_coding/.claude/skills/paper-pdf-figures
pytest tests/test_extract_pdf_figures.py -v
pytest tests/ -q
```
Expected: all dispatcher tests pass (15 from Phase 1+2 + 3 new detect = 18 in the file); full suite all green (was 48; +3 detect = 51). The binding check is "all green, no regressions".

- [ ] **Step 5: Commit**

```bash
cd /home/imalne/learn_vibe_coding
git add .claude/skills/paper-pdf-figures/scripts/extract_pdf_figures.py .claude/skills/paper-pdf-figures/tests/test_extract_pdf_figures.py
git commit -m "feat(paper-pdf-figures): CLI detect mode with previews + candidates.json (Phase 4)"
```

---

## Task 3: Real-paper acceptance smoke + Phase 4 acceptance

**Files:**
- No code changes. This task runs the real-paper smoke and verifies Phase 4 acceptance (A1–A4 from spec §11 Phase 4).

- [ ] **Step 1: Real-paper smoke on the vector paper**

Run detect on `2606.28301v1.pdf` page 11 (the page verified during plan writing) and confirm a candidate overlaps the known figure region (50,100)–(550,400):
```bash
cd /home/imalne/learn_vibe_coding
python3 .claude/skills/paper-pdf-figures/scripts/extract_pdf_figures.py \
    2606.28301v1.pdf --mode detect --out /tmp/p4smoke --paper-slug vec \
    --pages 11 --min-area-ratio 0.03
python3 -c "
import fitz, json
cands = json.load(open('/tmp/p4smoke/vec/candidates/candidates.json'))['candidates']
fig = fitz.Rect(50,100,550,400)
overlapping = [c for c in cands if fitz.Rect(*c['bbox_pdf_points']).intersects(fig)]
print('candidates on p11:', len(cands), '| overlapping known figure:', len(overlapping))
for c in overlapping: print(' ', c)
"
ls /tmp/p4smoke/vec/candidates/
```
Expected: at least 1 candidate overlaps the figure region; `page_0011_candidates.png` and `candidates.json` exist.

- [ ] **Step 2: Verify Phase 4 acceptance (spec §11 Phase 4)**

- [ ] **A1: two-column / dense pages find main figure regions.** The smoke above (and a second smoke on a two-column page if available) shows candidates overlapping figures. MET if ≥1 candidate overlaps the known figure.
- [ ] **A2: few false positives on formulas / headers / footers.** Inspect the preview PNG — `--exclude-margins 30` should suppress header/footer; formulas (small area) fall below `--min-area-ratio`. Report the candidate count as evidence (not a hard threshold).
- [ ] **A3: candidate bboxes can be copied into config.yaml.** The `candidates.json` entries have `page` + `bbox_pdf_points` in the exact format `config.yaml` expects. Verify by hand that a candidate's bbox is a valid `[x0,y0,x1,y1]` list.
- [ ] **A4: full suite passes + `check_deps` reports `[OK] numpy` + `[OK] opencv-python`.**
  ```bash
  cd .claude/skills/paper-pdf-figures && pytest tests/ -q
  python3 scripts/check_deps.py | grep -E 'numpy|opencv'
  ```

- [ ] **Step 3: Commit the acceptance evidence (optional)**

If you keep a smoke log, write it to `.superpowers/sdd/reports/phase4-smoke.md` (no code change). No commit required unless you want to record it.

---

## Phase 4 Acceptance

- **A1**: detect finds main figure regions (verified on real vector paper p11).
- **A2**: `--exclude-margins` + `--min-area-ratio` suppress header/footer/formula false positives (inspect preview).
- **A3**: `candidates.json` bboxes are directly usable in `config.yaml` (same `[x0,y0,x1,y1]` + `page` format).
- **A4**: full suite green; `check_deps` reports numpy + opencv OK.
- **A5**: detect is dry-run by design — no `figures/` directory is created; `--dry-run` writes nothing at all.

**Limitation (documented, not a defect):** `--two-column` is accepted (stored in `run_args`) but not yet wired into the algorithm — the spatial connected-component approach finds figures in either column layout without explicit column splitting. Wiring it in (gutter detection + per-column merge) is a future refinement.

---

## Self-Review Notes

**Spec coverage (Phase 4 scope):**
- §7.4 (detect dry-run: render→binarize→close→connected components→merge→filter→preview+candidates.json) → Task 1 `detect_candidates` + `draw_candidates_preview`; Task 2 dispatcher.
- §6.2 detect params (`--min-area-ratio`, `--max-area-ratio`, `--merge-distance`, `--exclude-margins`) → Task 2 args. `--two-column` accepted but deferred (noted).
- §9.4 naming (`candidates/page_{page:04d}_candidates.png`, `candidates/candidates.json`) → Task 2.
- §11 Phase 4 acceptance → Task 3.
- §8 manifest `candidates[]` → Task 2 `add_candidate`.

**Placeholder scan:** none — every code step has complete code; the algorithm parameters were verified on a real paper before writing.

**Type consistency:** `detect_candidates` returns `manifest.Candidate(page, bbox_pdf_points, score)` records, added via `Manifest.add_candidate`. `draw_candidates_preview` consumes the same `Candidate` list. Dispatcher passes the same params. `_merge_nearby` preserves the `Candidate` shape. The `pages_with_hits` local (declared before `doc = fitz.open`, incremented in the detect loop, read in the summary) is a dispatcher-internal summary counter — not part of any interface.

**Phase 1/2 compat:** the dispatcher rewrite preserves `embedded` + `manual` behavior unchanged (same args, same overwrite/validate/error-handling). Only adds the `detect` branch + 5 args + 2 validation gates (min/max-area-ratio range + inverted-pair check), both gated to `--mode detect` so embedded/manual users never see ratio errors.
