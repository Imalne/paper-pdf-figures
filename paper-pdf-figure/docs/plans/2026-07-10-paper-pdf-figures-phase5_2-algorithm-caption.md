# Paper PDF Figures - Phase 5.2 (Algorithm Separation + Caption Rescan) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** (1) Post-process cropped tables to separate **algorithm** blocks (DocLayout-YOLO has no `algorithm` class, so pseudocode gets misclassified as `table`) into a new `algorithms/` directory + manifest `algorithms[]`. (2) Rescan `plain text`/`title` regions to recover **table captions** the model misclassified (e.g. "Table 1:" caption detected as `plain text` instead of `table_caption`).

**Architecture:** Two independent post-processing steps added to the dispatcher's `auto` branch, both AFTER `pair_and_merge_multi` + `crop_figures`:
- **Caption rescan (D)**: before cropping, for each table that did NOT pair with a `table_caption`, scan same-page `plain text`/`title` regions for text starting with `Table N:`; merge the nearest one's bbox into the table. Records `caption_source` ("model" | "text-rescan" | "none").
- **Algorithm separation (A)**: after cropping to `tables/`, read each cropped table's text; classify via regex (Algorithm N / Algorithm: / pseudocode keywords ≥2) -> move algorithm files to `algorithms/`, rename id `tbl_` -> `alg_`, set `type="page-crop-algorithm"`, record in manifest `algorithms[]`.

**Tech Stack:** Python ≥3.9, PyMuPDF, opencv, numpy, torch + doclayout-yolo, pytest + jsonschema. 101 tests currently pass.

## Global Constraints

(From the design - every task inherits these.)

- Skill root: `.claude/skills/paper-pdf-figures/`; tests run from there.
- Never modify the original PDF; offline except first-run weight download.
- Reuse Phase 5/5.1 modules. `model_detect.pair_and_merge_multi`, `crop_figures(output_subdir=)`, `manifest.{Figure, Manifest, add_table, validate}`.
- **Algorithm classification rules** (verified on real paper - 2 false-positives + 7 real tables, 100% accuracy):
  - `re.search(r'Algorithm\s+\d+', text, IGNORECASE)` -> algorithm
  - `re.search(r'Algorithm\s*:', text, IGNORECASE)` -> algorithm
  - pseudocode keyword count ≥ 2 of: `Input:`, `Output:`, `for `, `while `, `return `, `do:`, `end for`, `end while` -> algorithm
  - else -> table
- **Caption rescan**: only for tables that did NOT pair with a `table_caption` (avoid double-processing). Scan same-page regions with label `plain text` or `title`; if text (stripped, first line) matches `^Table\s+\d+`, take the nearest by vertical distance; merge union bbox. Mark `caption_source="text-rescan"`. Tables paired via model keep `caption_source="model"`. No caption found -> `caption_source="none"` (no warning; acceptable).
- **Output dirs**: `figures/` (fig_), `tables/` (tbl_, type `page-crop-table`), `algorithms/` (alg_, type `page-crop-algorithm`).
- **manifest**: new `algorithms[]` array (item schema = same as `tables[]`). `Manifest.add_algorithm(t)`. `algorithms[]` required (can be empty).
- `Figure` gains optional `caption_source: str | None = None` field (nullable in schema) - records how caption was paired (model/text-rescan/none). Applies to tables + algorithms (figures keep None).
- Backward compat: `crop_figures` unchanged. `pair_and_merge_multi` unchanged. New post-processing is additive in the dispatcher's auto branch only.
- Subprocess list-form calls; output confined to `--out`.

**Pre-req:** ML deps installed (Phase 5). Verified on `2606.28301v1.pdf`: 9 tables -> 7 real tables + 2 algorithms (p21/p22).

---

## File Structure

