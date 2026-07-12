# Paper PDF Figures - Render Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `--mode render`: rasterize PDF pages to PNG. Three behaviors: (a) whole-page render (`pages/p{page:04d}.png`), (b) bbox region render via `--config` (`regions/{id}.png`, reuses manual's config input but outputs raster), (c) contact sheet of all rendered images.

**Architecture:** `render_pages.py` holds the render logic: `render_pages(doc, pages, out_dir, slug, dpi, dry_run) -> list[RenderedPage]` (whole pages) + `render_regions(doc, figures, out_dir, slug, dpi, dry_run) -> list[RenderedRegion]` (bbox crops as PNG) + `make_contact_sheet(images, out_path)`. `extract_pdf_figures.py` gains a `render` branch that: if `--config` set -> render regions; else -> render whole pages; always -> contact sheet. Manifest records rendered pages/regions via a new `rendered[]` array (lightweight: id/page/file/dpi, no sha needed for PNG-only).

**Tech Stack:** Python ≥3.9, PyMuPDF (`page.get_pixmap(dpi=, clip=)`), Pillow (contact sheet composition), pytest + jsonschema. 129 tests currently pass.

## Global Constraints

(From the spec §7 + design - every task inherits these.)

- Skill root: `.claude/skills/paper-pdf-figures/`; tests run from there.
- Never modify the original PDF; offline.
- Reuse Phase 0–2 modules: `crop_export.parse_config` + `FigureConfig`, `manifest.{Manifest, validate}`, `parse_pages` (dispatcher). Do not duplicate.
- **Whole-page render**: `page.get_pixmap(dpi=args.dpi)` -> PNG bytes -> `pages/p{page:04d}.png`. Filename per spec §9.6.
- **Region render**: for each `FigureConfig` (from `--config`), `page.get_pixmap(dpi=args.dpi, clip=fitz.Rect(*bbox))` -> `regions/{id}.png`. Reuses manual's config format (page+bbox+id) but outputs raster, not vector PDF.
- **Contact sheet**: compose all rendered PNGs (pages or regions) into one `summary_contact_sheet.png` via Pillow. Each thumb labeled with page/id. Grid layout (e.g. N columns).
- **manifest**: new `rendered[]` array (item: id/page/file/dpi/width/height). `Manifest.add_rendered(r)`. `RenderedItem` dataclass (id, page, file, dpi, width, height). `rendered[]` required (can be empty).
- `--config` optional: present -> region render; absent -> whole-page render. `--pages` filters whole-page render. `--dpi` controls resolution (default 300). `--dry-run` writes nothing.
- Backward compat: existing 4 modes unchanged. `render` was "not implemented yet" (exit 1) - now implemented.
- Subprocess list-form calls; output confined to `--out`.

---

## File Structure

| Path | Responsibility |
| --- | --- |
| `.claude/skills/paper-pdf-figures/scripts/render_pages.py` | `render_pages`, `render_regions`, `make_contact_sheet`, `RenderedItem` |
| `.claude/skills/paper-pdf-figures/scripts/manifest.py` | `rendered` field + `add_rendered` + `RenderedItem` dataclass |
| `.claude/skills/paper-pdf-figures/templates/manifest.schema.json` | `rendered[]` array |
| `.claude/skills/paper-pdf-figures/scripts/extract_pdf_figures.py` | `render` branch + mode gate |
| `.claude/skills/paper-pdf-figures/tests/test_render_pages.py` | NEW unit tests |
| `.claude/skills/paper-pdf-figures/tests/test_manifest.py` | +rendered[] tests |
| `.claude/skills/paper-pdf-figures/tests/test_extract_pdf_figures.py` | +render integration tests |

---

## Task 1: render_pages.py - render + contact sheet

**Files:**
- Create: `.claude/skills/paper-pdf-figures/scripts/render_pages.py`
- Create: `.claude/skills/paper-pdf-figures/tests/test_render_pages.py`

