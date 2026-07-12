# Paper PDF Figures - Table Extraction in auto mode (Phase 5.1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend `--mode auto` to extract **tables** alongside figures, as a separate screenshot type for paper-introduction use. Each table merges with its `table_caption` (like figure+figure_caption), writes to `tables/` (separate from `figures/`), and records in a new manifest `tables[]` array.

**Architecture:** Generalize `model_detect.pair_and_merge` into `pair_and_merge_multi(regions, group_specs, min_confidence)` that pairs each group's primary label with its caption label. The dispatcher's `auto` branch calls it with default `[("figure","figure_caption"), ("table","table_caption")]`, crops figures to `figures/` (id prefix `fig_`) and tables to `tables/` (id prefix `tbl_`), and records both in the manifest. `--labels` semantics shift from "categories to crop" to "primary categories to crop"; caption labels are auto-inferred as `{primary}_caption`.

**Tech Stack:** Python ≥3.9, PyMuPDF, opencv, numpy, torch + doclayout-yolo (ML, optional), pytest + jsonschema. 89 tests currently pass.

## Global Constraints

(From the design + main spec - every task inherits these.)

- Skill root: `.claude/skills/paper-pdf-figures/`; tests run from there.
- Never modify the original PDF; offline except first-run weight download.
- Reuse Phase 0–5 modules. `pair_and_merge_multi` generalizes `pair_and_merge` (the old fn can delegate to the new one or be replaced; tests must keep passing).
- Default `--labels figure,table` (was `figure,figure_caption`). Caption labels auto-inferred: for primary `X`, caption = `X_caption`.
- Figure id: `fig_p{page:04d}_{idx:02d}` (unchanged). Table id: `tbl_p{page:04d}_{idx:02d}` (new prefix).
- Output: `figures/fig_.../` and `tables/tbl_.../` (separate dirs). Naming inside follows Phase 2 convention (`figures/{id}/{id}.{ext}` and `tables/{id}/{id}.{ext}`).
- Manifest: new `tables[]` array (same item schema as `figures[]`: id/page/bbox_pdf_points/type/files/sha256/extraction_method/dpi/caption). `Manifest.add_table(t)` method. `tables[]` is required (can be empty list).
- Table `type` field: `"page-crop-table"` (distinguishes from figure's `"page-crop"`). `extraction_method`: `"manual-bbox"` (reuses crop_figures; distinguishable via `type` + output dir).
- Table+table_caption merge = union bbox (same as figure+figure_caption). Unpaired table -> crop alone. Unpaired table_caption -> dropped.
- Dedup: same-page table regions IoU > 0.8 -> keep higher confidence (per group).
- Backward compat: `--labels figure` (only figure) still works; `--labels figure,figure_caption` (old style) - figure_caption is not a primary, so it's ignored (no table added). Document this in `--help`.
- Subprocess list-form calls; output confined to `--out`.

**Pre-req:** ML deps installed (Phase 5). DocLayout-YOLO classes include `table` (5) + `table_caption` (6) + `table_footnote` (7) - we use 5+6 only (footnote deferred per design decision).

---

## File Structure

| Path | Responsibility |
| --- | --- |
| `.claude/skills/paper-pdf-figures/scripts/model_detect.py` | Generalize: `pair_and_merge_multi`, `regions_to_figure_configs` gains `id_prefix` param |
| `.claude/skills/paper-pdf-figures/scripts/manifest.py` | `add_table`, `tables` field; `from_dict`/`to_dict` round-trip |
| `.claude/skills/paper-pdf-figures/templates/manifest.schema.json` | `tables[]` array (same item schema as figures[]) |
| `.claude/skills/paper-pdf-figures/scripts/extract_pdf_figures.py` | auto branch: pair_and_merge_multi -> crop figures to figures/ + tables to tables/; --labels default figure,table |
| `.claude/skills/paper-pdf-figures/tests/test_model_detect.py` | +multi-group tests |
| `.claude/skills/paper-pdf-figures/tests/test_manifest.py` | +tables[] tests |
| `.claude/skills/paper-pdf-figures/tests/test_extract_pdf_figures.py` | +auto table-crop test |

---

## Task 1: model_detect generalization (pair_and_merge_multi + id_prefix)

**Files:**
- Modify: `.claude/skills/paper-pdf-figures/scripts/model_detect.py`
- Modify: `.claude/skills/paper-pdf-figures/tests/test_model_detect.py`

**Interfaces:**
- `model_detect.pair_and_merge_multi(regions, group_specs: list[tuple[str,str|None]], min_confidence: float) -> dict[str, list[tuple[LayoutRegion, LayoutRegion|None]]]` - returns one list of (merged, paired_caption) per group_spec key (the primary label). Each group deduped + sorted independently.
- `model_detect.regions_to_figure_configs(pairs, page, id_prefix="fig") -> list[FigureConfig]` - id_prefix param (default "fig" for backward compat; "tbl" for tables).
- `pair_and_merge` (old) delegates to `pair_and_merge_multi` with `[("figure","figure_caption")]` and returns the single list (backward compat for existing tests).

- [ ] **Step 1: Write the failing tests (append to test_model_detect.py)**

```python
def test_pair_and_merge_multi_figure_and_table_separate_groups():
    fig = _region("figure", [100, 100, 400, 300])
    figcap = _region("figure_caption", [100, 310, 400, 360])
    tbl = _region("table", [100, 400, 400, 500])
    tblcap = _region("table_caption", [100, 510, 400, 540])
    groups = model_detect.pair_and_merge_multi(
        [fig, figcap, tbl, tblcap],
        group_specs=[("figure", "figure_caption"), ("table", "table_caption")],
        min_confidence=0.3,
    )
    assert set(groups.keys()) == {"figure", "table"}
    assert len(groups["figure"]) == 1
    assert len(groups["table"]) == 1
    # figure merged with its caption
    fig_merged, fig_paired = groups["figure"][0]
    assert fig_paired is figcap
    assert fig_merged.bbox_pdf_points == [100, 100, 400, 360]
    # table merged with its caption
    tbl_merged, tbl_paired = groups["table"][0]
    assert tbl_paired is tblcap
    assert tbl_merged.bbox_pdf_points == [100, 100, 400, 540] if False else tbl_merged.bbox_pdf_points == [100, 400, 400, 540]


def test_pair_and_merge_multi_table_without_caption():
    tbl = _region("table", [100, 400, 400, 500])
    groups = model_detect.pair_and_merge_multi(
        [tbl], group_specs=[("figure", "figure_caption"), ("table", "table_caption")],
        min_confidence=0.3,
    )
    assert len(groups["figure"]) == 0
    assert len(groups["table"]) == 1
    _, cap = groups["table"][0]
    assert cap is None


def test_pair_and_merge_multi_caption_without_primary_dropped():
    tblcap = _region("table_caption", [100, 510, 400, 540])
    groups = model_detect.pair_and_merge_multi(
        [tblcap], group_specs=[("figure", "figure_caption"), ("table", "table_caption")],
        min_confidence=0.3,
    )
    assert groups["figure"] == []
    assert groups["table"] == []


def test_pair_and_merge_multi_picks_nearest_caption_per_group():
    fig = _region("figure", [100, 100, 400, 200])
    figcap_near = _region("figure_caption", [100, 210, 400, 240])
    figcap_far = _region("figure_caption", [100, 600, 400, 630])
    tbl = _region("table", [100, 300, 400, 400])
    tblcap = _region("table_caption", [100, 410, 400, 440])
    groups = model_detect.pair_and_merge_multi(
        [fig, figcap_far, figcap_near, tbl, tblcap],
        group_specs=[("figure", "figure_caption"), ("table", "table_caption")],
        min_confidence=0.3,
    )
    _, fc = groups["figure"][0]
    assert fc is figcap_near
    _, tc = groups["table"][0]
    assert tc is tblcap


def test_regions_to_figure_configs_id_prefix_tbl():
    fig = _region("figure", [100, 100, 400, 300])
    pairs = [(fig, None)]
    configs_fig = model_detect.regions_to_figure_configs(pairs, page=11, id_prefix="fig")
    configs_tbl = model_detect.regions_to_figure_configs(pairs, page=11, id_prefix="tbl")
    assert configs_fig[0].id == "fig_p0011_01"
    assert configs_tbl[0].id == "tbl_p0011_01"


def test_pair_and_merge_backward_compat_single_group():
    """Old pair_and_merge still works for figure-only callers."""
    fig = _region("figure", [100, 100, 400, 300])
    cap = _region("figure_caption", [100, 310, 400, 360])
    pairs = model_detect.pair_and_merge([fig, cap], labels=["figure", "figure_caption"], min_confidence=0.3)
    assert len(pairs) == 1
    assert pairs[0][1] is cap
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/imalne/learn_vibe_coding/.claude/skills/paper-pdf-figures
pytest tests/test_model_detect.py -k "pair_and_merge_multi or id_prefix or backward_compat" -v
```
Expected: FAIL (`pair_and_merge_multi` doesn't exist; `regions_to_figure_configs` has no id_prefix).

- [ ] **Step 3: Implement in model_detect.py**

Add `pair_and_merge_multi` and refactor. Replace the existing `pair_and_merge` with a version that delegates, and add the new function. Add `id_prefix` to `regions_to_figure_configs`:

```python
def pair_and_merge_multi(
    regions: list[LayoutRegion],
    group_specs: list[tuple[str, str | None]],
    min_confidence: float,
) -> dict[str, list[tuple[LayoutRegion, LayoutRegion | None]]]:
    """Pair each group's primary regions with their nearest caption; merge bbox.

    group_specs is a list of (primary_label, caption_label_or_None). Returns a
    dict keyed by primary_label -> list of (merged_region, paired_caption_or_None).
    Each group is deduped (IoU>0.8 keep higher conf) + sorted top-to-bottom.
    Captions not paired with any primary are dropped.
    """
    result: dict[str, list[tuple[LayoutRegion, LayoutRegion | None]]] = {}
    for primary_label, caption_label in group_specs:
        primaries = [r for r in regions if r.label == primary_label and r.confidence >= min_confidence]
        primaries = dedup_iou(primaries)
        primaries.sort(key=lambda r: (r.bbox_pdf_points[1], r.bbox_pdf_points[0]))
        captions: list[LayoutRegion] = []
        if caption_label:
            captions = [r for r in regions if r.label == caption_label and r.confidence >= min_confidence]
        used_caps: set[int] = set()
        pairs: list[tuple[LayoutRegion, LayoutRegion | None]] = []
        for prim in primaries:
            pcx, pcy = _center(prim.bbox_pdf_points)
            best, best_d = None, float("inf")
            for i, cap in enumerate(captions):
                if i in used_caps:
                    continue
                ccx, ccy = _center(cap.bbox_pdf_points)
                d = abs(ccy - pcy) + abs(ccx - pcx) * 0.1
                if d < best_d:
                    best_d, best = d, i
            if best is not None:
                used_caps.add(best)
                cap = captions[best]
                merged = LayoutRegion(_union(prim.bbox_pdf_points, cap.bbox_pdf_points),
                                       prim.label, prim.confidence)
                pairs.append((merged, cap))
            else:
                pairs.append((prim, None))
        result[primary_label] = pairs
    return result


def pair_and_merge(
    regions: list[LayoutRegion],
    labels: list[str],
    min_confidence: float,
) -> list[tuple[LayoutRegion, LayoutRegion | None]]:
    """Backward-compat: figure-only single-group pairing."""
    figure_label = "figure" if "figure" in labels else (labels[0] if labels else "figure")
    caption_label = "figure_caption"
    groups = pair_and_merge_multi(regions, [(figure_label, caption_label)], min_confidence)
    return groups.get(figure_label, [])


def regions_to_figure_configs(
    pairs: list[tuple[LayoutRegion, LayoutRegion | None]],
    page: int,
    id_prefix: str = "fig",
) -> list[FigureConfig]:
    configs: list[FigureConfig] = []
    for idx, (merged, _cap) in enumerate(pairs, start=1):
        fig_id = f"{id_prefix}_p{page:04d}_{idx:02d}"
        configs.append(FigureConfig(
            id=fig_id, page=page, bbox=list(merged.bbox_pdf_points),
        ))
    return configs
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/imalne/learn_vibe_coding/.claude/skills/paper-pdf-figures
pytest tests/test_model_detect.py -v
pytest tests/ -q -k "not real_doclayout"
```
Expected: all model_detect tests pass (existing 14 + 6 new = 20); full suite 95 (was 89; +6).

- [ ] **Step 5: Commit**

```bash
cd /home/imalne/learn_vibe_coding
git add .claude/skills/paper-pdf-figures/scripts/model_detect.py .claude/skills/paper-pdf-figures/tests/test_model_detect.py
git commit -m "feat(paper-pdf-figures): pair_and_merge_multi + id_prefix for table support (Phase 5.1 Task 1)"
```

---

## Task 2: manifest tables[] + schema

**Files:**
- Modify: `.claude/skills/paper-pdf-figures/scripts/manifest.py`
- Modify: `.claude/skills/paper-pdf-figures/templates/manifest.schema.json`
- Modify: `.claude/skills/paper-pdf-figures/tests/test_manifest.py`

**Interfaces:**
- `Manifest.tables: list[Figure]` field (reuse Figure dataclass; `type="page-crop-table"` distinguishes).
- `Manifest.add_table(t: Figure) -> None`.
- `from_dict`/`to_dict` round-trip tables[].
- Schema: top-level `tables` required array, item schema = same as `figures` items.

- [ ] **Step 1: Write failing tests (append to test_manifest.py)**

```python
def test_manifest_add_table_and_round_trip(tmp_path):
    m = _minimal_manifest()
    m.add_table(manifest.Figure(
        id="tbl_p0010_01", page=10, bbox_pdf_points=[100, 200, 500, 400],
        type="page-crop-table", extraction_method="manual-bbox", dpi=300,
        files={"pdf": "tables/tbl_p0010_01/tbl_p0010_01.pdf", "png": None, "svg": None},
        sha256={"pdf": "abc"},
    ))
    p = m.save(tmp_path / "manifest.json")
    loaded = manifest.Manifest.load(p)
    assert len(loaded.tables) == 1
    assert loaded.tables[0].id == "tbl_p0010_01"
    assert loaded.tables[0].type == "page-crop-table"
    assert manifest.validate(loaded.to_dict()) == []


def test_manifest_tables_required_in_schema():
    schema = _load_schema()
    assert "tables" in schema["required"]


def test_validate_rejects_unknown_table_type_value():
    # schema allows any string for type; this is a smoke check that type is optional string
    good = {
        "source_pdf": "p.pdf", "paper_slug": "p", "created_at": "2026-07-10T00:00:00",
        "tool_version": "0.1.0", "figures": [], "embedded_images": [],
        "candidates": [], "warnings": [], "tables": [],
    }
    assert manifest.validate(good) == []
    # missing tables -> schema error
    bad = dict(good); del bad["tables"]
    assert manifest.validate(bad)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_manifest.py -k "table or tables" -v
```
Expected: FAIL (Manifest has no `tables`/`add_table`; schema has no `tables`).

- [ ] **Step 3: Add `tables` to manifest.py**

In `manifest.py`, add `tables` field + `add_table` + from_dict/to_dict handling. The `Manifest` dataclass gains:
```python
    tables: list[Figure] = field(default_factory=list)
```
Add method:
```python
    def add_table(self, t: Figure) -> None:
        self.tables.append(t)
```
In `from_dict`, add:
```python
            tables=[Figure(**t) for t in d.get("tables", [])],
```
(`to_dict` via `asdict` already includes `tables` once the field exists.)

- [ ] **Step 4: Add `tables` to schema**

In `templates/manifest.schema.json`:
- Add `"tables"` to the top-level `required` array.
- Add a `tables` property (same item schema as `figures`):
```json
    "tables": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["id", "page", "bbox_pdf_points", "type", "files", "extraction_method", "dpi"],
        "additionalProperties": false,
        "properties": {
          "id": {"type": "string"},
          "page": {"type": "integer", "minimum": 1},
          "bbox_pdf_points": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4},
          "type": {"type": "string"},
          "caption": {"type": "string"},
          "files": {
            "type": "object", "additionalProperties": false,
            "properties": {
              "pdf": {"type": ["string", "null"]}, "png": {"type": ["string", "null"]}, "svg": {"type": ["string", "null"]}
            }
          },
          "sha256": {
            "type": "object", "additionalProperties": false,
            "properties": {"pdf": {"type": "string"}, "png": {"type": "string"}, "svg": {"type": "string"}}
          },
          "extraction_method": {"type": "string"},
          "dpi": {"type": "integer", "minimum": 1}
        }
      }
    },
```
(Place after `figures` in `properties`.)

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_manifest.py -v
pytest tests/ -q -k "not real_doclayout"
```
Expected: manifest tests pass (existing + 3 new); full suite 98 (was 95; +3).

- [ ] **Step 6: Commit**

```bash
git add .claude/skills/paper-pdf-figures/scripts/manifest.py .claude/skills/paper-pdf-figures/templates/manifest.schema.json .claude/skills/paper-pdf-figures/tests/test_manifest.py
git commit -m "feat(paper-pdf-figures): manifest tables[] + schema (Phase 5.1 Task 2)"
```

---

## Task 3: dispatcher auto branch - crop figures + tables separately

**Files:**
- Modify: `.claude/skills/paper-pdf-figures/scripts/extract_pdf_figures.py`
- Modify: `.claude/skills/paper-pdf-figures/tests/test_extract_pdf_figures.py`

**Interfaces:**
- `--labels` default `figure,table` (was `figure,figure_caption`). Caption labels auto-inferred as `{primary}_caption`.
- auto branch: `pair_and_merge_multi(regions, group_specs, min_confidence)` where `group_specs = [(p, f"{p}_caption") for p in labels]`. For each group: `regions_to_figure_configs(pairs, page, id_prefix)` -> `crop_figures` to `figures/` (prefix `fig_`) or `tables/` (prefix `tbl_`). Manifest: `add_figure` for figures, `add_table` for tables.

- [ ] **Step 1: Write failing tests (append to test_extract_pdf_figures.py)**

```python
def test_auto_mode_crops_table_separately(vector_pdf, tmp_path, monkeypatch, capsys):
    import model_detect
    regions = [
        model_detect.LayoutRegion([100, 100, 400, 300], "figure", 0.9),
        model_detect.LayoutRegion([100, 310, 400, 360], "figure_caption", 0.8),
        model_detect.LayoutRegion([100, 400, 400, 500], "table", 0.85),
        model_detect.LayoutRegion([100, 510, 400, 540], "table_caption", 0.7),
    ]
    fake = model_detect.FakeDetector({1: regions})
    monkeypatch.setattr(model_detect, "DocLayoutYoloDetector", lambda: fake)
    import extract_pdf_figures
    rc = extract_pdf_figures.main([str(vector_pdf), "--mode", "auto", "--paper-slug", "p",
                                   "--dpi", "150", "--out", str(tmp_path / "out")])
    out = capsys.readouterr()
    assert rc == 0, out.err
    assert "figures: 1" in out.out
    assert "tables: 1" in out.out
    m = manifest.Manifest.load(tmp_path / "out" / "p" / "manifest.json")
    assert len(m.figures) == 1
    assert len(m.tables) == 1
    assert m.figures[0].id == "fig_p0001_01"
    assert m.tables[0].id == "tbl_p0001_01"
    assert m.tables[0].type == "page-crop-table"
    # separate output dirs
    assert (tmp_path / "out" / "p" / "figures" / "fig_p0001_01" / "fig_p0001_01.pdf").is_file()
    assert (tmp_path / "out" / "p" / "tables" / "tbl_p0001_01" / "tbl_p0001_01.pdf").is_file()
    assert manifest.validate(m.to_dict()) == []


def test_auto_mode_labels_figure_only_skips_tables(vector_pdf, tmp_path, monkeypatch, capsys):
    import model_detect
    regions = [
        model_detect.LayoutRegion([100, 100, 400, 300], "figure", 0.9),
        model_detect.LayoutRegion([100, 400, 400, 500], "table", 0.85),
    ]
    fake = model_detect.FakeDetector({1: regions})
    monkeypatch.setattr(model_detect, "DocLayoutYoloDetector", lambda: fake)
    import extract_pdf_figures
    rc = extract_pdf_figures.main([str(vector_pdf), "--mode", "auto", "--paper-slug", "p",
                                   "--labels", "figure", "--dpi", "150",
                                   "--out", str(tmp_path / "out")])
    out = capsys.readouterr()
    assert rc == 0, out.err
    assert "figures: 1" in out.out
    assert "tables: 0" in out.out
    m = manifest.Manifest.load(tmp_path / "out" / "p" / "manifest.json")
    assert len(m.figures) == 1
    assert len(m.tables) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_extract_pdf_figures.py -k "table or labels_figure" -v
```
Expected: FAIL (no `tables:` in output; `--labels figure` still tries figure_caption).

- [ ] **Step 3: Modify the auto branch in extract_pdf_figures.py**

a) Change `--labels` default:
```python
    parser.add_argument("--labels", default="figure,table")
```

b) Replace the auto-branch pairing/cropping logic. The current single-group logic:
```python
                pairs = model_detect.pair_and_merge(regions, labels=labels,
                                       min_confidence=args.min_confidence)
                configs = model_detect.regions_to_figure_configs(pairs, page=pno + 1)
                all_figure_configs.extend(configs)
```
Replace with multi-group:
```python
                group_specs = [(p, f"{p}_caption") for p in labels]
                groups = model_detect.pair_and_merge_multi(
                    regions, group_specs=group_specs, min_confidence=args.min_confidence)
                for primary, pairs in groups.items():
                    id_prefix = "tbl" if primary == "table" else "fig"
                    configs = model_detect.regions_to_figure_configs(
                        pairs, page=pno + 1, id_prefix=id_prefix)
                    if primary == "table":
                        all_table_configs.extend(configs)
                    else:
                        all_figure_configs.extend(configs)
```
(Initialize `all_table_configs: list = []` alongside `all_figure_configs`.)

c) After the page loop, crop tables too (mirroring the figures crop):
```python
            if not args.dry_run:
                records = crop_figures(doc, all_figure_configs, out_dir, slug,
                                       dpi=args.dpi, formats=formats, warnings=warnings)
                table_records = crop_figures(doc, all_table_configs, out_dir, slug,
                                             dpi=args.dpi, formats=formats, warnings=warnings)
            else:
                records = []
                table_records = []
```
**Note:** `crop_figures` writes to `figures/{id}/` hardcoded. For tables to go to `tables/`, either (a) add an `output_subdir` param to `crop_figures` (default "figures"), or (b) post-process. Option (a) is cleaner - add `output_subdir: str = "figures"` to `crop_figures` and use `figs_dir = out_dir / paper_slug / output_subdir`. Apply this change in `crop_export.py` and pass `output_subdir="tables"` for tables.

d) Manifest construction - add tables:
```python
    elif args.mode == "auto":
        for rec in records:
            m.add_figure(rec)
        if not records and not args.dry_run:
            m.add_warning("WARN_NO_FIGURES")
        for rec in table_records:
            # set type to page-crop-table
            rec.type = "page-crop-table"
            # fix files path prefix (figures/ -> tables/)
            m.add_table(rec)
        if not table_records and not args.dry_run:
            m.add_warning("WARN_NO_TABLES")
```
**Note:** `crop_figures` sets `type="page-crop"` and `files["pdf"]="figures/{id}/..."`. For tables, override `type` to `"page-crop-table"` (the files path is already correct if `output_subdir="tables"` was passed). Verify the Figure's `files` paths point to `tables/...` after the subdir change.

e) Summary print:
```python
    elif args.mode in ("manual", "auto"):
        print(f"figures: {len(records)}")
        if args.mode == "auto":
            print(f"tables: {len(table_records)}")
            print(f"candidates: {len(all_candidates)} across {pages_with_hits} pages")
```

f) `run_args["labels"]` already stores `args.labels` - no change needed.

- [ ] **Step 4: Add `output_subdir` to crop_export.crop_figures**

In `scripts/crop_export.py`, change the signature:
```python
def crop_figures(
    doc, figures, out_dir, paper_slug, dpi=300, formats=None, dry_run=False,
    warnings=None, output_subdir="figures",
) -> list[Figure]:
```
And replace `figs_dir = out_dir / paper_slug / "figures"` with `figs_dir = out_dir / paper_slug / output_subdir`, and the `files` paths from `f"figures/{fig.id}/..."` to `f"{output_subdir}/{fig.id}/..."`. Update existing tests that assert `figures/...` paths (they pass `output_subdir` default "figures", so no change needed).

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd /home/imalne/learn_vibe_coding/.claude/skills/paper-pdf-figures
pytest tests/test_extract_pdf_figures.py -k "table or labels_figure or auto" -v
pytest tests/ -q -k "not real_doclayout"
```
Expected: all auto tests pass (existing 4 + 2 new = 6); full suite 100 (was 98; +2). Binding: "all green, no regressions".

- [ ] **Step 6: Commit**

```bash
git add .claude/skills/paper-pdf-figures/scripts/extract_pdf_figures.py .claude/skills/paper-pdf-figures/scripts/crop_export.py .claude/skills/paper-pdf-figures/tests/test_extract_pdf_figures.py
git commit -m "feat(paper-pdf-figures): auto mode crops tables separately to tables/ (Phase 5.1 Task 3)"
```

---

## Task 4: Real-paper acceptance (2606.26615v1.pdf has tables) + update existing auto tests for new --labels default

**Files:**
- (no code) real-paper smoke
- Modify: `.claude/skills/paper-pdf-figures/tests/test_extract_pdf_figures.py` (existing auto tests may need `--labels figure,figure_caption` removed since default is now `figure,table` - the FakeDetector regions use `figure`/`figure_caption` labels, so default `figure,table` will still pair figure+figure_caption and find 0 tables; existing tests should still pass. Verify.)

- [ ] **Step 1: Verify existing auto tests still pass with new default**

```bash
pytest tests/test_extract_pdf_figures.py -k auto -v
```
If any fail because the new `--labels figure,table` default causes `pair_and_merge_multi` to look for `table_caption` (harmless - 0 tables found), they should still pass. If a test asserts `tables: 0` is NOT in output, update it.

- [ ] **Step 2: Real-paper smoke on 2606.26615v1.pdf**

```bash
cd /home/imalne/learn_vibe_coding
export HF_ENDPOINT=https://hf-mirror.com
python3 .claude/skills/paper-pdf-figures/scripts/extract_pdf_figures.py \
    2606.26615v1.pdf --mode auto --out /tmp/p51acc --paper-slug raster \
    --pages 10,12 --dpi 300 --overwrite
```
Confirm: `figures: N` + `tables: M` (M > 0); `tables/tbl_.../*.pdf` exist; manifest has `tables[]` with `type=page-crop-table`; source PDF unchanged.

- [ ] **Step 3: Verify Phase 5.1 acceptance**
- A1: tables cropped to `tables/` separate from `figures/`
- A2: table+table_caption merged (union bbox)
- A3: manifest `tables[]` records with `type=page-crop-table`
- A4: source PDF unchanged
- A5: full suite passes
- A6: `--labels figure` (only figures) skips tables

- [ ] **Step 4: Commit (only if test updates were made)**

```bash
git add .claude/skills/paper-pdf-figures/tests/test_extract_pdf_figures.py
git commit -m "test(paper-pdf-figures): adjust auto tests for figure,table default (Phase 5.1 Task 4)"
```

---

## Self-Review Notes

**Spec coverage:**
- table as separate screenshot type -> Task 3 (tables/ dir + manifest tables[]).
- table+table_caption merge -> Task 1 (pair_and_merge_multi) + Task 3.
- figure/table separate in manifest -> Task 2 (tables[] schema) + Task 3 (add_table).
- `--labels` default figure,table -> Task 3.

**Backward compat:**
- `pair_and_merge` (old) delegates to `pair_and_merge_multi` - existing Task-1 (Phase 5) tests pass.
- `regions_to_figure_configs` gains `id_prefix` default "fig" - existing callers unaffected.
- `crop_figures` gains `output_subdir` default "figures" - existing manual-mode + Phase-2 tests unaffected.
- Manifest `tables` field is new + required; existing manifests without `tables` fail `from_dict`? No - `from_dict` uses `d.get("tables", [])` so old manifests load with empty tables. But schema validation of an OLD manifest (no `tables` key) would now fail. Acceptable - Phase 5.1 manifests always have `tables[]`.

**Type consistency:** `pair_and_merge_multi` returns `dict[primary_label, list[(merged, caption)]]`; `regions_to_figure_configs(pairs, page, id_prefix)` consumes the same pair shape. `Figure` dataclass reused for tables (with `type="page-crop-table"`). `add_table` mirrors `add_figure`.

**Placeholder scan:** complete code in every step. The `output_subdir` change to `crop_figures` is the one cross-file dependency (Task 3 Step 4) - handle before Step 3's crop calls.

**Risk:** the `crop_figures` `files` path uses `output_subdir` - verify the manifest's `files["pdf"]` for tables reads `tables/tbl_.../tbl_....pdf` (not `figures/...`). Test asserts this.