| Path | Responsibility |
| --- | --- |
| `.claude/skills/paper-pdf-figures/scripts/postprocess.py` | NEW: `classify_table_or_algorithm(text) -> str`, `rescan_table_caption(table_region, regions, page_num) -> tuple[LayoutRegion, str]` (returns merged region + caption_source) |
| `.claude/skills/paper-pdf-figures/scripts/manifest.py` | `add_algorithm`, `algorithms` field; `Figure.caption_source` field; `from_dict`/`to_dict` |
| `.claude/skills/paper-pdf-figures/templates/manifest.schema.json` | `algorithms[]` array; `caption_source` on figure/table/algorithm items |
| `.claude/skills/paper-pdf-figures/scripts/extract_pdf_figures.py` | auto branch: caption rescan before crop + algorithm separation after crop |
| `.claude/skills/paper-pdf-figures/tests/test_postprocess.py` | NEW: classification + rescan tests |
| `.claude/skills/paper-pdf-figures/tests/test_manifest.py` | +algorithms[] tests |
| `.claude/skills/paper-pdf-figures/tests/test_extract_pdf_figures.py` | +auto algorithm-separation test |

---

## Task 1: postprocess.py - classification + caption rescan

**Files:**
- Create: `.claude/skills/paper-pdf-figures/scripts/postprocess.py`
- Create: `.claude/skills/paper-pdf-figures/tests/test_postprocess.py`

**Interfaces:**
- `postprocess.classify_table_or_algorithm(text: str) -> str` - returns `"algorithm"` or `"table"`.
- `postprocess.ALGORITHM_KEYWORDS` - the list of pseudocode keywords.
- `postprocess.rescan_table_caption(table_region: LayoutRegion, regions: list[LayoutRegion], page_num: int) -> tuple[LayoutRegion, str]` - returns `(merged_region, caption_source)`. `caption_source` is `"text-rescan"` if a caption was found, else `"none"`. (Caller handles the `"model"` case before calling.)

- [ ] **Step 1: Write the failing tests**

File `.claude/skills/paper-pdf-figures/tests/test_postprocess.py`:
```python
import postprocess
import model_detect


def _region(label, bbox, conf=0.9):
    return model_detect.LayoutRegion(bbox_pdf_points=list(bbox), label=label, confidence=conf)


def test_classify_algorithm_N():
    assert postprocess.classify_table_or_algorithm(
        "Algorithm 4 Momentum MDM-VGB sampler") == "algorithm"


def test_classify_algorithm_colon():
    assert postprocess.classify_table_or_algorithm(
        "Algorithm: do stuff") == "algorithm"


def test_classify_pseudocode_keywords():
    text = "Input: context x\nOutput: result\nfor x in y: do something"
    assert postprocess.classify_table_or_algorithm(text) == "algorithm"


def test_classify_single_keyword_is_table():
    # only one pseudocode keyword -> not enough -> table
    text = "Method Letter Acc. Input: foo"
    assert postprocess.classify_table_or_algorithm(text) == "table"


def test_classify_real_table_is_table():
    text = "Heuristic verifier Learned verifier Method Letter Sudoku QM9\n25.6 30.1"
    assert postprocess.classify_table_or_algorithm(text) == "table"


def test_classify_empty_text_is_table():
    assert postprocess.classify_table_or_algorithm("") == "table"


def test_rescan_finds_table_caption_in_plain_text():
    # table at [100,200,400,300]; caption "Table 1:..." misdetected as plain text below at [100,310,400,340]
    tbl = _region("table", [100, 200, 400, 300])
    caption = _region("plain text", [100, 310, 400, 340])
    # simulate text starting with "Table 1:"
    import fitz
    # rescan works on regions; we need the text. For unit test, patch the text getter.
    # Easier: rescan takes a text-extractor callable.
    def text_of(region):
        if region is caption:
            return "Table 1: Generation results."
        return "some other text"
    merged, source = postprocess.rescan_table_caption(
        tbl, [caption, _region("plain text", [100, 400, 400, 450])],
        page_num=11, text_of=text_of,
    )
    assert source == "text-rescan"
    assert merged.bbox_pdf_points == [100, 200, 400, 340]  # union


def test_rescan_returns_none_when_no_caption():
    tbl = _region("table", [100, 200, 400, 300])
    other = _region("plain text", [100, 400, 400, 450])
    def text_of(region):
        return "just body text, no Table N:"
    merged, source = postprocess.rescan_table_caption(tbl, [other], page_num=11, text_of=text_of)
    assert source == "none"
    assert merged.bbox_pdf_points == [100, 200, 400, 300]  # unchanged


def test_rescan_picks_nearest_caption():
    tbl = _region("table", [100, 200, 400, 300])
    near = _region("plain text", [100, 310, 400, 340])
    far = _region("title", [100, 600, 400, 630])
    def text_of(region):
        if region is near: return "Table 1: near."
        if region is far: return "Table 99: far."
        return "body"
    merged, source = postprocess.rescan_table_caption(
        tbl, [far, near], page_num=11, text_of=text_of)
    assert source == "text-rescan"
    # near is closer (gap 10) than far (gap 300)
    assert merged.bbox_pdf_points == [100, 200, 400, 340]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/imalne/learn_vibe_coding/.claude/skills/paper-pdf-figures
pytest tests/test_postprocess.py -v
```
Expected: FAIL (`ModuleNotFoundError: No module named 'postprocess'`).