**Interfaces:**
- `render_pages.RenderedItem(id: str, page: int, file: str, dpi: int, width: int, height: int)` dataclass.
- `render_pages.render_pages(doc, pages: set[int]|None, out_dir, slug, dpi=300, dry_run=False) -> list[RenderedItem]` - whole-page render to `pages/p{page:04d}.png`.
- `render_pages.render_regions(doc, figures: list[FigureConfig], out_dir, slug, dpi=300, dry_run=False) -> list[RenderedItem]` - bbox region render to `regions/{id}.png`.
- `render_pages.make_contact_sheet(items: list[RenderedItem], out_dir, slug, dry_run=False) -> Path|None` - compose all rendered PNGs into `summary_contact_sheet.png` via Pillow.

- [ ] **Step 1: Write the failing tests**

File `.claude/skills/paper-pdf-figures/tests/test_render_pages.py`:
```python
import fitz
import pytest

import render_pages


@pytest.fixture
def multi_page_pdf(tmp_path):
    doc = fitz.open()
    for i in range(3):
        page = doc.new_page(width=612, height=792)
        page.insert_text((100, 100), f"Page {i+1}", fontsize=24)
    p = tmp_path / "multi.pdf"
    doc.save(str(p)); doc.close()
    return p


def test_render_pages_whole(multi_page_pdf, tmp_path):
    doc = fitz.open(str(multi_page_pdf))
    items = render_pages.render_pages(doc, {1, 3}, tmp_path / "out", "paper", dpi=72)
    doc.close()
    assert len(items) == 2
    assert {i.page for i in items} == {1, 3}
    for it in items:
        assert it.file.startswith("pages/p")
        assert it.file.endswith(".png")
        assert (tmp_path / "out" / "paper" / it.file).is_file()
        assert it.width > 0 and it.height > 0


def test_render_pages_all(multi_page_pdf, tmp_path):
    doc = fitz.open(str(multi_page_pdf))
    items = render_pages.render_pages(doc, None, tmp_path / "out", "paper", dpi=72)
    doc.close()
    assert len(items) == 3


def test_render_pages_dry_run(multi_page_pdf, tmp_path):
    doc = fitz.open(str(multi_page_pdf))
    items = render_pages.render_pages(doc, None, tmp_path / "out", "paper", dpi=72, dry_run=True)
    doc.close()
    assert len(items) == 3
    assert not (tmp_path / "out").exists() or not any((tmp_path / "out").rglob("*.png"))


def test_render_regions(multi_page_pdf, tmp_path):
    from crop_export import FigureConfig
    doc = fitz.open(str(multi_page_pdf))
    figs = [FigureConfig(id="r1", page=1, bbox=[50, 50, 300, 300])]
    items = render_pages.render_regions(doc, figs, tmp_path / "out", "paper", dpi=72)
    doc.close()
    assert len(items) == 1
    assert items[0].id == "r1"
    assert items[0].file == "regions/r1.png"
    assert (tmp_path / "out" / "paper" / "regions" / "r1.png").is_file()


def test_render_regions_dpi_scales(multi_page_pdf, tmp_path):
    from crop_export import FigureConfig
    doc = fitz.open(str(multi_page_pdf))
    figs = [FigureConfig(id="r1", page=1, bbox=[0, 0, 100, 100])]
    low = render_pages.render_regions(doc, figs, tmp_path / "lo", "p", dpi=72)
    high = render_pages.render_regions(doc, figs, tmp_path / "hi", "p", dpi=144)
    doc.close()
    assert high[0].width > low[0].width  # higher dpi -> more pixels


def test_make_contact_sheet(multi_page_pdf, tmp_path):
    doc = fitz.open(str(multi_page_pdf))
    items = render_pages.render_pages(doc, None, tmp_path / "out", "paper", dpi=72)
    doc.close()
    sheet = render_pages.make_contact_sheet(items, tmp_path / "out", "paper")
    assert sheet is not None
    assert sheet.is_file()
    from PIL import Image
    im = Image.open(sheet)
    assert im.format == "PNG"


def test_make_contact_sheet_empty(tmp_path):
    sheet = render_pages.make_contact_sheet([], tmp_path / "out", "paper")
    assert sheet is None  # nothing to compose
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/imalne/learn_vibe_coding/.claude/skills/paper-pdf-figures
pytest tests/test_render_pages.py -v
```
Expected: FAIL (`ModuleNotFoundError: No module named 'render_pages'`).