- [ ] **Step 3: Write `scripts/postprocess.py`**

File `.claude/skills/paper-pdf-figures/scripts/postprocess.py`:
```python
"""Post-processing for auto-mode table crops (Phase 5.2).

- classify_table_or_algorithm: distinguish real tables from algorithm
  pseudocode blocks (DocLayout-YOLO has no `algorithm` class).
- rescan_table_caption: recover table captions the model misclassified as
  plain text / title (text starting with "Table N:").
"""
from __future__ import annotations

import re

from model_detect import LayoutRegion, _center, _union

ALGORITHM_KEYWORDS = [
    "Input:", "Output:", "for ", "while ", "return ", "do:",
    "end for", "end while",
]

_CAPTION_RE = re.compile(r"^Table\s+\d+", re.IGNORECASE)


def classify_table_or_algorithm(text: str) -> str:
    """Return 'algorithm' if `text` looks like pseudocode, else 'table'."""
    if not text:
        return "table"
    if re.search(r"Algorithm\s+\d+", text, re.IGNORECASE):
        return "algorithm"
    if re.search(r"Algorithm\s*:", text, re.IGNORECASE):
        return "algorithm"
    kw_count = sum(1 for kw in ALGORITHM_KEYWORDS if kw in text)
    if kw_count >= 2:
        return "algorithm"
    return "table"


def rescan_table_caption(
    table_region: LayoutRegion,
    regions: list[LayoutRegion],
    page_num: int,
    text_of,
) -> tuple[LayoutRegion, str]:
    """Find a 'Table N:' caption misclassified as plain text/title; merge bbox.

    `text_of(region) -> str` extracts text from a candidate region (the caller
    knows how to render the page region to text). Returns (merged_region,
    caption_source) where caption_source is 'text-rescan' if found else 'none'.
    """
    candidates = [r for r in regions
                  if r.label in ("plain text", "title") and r is not table_region]
    tcx, tcy = _center(table_region.bbox_pdf_points)
    best, best_d = None, float("inf")
    for r in candidates:
        text = text_of(r)
        first_line = text.strip().split("\n", 1)[0] if text else ""
        if not _CAPTION_RE.match(first_line):
            continue
        rcx, rcy = _center(r.bbox_pdf_points)
        d = abs(rcy - tcy) + abs(rcx - tcx) * 0.1
        if d < best_d:
            best_d, best = d, r
    if best is not None:
        merged = LayoutRegion(
            _union(table_region.bbox_pdf_points, best.bbox_pdf_points),
            table_region.label, table_region.confidence,
        )
        return merged, "text-rescan"
    return table_region, "none"
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/imalne/learn_vibe_coding/.claude/skills/paper-pdf-figures
pytest tests/test_postprocess.py -v
pytest tests/ -q -k "not real_doclayout"
```
Expected: 9 postprocess tests pass; full suite 110 (was 101; +9).

- [ ] **Step 5: Commit**

```bash
cd /home/imalne/learn_vibe_coding
git add .claude/skills/paper-pdf-figures/scripts/postprocess.py .claude/skills/paper-pdf-figures/tests/test_postprocess.py
git commit -m "feat(paper-pdf-figures): postprocess classify algorithm + rescan caption (Phase 5.2 Task 1)"
```

---

## Task 2: manifest algorithms[] + caption_source field + schema

**Files:**
- Modify: `.claude/skills/paper-pdf-figures/scripts/manifest.py`
- Modify: `.claude/skills/paper-pdf-figures/templates/manifest.schema.json`
- Modify: `.claude/skills/paper-pdf-figures/tests/test_manifest.py`

**Interfaces:**
- `Manifest.algorithms: list[Figure]` field + `add_algorithm(t)`.
- `Figure.caption_source: str | None = None` (records "model" | "text-rescan" | "none" for tables; None for figures).
- Schema: `algorithms[]` required array (item schema = same as tables); `caption_source` optional nullable string on figure/table/algorithm items.

- [ ] **Step 1: Write failing tests (append to test_manifest.py)**

```python
def test_manifest_add_algorithm_and_round_trip(tmp_path):
    m = _minimal_manifest()
    m.add_algorithm(manifest.Figure(
        id="alg_p0022_01", page=22, bbox_pdf_points=[100, 200, 500, 400],
        type="page-crop-algorithm", extraction_method="manual-bbox", dpi=300,
        files={"pdf": "algorithms/alg_p0022_01/alg_p0022_01.pdf", "png": None, "svg": None},
        sha256={"pdf": "abc"}, caption_source="text-rescan",
    ))
    p = m.save(tmp_path / "manifest.json")
    loaded = manifest.Manifest.load(p)
    assert len(loaded.algorithms) == 1
    assert loaded.algorithms[0].id == "alg_p0022_01"
    assert loaded.algorithms[0].type == "page-crop-algorithm"
    assert loaded.algorithms[0].caption_source == "text-rescan"
    assert manifest.validate(loaded.to_dict()) == []


def test_manifest_algorithms_required_in_schema():
    schema = _load_schema()
    assert "algorithms" in schema["required"]


def test_manifest_caption_source_field_round_trip(tmp_path):
    m = _minimal_manifest()
    m.add_table(manifest.Figure(
        id="tbl_p0011_01", page=11, bbox_pdf_points=[100, 200, 500, 400],
        type="page-crop-table", extraction_method="manual-bbox", dpi=300,
        files={"pdf": "tables/tbl_p0011_01/tbl_p0011_01.pdf", "png": None, "svg": None},
        sha256={}, caption_source="model",
    ))
    p = m.save(tmp_path / "manifest.json")
    loaded = manifest.Manifest.load(p)
    assert loaded.tables[0].caption_source == "model"
    assert manifest.validate(loaded.to_dict()) == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_manifest.py -k "algorithm or caption_source" -v
```
Expected: FAIL (no `algorithms`/`add_algorithm`/`caption_source`).

- [ ] **Step 3: Add `algorithms` + `caption_source` to manifest.py**

In `manifest.py`:
- `Figure` dataclass gains: `caption_source: str | None = None`
- `Manifest` gains: `algorithms: list[Figure] = field(default_factory=list)` + `add_algorithm(self, t)` method.
- `from_dict` adds: `algorithms=[Figure(**a) for a in d.get("algorithms", [])]` + `caption_source=f.get("caption_source")` in each Figure reconstruction (figures/tables/algorithms).

- [ ] **Step 4: Add `algorithms` + `caption_source` to schema**