- [ ] **Step 3: Write `scripts/render_pages.py`**

File `.claude/skills/paper-pdf-figures/scripts/render_pages.py`:
```python
"""Render PDF pages/regions to PNG + contact sheet (--mode render)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import fitz
from PIL import Image

from crop_export import FigureConfig


@dataclass
class RenderedItem:
    id: str
    page: int
    file: str
    dpi: int
    width: int
    height: int


def render_pages(
    doc: "fitz.Document",
    pages: set[int] | None,
    out_dir: Path | str,
    slug: str,
    dpi: int = 300,
    dry_run: bool = False,
) -> list[RenderedItem]:
    """Render whole pages to pages/p{page:04d}.png."""
    out_dir = Path(out_dir)
    pages_dir = out_dir / slug / "pages"
    if not dry_run:
        pages_dir.mkdir(parents=True, exist_ok=True)
    if pages is None:
        page_indices = range(len(doc))
    else:
        page_indices = sorted(p - 1 for p in pages if 1 <= p <= len(doc))
    items: list[RenderedItem] = []
    for pno in page_indices:
        pix = doc[pno].get_pixmap(dpi=dpi)
        page_1 = pno + 1
        rel = f"pages/p{page_1:04d}.png"
        if not dry_run:
            pix.save(str(pages_dir / f"p{page_1:04d}.png"))
        items.append(RenderedItem(
            id=f"page_{page_1:04d}", page=page_1, file=rel,
            dpi=dpi, width=pix.width, height=pix.height,
        ))
    return items


def render_regions(
    doc: "fitz.Document",
    figures: list[FigureConfig],
    out_dir: Path | str,
    slug: str,
    dpi: int = 300,
    dry_run: bool = False,
) -> list[RenderedItem]:
    """Render bbox regions to regions/{id}.png."""
    out_dir = Path(out_dir)
    regions_dir = out_dir / slug / "regions"
    if not dry_run:
        regions_dir.mkdir(parents=True, exist_ok=True)
    items: list[RenderedItem] = []
    for fig in figures:
        if fig.page < 1 or fig.page > len(doc):
            continue
        clip = fitz.Rect(*fig.bbox)
        pix = doc[fig.page - 1].get_pixmap(dpi=dpi, clip=clip)
        rel = f"regions/{fig.id}.png"
        if not dry_run:
            pix.save(str(regions_dir / f"{fig.id}.png"))
        items.append(RenderedItem(
            id=fig.id, page=fig.page, file=rel,
            dpi=dpi, width=pix.width, height=pix.height,
        ))
    return items


def make_contact_sheet(
    items: list[RenderedItem],
    out_dir: Path | str,
    slug: str,
    dry_run: bool = False,
    cols: int = 4,
    thumb_w: int = 300,
) -> Path | None:
    """Compose all rendered PNGs into summary_contact_sheet.png."""
    if not items:
        return None
    out_dir = Path(out_dir)
    sheet_path = out_dir / slug / "summary_contact_sheet.png"
    if dry_run:
        return None
    thumbs = []
    for it in items:
        img_path = out_dir / slug / it.file
        if not img_path.is_file():
            continue
        im = Image.open(img_path)
        ratio = thumb_w / im.width
        im = im.resize((thumb_w, max(1, int(im.height * ratio))))
        thumbs.append((it, im))
    if not thumbs:
        return None
    rows = (len(thumbs) + cols - 1) // cols
    thumb_h = max(im.height for _, im in thumbs)
    label_h = 20
    cell_h = thumb_h + label_h
    sheet = Image.new("RGB", (cols * thumb_w, rows * cell_h), "white")
    from PIL import ImageDraw
    draw = ImageDraw.Draw(sheet)
    for idx, (it, im) in enumerate(thumbs):
        r, c = divmod(idx, cols)
        x = c * thumb_w
        y = r * cell_h
        sheet.paste(im, (x, y))
        draw.text((x + 2, y + thumb_h + 2), f"p{it.page} {it.id}", fill="black")
    sheet.save(str(sheet_path))
    return sheet_path
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/imalne/learn_vibe_coding/.claude/skills/paper-pdf-figures
pytest tests/test_render_pages.py -v
pytest tests/ -q -k "not real_doclayout"
```
Expected: 7 render tests pass; full suite 136 (was 129; +7).