In `manifest.schema.json`:
- Add `"algorithms"` to top-level `required`.
- Add `algorithms` property (same item schema as `tables`).
- Add `"caption_source": {"type": ["string", "null"]}` to the `properties` of figures, tables, AND algorithms items.

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_manifest.py -v
pytest tests/ -q -k "not real_doclayout"
```
Expected: manifest tests pass (existing + 3 new); full suite 113 (was 110; +3). NOTE: adding `algorithms` to `required` may break existing hand-built manifest fixtures in tests - fix them by adding `"algorithms": []` (same approach as Task 2 of Phase 5.1).

- [ ] **Step 6: Commit**

```bash
git add .claude/skills/paper-pdf-figures/scripts/manifest.py .claude/skills/paper-pdf-figures/templates/manifest.schema.json .claude/skills/paper-pdf-figures/tests/test_manifest.py
git commit -m "feat(paper-pdf-figures): manifest algorithms[] + caption_source (Phase 5.2 Task 2)"
```

---

## Task 3: dispatcher auto branch - caption rescan + algorithm separation

**Files:**
- Modify: `.claude/skills/paper-pdf-figures/scripts/extract_pdf_figures.py`
- Modify: `.claude/skills/paper-pdf-figures/tests/test_extract_pdf_figures.py`

**Interfaces:**
- auto branch flow: `pair_and_merge_multi` -> for each table pair with caption=None, `rescan_table_caption` -> `crop_figures` to `tables/` -> for each cropped table, read text, `classify_table_or_algorithm` -> if algorithm, move file to `algorithms/`, rename id `tbl_`->`alg_`, set `type="page-crop-algorithm"`, add to `algorithms[]` instead of `tables[]`.
- `caption_source` set on every table/algorithm Figure: "model" (paired via table_caption), "text-rescan" (recovered via rescan), "none" (no caption found).

- [ ] **Step 1: Write failing tests (append to test_extract_pdf_figures.py)**

```python
def test_auto_mode_separates_algorithm(vector_pdf, tmp_path, monkeypatch, capsys):
    """A table whose cropped text contains 'Algorithm N' -> moved to algorithms/."""
    import model_detect
    # one region labeled "table" but whose crop text will look like an algorithm.
    # We can't easily inject crop text via FakeDetector; instead, patch
    # postprocess.classify_table_or_algorithm to recognize a marker in the id.
    # Simpler: make the table region's bbox produce a vector_pdf crop with
    # algorithm-like text. Hardest path -> patch the classifier.
    import postprocess
    real = postprocess.classify_table_or_algorithm
    def fake_classify(text):
        if "ALG_MARKER" in text:
            return "algorithm"
        return real(text)
    monkeypatch.setattr(postprocess, "classify_table_or_algorithm", fake_classify)
    # patch crop to inject marker text - can't easily. Instead patch the
    # dispatcher's text-reading to return marker for one table. Simplest:
    # patch fitz.Page.get_text to append marker for the algorithm table.
    # Even simpler: make the FakeDetector return a region whose id we can
    # detect, and patch the classifier to mark it. Use a sentinel label.
    # ACTUALLY: the cleanest unit test patches classify + uses a real crop.
    # Skip the marker approach - directly patch the dispatcher's post-process.
    # For a clean test: use a 2-table fixture where one crops to algorithm-ish
    # text is hard. So patch `postprocess.classify_table_or_algorithm` to
    # return "algorithm" for ANY text containing "Algorithm", and make the
    # vector_pdf draw "Algorithm 9" text in one bbox.
    import fitz
    # redraw vector_pdf with an algorithm-looking block
    # (the fixture is shared; instead use a local PDF)
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((100, 150), "Algorithm 9: do stuff", fontsize=12)
    page.insert_text((100, 170), "Input: x", fontsize=10)
    page.insert_text((100, 185), "Output: y", fontsize=10)
    alg_pdf = tmp_path / "alg.pdf"
    doc.save(str(alg_pdf)); doc.close()

    regions = [model_detect.LayoutRegion([90, 130, 300, 200], "table", 0.9)]
    fake = model_detect.FakeDetector({1: regions})
    monkeypatch.setattr(model_detect, "DocLayoutYoloDetector", lambda: fake)
    import extract_pdf_figures
    rc = extract_pdf_figures.main([str(alg_pdf), "--mode", "auto", "--paper-slug", "p",
                                   "--dpi", "150", "--out", str(tmp_path / "out")])
    out = capsys.readouterr()
    assert rc == 0, out.err
    assert "tables: 0" in out.out
    assert "algorithms: 1" in out.out
    m = manifest.Manifest.load(tmp_path / "out" / "p" / "manifest.json")
    assert len(m.tables) == 0
    assert len(m.algorithms) == 1
    assert m.algorithms[0].id == "alg_p0001_01"
    assert m.algorithms[0].type == "page-crop-algorithm"
    assert (tmp_path / "out" / "p" / "algorithms" / "alg_p0001_01" / "alg_p0001_01.pdf").is_file()
    assert not (tmp_path / "out" / "p" / "tables").exists() or not list((tmp_path / "out" / "p" / "tables").glob("*"))
    assert manifest.validate(m.to_dict()) == []


def test_auto_mode_caption_rescan_recovers_table_caption(vector_pdf, tmp_path, monkeypatch, capsys):
    """Table with no table_caption pair, but a 'Table N:' in plain text -> merged."""
    import model_detect
    # table region; a plain text region below it with "Table 1:" text.
    # FakeDetector returns regions; the dispatcher must extract text from
    # the page region to rescan. Patch the text_of callable via monkeypatch
    # on the rescan call... but rescan is called inside the dispatcher.
    # Cleanest: make a real PDF where the table + a "Table 1:" caption exist
    # as vector text, so get_text returns real text.
    import fitz
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.draw_rect(fitz.Rect(100, 100, 400, 200), color=(0,0,0), width=1)
    page.insert_text((100, 220), "Table 1: Real caption below.", fontsize=10)
    tbl_pdf = tmp_path / "tbl.pdf"
    doc.save(str(tbl_pdf)); doc.close()
    # detector returns: table + a plain_text region covering the caption
    regions = [
        model_detect.LayoutRegion([100, 100, 400, 200], "table", 0.9),
        model_detect.LayoutRegion([100, 210, 400, 230], "plain text", 0.9),  # the caption, misclassified
    ]
    fake = model_detect.FakeDetector({1: regions})
    monkeypatch.setattr(model_detect, "DocLayoutYoloDetector", lambda: fake)
    import extract_pdf_figures
    rc = extract_pdf_figures.main([str(tbl_pdf), "--mode", "auto", "--paper-slug", "p",
                                   "--dpi", "150", "--out", str(tmp_path / "out")])
    out = capsys.readouterr()
    assert rc == 0, out.err
    m = manifest.Manifest.load(tmp_path / "out" / "p" / "manifest.json")
    assert len(m.tables) == 1
    # caption merged: bbox should extend below 200 to include caption ~230
    assert m.tables[0].bbox_pdf_points[3] > 200  # y1 extended
    assert m.tables[0].caption_source == "text-rescan"
    assert manifest.validate(m.to_dict()) == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_extract_pdf_figures.py -k "separates_algorithm or caption_rescan" -v