- [ ] **Step 5: Commit**

```bash
cd /home/imalne/learn_vibe_coding
git add .claude/skills/paper-pdf-figures/scripts/render_pages.py .claude/skills/paper-pdf-figures/tests/test_render_pages.py
git commit -m "feat(paper-pdf-figures): render_pages whole/region render + contact sheet (render mode Task 1)"
```

---

## Task 2: manifest rendered[] + schema

**Files:**
- Modify: `.claude/skills/paper-pdf-figures/scripts/manifest.py`
- Modify: `.claude/skills/paper-pdf-figures/templates/manifest.schema.json`
- Modify: `.claude/skills/paper-pdf-figures/tests/test_manifest.py`

**Interfaces:**
- `Manifest.rendered: list[RenderedItem]` field + `add_rendered(r)`.
- `RenderedItem` imported from `render_pages` (or defined in manifest - decide: define in manifest to avoid circular import; render_pages imports it). **Decision: define `RenderedItem` in manifest.py; render_pages imports from manifest.**
- Schema: `rendered[]` required array; item: id/page/file/dpi/width/height (all required).

- [ ] **Step 1: Write failing tests (append to test_manifest.py)**

```python
def test_manifest_add_rendered_and_round_trip(tmp_path):
    m = _minimal_manifest()
    m.add_rendered(manifest.RenderedItem(
        id="page_0001", page=1, file="pages/p0001.png", dpi=300, width=2550, height=3300,
    ))
    p = m.save(tmp_path / "manifest.json")
    loaded = manifest.Manifest.load(p)
    assert len(loaded.rendered) == 1
    assert loaded.rendered[0].id == "page_0001"
    assert loaded.rendered[0].width == 2550
    assert manifest.validate(loaded.to_dict()) == []


def test_manifest_rendered_required_in_schema():
    schema = _load_schema()
    assert "rendered" in schema["required"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_manifest.py -k "rendered" -v
```
Expected: FAIL (no `rendered`/`add_rendered`/`RenderedItem`).

- [ ] **Step 3: Add `rendered` + `RenderedItem` to manifest.py**

Define `RenderedItem` dataclass in `manifest.py` (id, page, file, dpi, width, height). Add `rendered: list[RenderedItem]` field + `add_rendered`. `from_dict` reconstructs via `RenderedItem(**r)`. Update `render_pages.py` to import `RenderedItem` from `manifest` instead of defining its own (remove the local dataclass, import it).

- [ ] **Step 4: Add `rendered` to schema**

In `manifest.schema.json`: add `"rendered"` to `required`; add `rendered` property (array of items with id/page/file/dpi/width/height, all required, `additionalProperties: false`). Update existing hand-built manifest fixtures in tests by adding `"rendered": []` if they break.

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_manifest.py -v
pytest tests/ -q -k "not real_doclayout"
```
Expected: manifest tests pass (existing + 2 new); full suite 138 (was 136; +2). Fix any fixture breakage from `rendered` required.

- [ ] **Step 6: Commit**

```bash
git add .claude/skills/paper-pdf-figures/scripts/manifest.py .claude/skills/paper-pdf-figures/scripts/render_pages.py .claude/skills/paper-pdf-figures/templates/manifest.schema.json .claude/skills/paper-pdf-figures/tests/test_manifest.py
git commit -m "feat(paper-pdf-figures): manifest rendered[] + schema (render mode Task 2)"
```

---

## Task 3: dispatcher render branch

**Files:**
- Modify: `.claude/skills/paper-pdf-figures/scripts/extract_pdf_figures.py`
- Modify: `.claude/skills/paper-pdf-figures/tests/test_extract_pdf_figures.py`

**Interfaces:**
- Mode gate: allow `render` (was "not implemented yet").
- `render` branch: if `--config` set -> `parse_config` -> `render_regions`; else -> `render_pages` (with `--pages`). Always -> `make_contact_sheet`. Manifest: `add_rendered` per item. `WARN_NO_RENDERED` if empty. Summary: `rendered: N`.

- [ ] **Step 1: Write failing tests (append to test_extract_pdf_figures.py)**

```python
def test_render_mode_whole_pages(multi_page_pdf_via_conftest, tmp_path):
    # use a multi-page fixture; if conftest lacks one, build inline
    out = tmp_path / "out"
    r = _run(multi_page_pdf_via_conftest, out, "--mode", "render", "--paper-slug", "p", "--dpi", "72")
    assert r.returncode == 0, r.stderr
    assert "rendered:" in r.stdout
    m = manifest.Manifest.load(out / "p" / "manifest.json")
    assert len(m.rendered) >= 1
    assert (out / "p" / "pages" / "p0001.png").is_file()
    assert (out / "p" / "summary_contact_sheet.png").is_file()
    assert manifest.validate(m.to_dict()) == []


def test_render_mode_with_config_regions(vector_pdf, tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "figures:\n"
        "  - id: r1\n"
        "    page: 1\n"
        "    bbox: [60, 60, 210, 210]\n"
    )
    out = tmp_path / "out"
    r = _run(vector_pdf, out, "--mode", "render", "--config", str(cfg),
             "--paper-slug", "p", "--dpi", "72")
    assert r.returncode == 0, r.stderr
    m = manifest.Manifest.load(out / "p" / "manifest.json")
    assert len(m.rendered) == 1
    assert m.rendered[0].id == "r1"
    assert (out / "p" / "regions" / "r1.png").is_file()
    assert (out / "p" / "summary_contact_sheet.png").is_file()


def test_render_mode_pages_filter(multi_page_pdf_via_conftest, tmp_path):
    out = tmp_path / "out"
    r = _run(multi_page_pdf_via_conftest, out, "--mode", "render", "--paper-slug", "p",
             "--pages", "1", "--dpi", "72")
    assert r.returncode == 0, r.stderr
    assert (out / "p" / "pages" / "p0001.png").is_file()
    assert not (out / "p" / "pages" / "p0002.png").exists()
```

**Note**: the `multi_page_pdf_via_conftest` fixture - if conftest doesn't have one, add a `multi_page_pdf` fixture to conftest (2-3 pages with text), or build inline in the test. Prefer adding to conftest.

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_extract_pdf_figures.py -k "render_mode" -v
```
Expected: FAIL (render exits 1 "not implemented yet"; or fixture missing).

- [ ] **Step 3: Modify extract_pdf_figures.py**