```
Expected: FAIL (no algorithm separation; no caption_source).

- [ ] **Step 3: Modify the auto branch in extract_pdf_figures.py**

This is the most involved change. After `pair_and_merge_multi` and BEFORE `crop_figures`, do caption rescan on unpaired tables. After `crop_figures` to `tables/`, classify each and move algorithms.

a) Add import at top:
```python
import re
import postprocess
```

b) After building `groups` from `pair_and_merge_multi`, for the table group, rescan captions on pairs with `paired_caption is None`. The current loop builds `all_table_configs` from `pairs`. Insert caption rescan before `regions_to_figure_configs`:

```python
                for primary, pairs in groups.items():
                    if primary == "table":
                        # caption rescan for tables that didn't pair via model
                        rescan_pairs = []
                        for merged, paired_cap in pairs:
                            if paired_cap is not None:
                                rescan_pairs.append((merged, paired_cap, "model"))
                            else:
                                # rescan plain text/title for "Table N:" caption
                                def text_of(region):
                                    # render the region's bbox on the page to text
                                    page_clip = fitz.Rect(*region.bbox_pdf_points)
                                    # expand clip slightly to catch partial text
                                    return doc[pno].get_textbox(page_clip)
                                rescanned, source = postprocess.rescan_table_caption(
                                    merged, regions, pno + 1, text_of=text_of)
                                rescan_pairs.append((rescanned, paired_cap, source))
                        # build configs with caption_source metadata
                        for idx, (merged, _cap, source) in enumerate(rescan_pairs, start=1):
                            fig_id = f"tbl_p{pno + 1:04d}_{idx:02d}"
                            all_table_configs.append(
                                (FigureConfig(id=fig_id, page=pno + 1, bbox=list(merged.bbox_pdf_points)),
                                 source)
                            )
                    else:
                        id_prefix = "tbl" if primary == "table" else ("fig" if primary == "figure" else "".join(c if c.isalnum() else "_" for c in primary)[:8] or "reg")
                        configs = model_detect.regions_to_figure_configs(pairs, page=pno + 1, id_prefix=id_prefix)
                        if primary == "table":
                            # handled above with caption_source
                            pass
                        else:
                            all_figure_configs.extend(configs)
```
**Note**: `all_table_configs` now stores `(FigureConfig, caption_source)` tuples. Adjust the downstream crop + manifest accordingly. This is a refactor of the table handling - keep figure handling unchanged.

c) Crop tables (with caption_source):
```python
            if not args.dry_run:
                # figures
                records = crop_figures(doc, all_figure_configs, out_dir, slug,
                                       dpi=args.dpi, formats=formats, warnings=warnings)
                # tables (split into tables vs algorithms after classification)
                table_configs_only = [c for c, _ in all_table_configs]
                table_records_raw = crop_figures(doc, table_configs_only, out_dir, slug,
                                                 dpi=args.dpi, formats=formats, warnings=warnings,
                                                 output_subdir="tables")
                # classify each: read cropped text
                final_table_records = []
                algorithm_records = []
                for (cfg, source), rec in zip(all_table_configs, table_records_raw):
                    # read text from the cropped PDF
                    import fitz as _fitz
                    cdoc = _fitz.open(str(out_dir / slug / rec.files["pdf"]))
                    text = cdoc[0].get_text()
                    cdoc.close()
                    kind = postprocess.classify_table_or_algorithm(text)
                    if kind == "algorithm":
                        # move file from tables/ to algorithms/, rename id
                        old_dir = out_dir / slug / "tables" / cfg.id
                        new_id = cfg.id.replace("tbl_", "alg_", 1)
                        new_dir = out_dir / slug / "algorithms" / new_id
                        new_dir.parent.mkdir(parents=True, exist_ok=True)
                        import shutil as _shutil
                        _shutil.move(str(old_dir), str(new_dir))
                        # rename files inside
                        for f in new_dir.iterdir():
                            if f.name.startswith("tbl_"):
                                f.rename(new_dir / f.name.replace("tbl_", "alg_", 1))
                        rec.id = new_id
                        rec.type = "page-crop-algorithm"
                        rec.files = {k: (v.replace("tables/", "algorithms/").replace("tbl_", "alg_", 1) if v else v) for k, v in rec.files.items()}
                        rec.caption_source = source
                        algorithm_records.append(rec)
                    else:
                        rec.caption_source = source
                        final_table_records.append(rec)
                table_records = final_table_records
            else:
                records = []
                table_records = []
                algorithm_records = []
```

d) Manifest construction - add algorithms + caption_source:
```python
    elif args.mode == "auto":
        for rec in records:
            m.add_figure(rec)
        if not records and not args.dry_run:
            m.add_warning("WARN_NO_FIGURES")
        for rec in table_records:
            m.add_table(rec)
        for rec in algorithm_records:
            m.add_algorithm(rec)
        if not table_records and not args.dry_run:
            m.add_warning("WARN_NO_TABLES")