a) Mode gate: add `render` to allowed modes:
```python
    if args.mode not in ("embedded", "manual", "detect", "auto", "render"):
        ...
```
b) Add `render` branch in the try block (after detect/auto):
```python
        elif args.mode == "render":
            from render_pages import render_pages as _render_pages, render_regions, make_contact_sheet
            if args.config:
                try:
                    figures = parse_config(args.config)
                except (OSError, yaml.YAMLError, ValueError, KeyError) as e:
                    print(f"ERROR: {e}", file=sys.stderr)
                    return 1
                rendered = render_regions(doc, figures, out_dir, slug,
                                          dpi=args.dpi, dry_run=args.dry_run)
            else:
                rendered = _render_pages(doc, pages_set, out_dir, slug,
                                        dpi=args.dpi, dry_run=args.dry_run)
            if not args.dry_run:
                make_contact_sheet(rendered, out_dir, slug)
```
c) Manifest: add `add_rendered` for each item; `WARN_NO_RENDERED` if empty (non-dry-run).
d) Summary: `print(f"rendered: {len(rendered)}")`.

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/imalne/learn_vibe_coding/.claude/skills/paper-pdf-figures
pytest tests/test_extract_pdf_figures.py -k "render_mode or render" -v
pytest tests/ -q -k "not real_doclayout"
```
Expected: 3 render tests pass; full suite 141 (was 138; +3). Existing `test_unimplemented_mode_errors` (uses `--mode render`) MUST be updated to use a still-unimplemented mode - but now ALL 5 modes are implemented. Change that test to assert `--mode auto` without ML deps errors, OR remove the "unimplemented" assertion (since no mode is unimplemented now). Simplest: change it to test an invalid mode via argparse `choices` (argparse rejects unknown modes automatically). Update the test to `--mode invalid` expecting argparse error (exit 2).

- [ ] **Step 5: Commit**

```bash
git add .claude/skills/paper-pdf-figures/scripts/extract_pdf_figures.py .claude/skills/paper-pdf-figures/tests/test_extract_pdf_figures.py .claude/skills/paper-pdf-figures/tests/conftest.py
git commit -m "feat(paper-pdf-figures): CLI render mode (render Task 3)"
```

---

## Task 4: Real-paper acceptance + update SKILL.md/README

**Files:**
- (no code) real-paper smoke
- Modify: `.claude/skills/paper-pdf-figures/SKILL.md` (update mode list: render now implemented)
- Modify: `.claude/skills/paper-pdf-figures/README.md` (add render to modes table)

- [ ] **Step 1: Real-paper smoke**

```bash
cd /home/imalne/learn_vibe_coding
python3 .claude/skills/paper-pdf-figures/scripts/extract_pdf_figures.py \
    2606.28301v1.pdf --mode render --out /tmp/render_acc --paper-slug vec \
    --pages 1,11 --dpi 150
```
Confirm: `pages/p0001.png` + `pages/p0011.png` + `summary_contact_sheet.png` exist; manifest schema-valid; source PDF unchanged.

- [ ] **Step 2: Verify acceptance**
- A1: whole-page render produces PNGs
- A2: `--config` region render produces region PNGs
- A3: contact sheet composed
- A4: source PDF unchanged
- A5: full suite passes
- A6: all 5 modes now implemented (no "not implemented yet")

- [ ] **Step 3: Update SKILL.md + README**

In SKILL.md, the mode list mentions `render: render full pages or selected regions to PNG` - update if it said "not implemented". In README.md modes table, render row is already listed - confirm it's accurate.

- [ ] **Step 4: Commit**

```bash
git add .claude/skills/paper-pdf-figures/SKILL.md .claude/skills/paper-pdf-figures/README.md
git commit -m "docs(paper-pdf-figures): render mode now implemented (render Task 4)"
```

---

## Self-Review Notes

**Spec coverage:**
- §7 render (whole page + region + contact sheet) -> Task 1 + Task 3.
- §9.6 naming (`pages/p{page:04d}.png`) -> Task 1.
- manifest `rendered[]` -> Task 2.
- All 5 modes implemented -> Task 3 + Task 4.

**Backward compat:**
- `render` was exit-1 "not implemented yet"; now implemented. Existing `test_unimplemented_mode_errors` needs updating (no mode is unimplemented now).
- `RenderedItem` defined in `manifest.py` (avoid circular import: render_pages imports from manifest).
- Existing 4 modes unchanged.

**Type consistency:** `render_pages.render_pages/render_regions -> list[RenderedItem]`; dispatcher `add_rendered` per item; schema `rendered[]` item matches. `make_contact_sheet` consumes `RenderedItem.file` paths.

**Risk:** Task 3's `test_unimplemented_mode_errors` update - all 5 modes now implemented, so the test's premise (an unimplemented mode) no longer holds. Change it to test argparse rejecting an invalid mode (`--mode invalid` -> exit 2), or remove it. The `multi_page_pdf` fixture may need adding to conftest.