```

e) Summary print:
```python
    elif args.mode in ("manual", "auto"):
        print(f"figures: {len(records)}")
        if args.mode == "auto":
            print(f"tables: {len(table_records)}")
            print(f"algorithms: {len(algorithm_records)}")
            print(f"candidates: {len(all_candidates)} across {pages_with_hits} pages")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/imalne/learn_vibe_coding/.claude/skills/paper-pdf-figures
pytest tests/test_extract_pdf_figures.py -k "auto or table or algorithm or caption" -v
pytest tests/ -q -k "not real_doclayout"
```
Expected: all auto tests pass (existing + 2 new); full suite 115 (was 113; +2). The existing `test_auto_mode_crops_table_separately` may need `caption_source` assertion added or its FakeDetector regions adjusted - update minimally if it breaks.

- [ ] **Step 5: Commit**

```bash
git add .claude/skills/paper-pdf-figures/scripts/extract_pdf_figures.py .claude/skills/paper-pdf-figures/tests/test_extract_pdf_figures.py
git commit -m "feat(paper-pdf-figures): auto mode algorithm separation + caption rescan (Phase 5.2 Task 3)"
```

---

## Task 4: Real-paper acceptance (2606.28301v1.pdf)

**Files:** (no code) real-paper smoke.

- [ ] **Step 1: Run auto on the vector paper**

```bash
cd /home/imalne/learn_vibe_coding
export HF_ENDPOINT=https://hf-mirror.com
python3 .claude/skills/paper-pdf-figures/scripts/extract_pdf_figures.py \
    2606.28301v1.pdf --mode auto --out /tmp/p52acc --paper-slug vec \
    --dpi 300 --overwrite
```
Confirm:
- `figures: 17` + `tables: 7` + `algorithms: 2` (the 2 algorithm false-positives p21/p22 moved out of tables)
- `tables/` has 7 (real Table 1-7), `algorithms/` has 2 (p21/p22)
- Some tables have `caption_source: "text-rescan"` (Table 1/2 recovered) or "model"
- manifest `algorithms[]` with `type="page-crop-algorithm"`
- source PDF unchanged

- [ ] **Step 2: Verify Phase 5.2 acceptance**
- A1: algorithms separated to `algorithms/` (tables/ no longer contains algorithm blocks)
- A2: algorithm `type="page-crop-algorithm"` in manifest
- A3: table caption rescan recovered some captions (`caption_source="text-rescan"`)
- A4: source PDF unchanged
- A5: full suite passes

- [ ] **Step 3: Commit (only if test updates)**

---

## Self-Review Notes

**Spec coverage:**
- Algorithm separation (A) -> Task 1 classify + Task 3 dispatcher move.
- Caption rescan (D) -> Task 1 rescan + Task 3 dispatcher call.
- algorithms[] + caption_source -> Task 2 manifest + schema.

**Backward compat:**
- `crop_figures` unchanged.
- `pair_and_merge_multi` unchanged.
- New `postprocess.py` is additive.
- Manifest `algorithms` field new + required; existing manifests without `algorithms` fail schema validation (acceptable - Phase 5.2 always has algorithms[]).
- `Figure.caption_source` optional None - existing figure records unaffected.

**Type consistency:** `classify_table_or_algorithm(text) -> str` ("algorithm"/"table"). `rescan_table_caption(...) -> (LayoutRegion, str)`. `Figure.caption_source` flows from dispatcher to manifest. `algorithms[]` item schema = tables[] item schema + caption_source.

**Risk:** Task 3 Step 3 is the most involved (file move + rename + manifest). The implementer must carefully handle: (a) `all_table_configs` becoming `(config, caption_source)` tuples, (b) file move from `tables/` to `algorithms/` with id rename, (c) `files` path rewrite. Tests cover the happy path; the real-paper smoke (Task 4) verifies on the actual paper.

**Placeholder scan:** complete code in every step. The Task 3 dispatcher change is described as a delta with scoping notes; the implementer reads the current `extract_pdf_figures.py` and applies carefully.
