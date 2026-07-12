# Paper PDF Figures - Phase 5 (Model-Detection Auto-Crop) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `--mode auto`: use DocLayout-YOLO to detect figure + figure_caption regions per page, merge each figure with its nearest caption into one bbox, and crop vector PDF + PNG via the existing `crop_figures` - fully automatic, no hand-written config.yaml.

**Architecture:** `model_detect.py` defines a `LayoutDetector` protocol + `DocLayoutYoloDetector` (default) + `LayoutRegion` dataclass. The dispatcher's new `auto` branch: load detector (download weights to a configurable dir on first run), per page call `detect()` -> filter by `--labels` + `--min-confidence` -> pair each figure with nearest caption -> merge bbox -> build `FigureConfig` list -> reuse Phase 2 `crop_figures`. Heuristic `figure_detect.py` (Phase 4) is untouched and still serves `--mode detect` for ML-less environments.

**Tech Stack:** Python ≥3.9, PyMuPDF, opencv, numpy, **torch + doclayout-yolo** (ML, optional via `requirements-ml.txt`), pytest + jsonschema. RTX 5070 Ti available; `--device auto` picks CUDA.

## Global Constraints

(From the spec `paper-pdf-figure/docs/designs/2026-07-07-paper-pdf-figures-phase5-model-detect.md` + main design - every task inherits these.)

- Skill root: `.claude/skills/paper-pdf-figures/`; tests run from there: `cd .claude/skills/paper-pdf-figures && pytest tests/ -v`
- Never modify the original PDF; offline except first-run weight download.
- Reuse Phase 0–4 modules: `manifest.py` (`Manifest`, `Figure`, `Candidate`, `validate`), `crop_export.py` (`crop_figures`, `FigureConfig`), `extract_pdf_figures.py` (extend dispatcher). Do not duplicate.
- ML deps are **optional**: `requirements-ml.txt` (torch + doclayout-yolo) is separate from `requirements.txt`. `auto` mode missing ML deps -> clean `ERROR: --mode auto requires ML backend; pip install -r requirements-ml.txt`, exit 1 (no fallback to heuristic).
- **Weights directory** (3-level priority): `--weights-dir` arg > `PAPER_PDF_FIGURES_WEIGHTS_DIR` env var > default `<skill_root>/models/`. `models/` is gitignored. First run downloads weights there; never `~/.cache`.
- `LayoutRegion(bbox_pdf_points: list[float], label: str, confidence: float)` - PDF-point bbox, label from DocLayout-YOLO classes (`figure`, `figure_caption`, `table`, ...), confidence 0..1.
- Figure-caption pairing: each figure pairs with nearest `figure_caption` on the same page (vertical center distance; caption below figure preferred). Merge = union bbox. Unpaired figure -> crop alone. Unpaired caption -> ignored.
- Dedup: same-page figure regions with IoU > 0.8 -> keep higher confidence.
- Figure id: `fig_p{page:04d}_{idx:02d}` (idx = top-to-bottom, left-to-right order on the page).
- Default `--labels figure,figure_caption`; `--min-confidence 0.3`; `--device auto`; detection dpi 150.
- `auto` mode default = crop directly; `--dry-run` = candidates + previews only, no crop, no `figures/`.
- Subprocess list-form calls; sanitize nothing user-supplied into a shell; output confined to `--out`.

**Pre-req:** ML deps installed (`pip install -r requirements-ml.txt`). `check_deps.py` reports `[OK] torch` + `[OK] doclayout-yolo`. API verified on the real vector paper before writing each task's code.

---

## File Structure

Phase 5 creates/modifies these files.

| Path | Responsibility |
| --- | --- |
| `.claude/skills/paper-pdf-figures/requirements-ml.txt` | torch + doclayout-yolo (optional) |
| `.claude/skills/paper-pdf-figures/scripts/model_detect.py` | `LayoutRegion`, `LayoutDetector` protocol, `DocLayoutYoloDetector`, pairing/merge/dedup helpers, weight-dir resolution |
| `.claude/skills/paper-pdf-figures/scripts/check_deps.py` | Modify: add torch + doclayout-yolo (optional, block auto) |
| `.claude/skills/paper-pdf-figures/scripts/install_deps.sh` | Modify: add `--ml` flag |
| `.claude/skills/paper-pdf-figures/scripts/extract_pdf_figures.py` | Modify: add `auto` branch + `--weights-dir`/`--device`/`--min-confidence`/`--labels`/`--apply` args |
| `.claude/skills/paper-pdf-figures/scripts/figure_detect.py` | Modify `draw_candidates_preview` to optionally label regions (or add a sibling fn) |
| `.claude/skills/paper-pdf-figures/templates/manifest.schema.json` | Modify: candidates +`label`/`confidence` (optional) |
| `.claude/skills/paper-pdf-figures/.gitignore` (or root) | `models/` |
| `.claude/skills/paper-pdf-figures/tests/test_model_detect.py` | Unit tests (FakeDetector; no weight download) |
| `.claude/skills/paper-pdf-figures/tests/test_extract_pdf_figures.py` | +auto integration tests (FakeDetector) |

`crop_export.py`, `extract_embedded.py`, `manifest.py` reused (manifest gets schema-only change).

---

## Task 1: model_detect.py + ML deps + weight-dir resolution

**Files:**
- Create: `.claude/skills/paper-pdf-figures/requirements-ml.txt`
- Create: `.claude/skills/paper-pdf-figures/scripts/model_detect.py`
- Modify: `.claude/skills/paper-pdf-figures/scripts/check_deps.py`
- Modify: `.claude/skills/paper-pdf-figures/scripts/install_deps.sh`
- Create: `.claude/skills/paper-pdf-figures/tests/test_model_detect.py`

**Interfaces:**
- `model_detect.LayoutRegion(bbox_pdf_points, label, confidence)` dataclass.
- `model_detect.resolve_weights_dir(weights_dir_arg: str | None) -> Path` - 3-level priority.
- `model_detect.pair_and_merge(regions, labels, min_confidence) -> list[tuple[LayoutRegion, LayoutRegion | None]]` - each figure paired with nearest caption (or None); non-figure labels ignored as "figures".
- `model_detect.dedup_iou(regions, iou_threshold=0.8) -> list[LayoutRegion]` - keep higher confidence.
- `model_detect.regions_to_figure_configs(pairs, dpi) -> list[FigureConfig]` - merged bbox -> FigureConfig with id `fig_p{page:04d}_{idx:02d}`.
- `model_detect.LayoutDetector` Protocol + `DocLayoutYoloDetector(weights_dir, device)` - `load()`, `detect(page, dpi=150) -> list[LayoutRegion]`.
- `model_detect.FakeDetector(regions_per_page)` - test double.

- [ ] **Step 1: Write `requirements-ml.txt`**

File `.claude/skills/paper-pdf-figures/requirements-ml.txt`:
```
torch>=2.1.0
doclayout-yolo>=0.0.4
huggingface_hub>=0.20.0
```

- [ ] **Step 2: Write the failing tests**

File `.claude/skills/paper-pdf-figures/tests/test_model_detect.py`:
```python
import os
from pathlib import Path

import fitz
import pytest

import model_detect


def _region(label, bbox, conf=0.9):
    return model_detect.LayoutRegion(
        bbox_pdf_points=list(bbox), label=label, confidence=conf)


def test_layout_region_fields():
    r = _region("figure", [0, 0, 10, 10], 0.5)
    assert r.label == "figure"
    assert r.bbox_pdf_points == [0, 0, 10, 10]
    assert r.confidence == 0.5


def test_resolve_weights_dir_arg_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("PAPER_PDF_FIGURES_WEIGHTS_DIR", "/from-env")
    assert model_detect.resolve_weights_dir(str(tmp_path / "from-arg")) == tmp_path / "from-arg"


def test_resolve_weights_dir_env_fallback(monkeypatch, tmp_path):
    monkeypatch.setenv("PAPER_PDF_FIGURES_WEIGHTS_DIR", str(tmp_path / "from-env"))
    assert model_detect.resolve_weights_dir(None) == tmp_path / "from-env"


def test_resolve_weights_dir_default(monkeypatch, tmp_path):
    monkeypatch.delenv("PAPER_PDF_FIGURES_WEIGHTS_DIR", raising=False)
    # default = <skill_root>/models
    result = model_detect.resolve_weights_dir(None)
    assert result.name == "models"
    assert result.parent.name == "paper-pdf-figures"


def test_pair_and_merge_figure_with_caption_below():
    fig = _region("figure", [100, 100, 400, 300])
    cap = _region("figure_caption", [100, 310, 400, 360])
    pairs = model_detect.pair_and_merge([fig, cap], labels=["figure", "figure_caption"], min_confidence=0.3)
    assert len(pairs) == 1
    merged, paired_cap = pairs[0]
    assert paired_cap is cap
    # union bbox
    assert merged.bbox_pdf_points == [100, 100, 400, 360]


def test_pair_and_merge_figure_without_caption():
    fig = _region("figure", [100, 100, 400, 300])
    pairs = model_detect.pair_and_merge([fig], labels=["figure", "figure_caption"], min_confidence=0.3)
    assert len(pairs) == 1
    _, cap = pairs[0]
    assert cap is None


def test_pair_and_merge_caption_without_figure_ignored():
    cap = _region("figure_caption", [100, 310, 400, 360])
    pairs = model_detect.pair_and_merge([cap], labels=["figure", "figure_caption"], min_confidence=0.3)
    assert pairs == []


def test_pair_and_merge_picks_nearest_caption():
    fig = _region("figure", [100, 100, 400, 200])
    cap_near = _region("figure_caption", [100, 210, 400, 240], conf=0.8)
    cap_far = _region("figure_caption", [100, 500, 400, 530], conf=0.8)
    pairs = model_detect.pair_and_merge([fig, cap_far, cap_near],
                                        labels=["figure", "figure_caption"], min_confidence=0.3)
    assert len(pairs) == 1
    _, cap = pairs[0]
    assert cap is cap_near


def test_pair_and_merge_caption_above_figure_still_paired():
    # caption above figure (less common) still pairs if nearest
    cap = _region("figure_caption", [100, 50, 400, 90])
    fig = _region("figure", [100, 100, 400, 300])
    pairs = model_detect.pair_and_merge([cap, fig],
                                        labels=["figure", "figure_caption"], min_confidence=0.3)
    assert len(pairs) == 1
    _, paired = pairs[0]
    assert paired is cap


def test_min_confidence_filters_low():
    fig_low = _region("figure", [100, 100, 400, 300], conf=0.2)
    fig_ok = _region("figure", [100, 400, 400, 600], conf=0.8)
    pairs = model_detect.pair_and_merge([fig_low, fig_ok],
                                        labels=["figure", "figure_caption"], min_confidence=0.3)
    assert len(pairs) == 1


def test_dedup_iou_keeps_higher_confidence():
    a = _region("figure", [100, 100, 400, 300], conf=0.9)
    b = _region("figure", [105, 105, 405, 305], conf=0.7)  # near-duplicate
    result = model_detect.dedup_iou([a, b], iou_threshold=0.8)
    assert len(result) == 1
    assert result[0].confidence == 0.9


def test_dedup_iou_keeps_distinct():
    a = _region("figure", [100, 100, 200, 200])
    b = _region("figure", [300, 300, 400, 400])
    result = model_detect.dedup_iou([a, b], iou_threshold=0.8)
    assert len(result) == 2


def test_regions_to_figure_configs_ids_and_merge():
    fig = _region("figure", [100, 100, 400, 300])
    cap = _region("figure_caption", [100, 310, 400, 360])
    pairs = model_detect.pair_and_merge([fig, cap], labels=["figure", "figure_caption"], min_confidence=0.3)
    configs = model_detect.regions_to_figure_configs(pairs, page=11)
    assert len(configs) == 1
    assert configs[0].id == "fig_p0011_01"
    assert configs[0].page == 11
    assert configs[0].bbox == [100, 100, 400, 360]


class _FakePage:
    def __init__(self, width=612, height=792):
        self.rect = fitz.Rect(0, 0, width, height)


def test_fake_detector_returns_regions():
    regions = [_region("figure", [100, 100, 400, 300])]
    det = model_detect.FakeDetector({1: regions})
    det.load(Path("/tmp"), "cpu")
    page = _FakePage()
    result = det.detect(page, dpi=150)
    assert result == regions


def test_real_doclayout_detector_smoke(vector_pdf, tmp_path):
    """Real DocLayout-YOLO on a vector page. Skipped if ML deps missing.

    Downloads the real `hantian/yolo` model on first run (~tens of MB) and
    may take 30s+; this is the only real-model test in the suite.
    """
    try:
        import torch  # noqa: F401
        from doclayout_yolo import YOLOv10  # noqa: F401
        import huggingface_hub  # noqa: F401
    except ImportError:
        import pytest
        pytest.skip("ML backend not installed")
    import fitz
    det = model_detect.DocLayoutYoloDetector()
    det.load(tmp_path / "weights", "cpu")
    doc = fitz.open(str(vector_pdf))
    regions = det.detect(doc[0], dpi=150)
    doc.close()
    assert isinstance(regions, list)
    # the vector_pdf fixture has drawn shapes; model may or may not find "figure"
    # but the call must not raise and must return LayoutRegion instances
    for r in regions:
        assert isinstance(r, model_detect.LayoutRegion)
        assert r.label  # non-empty string
        assert 0 <= r.confidence <= 1
```

- [ ] **Step 3: Run tests to verify they fail**

Run:
```bash
cd /home/imalne/learn_vibe_coding/.claude/skills/paper-pdf-figures
pytest tests/test_model_detect.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'model_detect'`.

- [ ] **Step 4: Write `scripts/model_detect.py`**

File `.claude/skills/paper-pdf-figures/scripts/model_detect.py`:
```python
"""Model-based layout detection for --mode auto (Phase 5).

DocLayout-YOLO is the default backend. The LayoutDetector protocol lets
LayoutParser/Surya be added later without changing the dispatcher.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import fitz

from crop_export import FigureConfig

SKILL_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class LayoutRegion:
    bbox_pdf_points: list[float]   # [x0, y0, x1, y1] in PDF points
    label: str
    confidence: float


class LayoutDetector(Protocol):
    def load(self, weights_dir: Path, device: str) -> None: ...
    def detect(self, page: "fitz.Page", dpi: int = 150) -> list[LayoutRegion]: ...


def resolve_weights_dir(weights_dir_arg: str | None) -> Path:
    """3-level priority: --weights-dir > env var > <skill_root>/models."""
    if weights_dir_arg:
        return Path(weights_dir_arg)
    env = os.environ.get("PAPER_PDF_FIGURES_WEIGHTS_DIR")
    if env:
        return Path(env)
    return SKILL_ROOT / "models"


def _iou(a: list[float], b: list[float]) -> float:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    inter = (ix1 - ix0) * (iy1 - iy0)
    area_a = (ax1 - ax0) * (ay1 - ay0)
    area_b = (bx1 - bx0) * (by1 - by0)
    return inter / (area_a + area_b - inter) if (area_a + area_b - inter) > 0 else 0.0


def dedup_iou(regions: list[LayoutRegion], iou_threshold: float = 0.8) -> list[LayoutRegion]:
    """Drop near-duplicate regions (IoU > threshold), keeping higher confidence."""
    kept: list[LayoutRegion] = []
    for r in sorted(regions, key=lambda x: -x.confidence):
        if any(_iou(r.bbox_pdf_points, k.bbox_pdf_points) > iou_threshold for k in kept):
            continue
        kept.append(r)
    return kept


def _center(bbox: list[float]) -> tuple[float, float]:
    return ((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2)


def _union(a: list[float], b: list[float]) -> list[float]:
    return [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]


def pair_and_merge(
    regions: list[LayoutRegion],
    labels: list[str],
    min_confidence: float,
) -> list[tuple[LayoutRegion, LayoutRegion | None]]:
    """Pair each figure with its nearest figure_caption; merge bbox.

    Returns list of (merged_figure_region, paired_caption_or_None). Non-figure
    regions are ignored as figure candidates. Captions without a figure are
    dropped. Low-confidence regions are filtered.
    """
    figure_label = "figure"
    caption_label = "figure_caption"
    if figure_label not in labels:
        # if user customized --labels to not include "figure", treat first label as figure
        figure_label = labels[0] if labels else "figure"
    figures = [r for r in regions if r.label == figure_label and r.confidence >= min_confidence]
    captions = [r for r in regions if r.label == caption_label and r.confidence >= min_confidence]
    figures = dedup_iou(figures)
    # order figures top-to-bottom, left-to-right
    figures.sort(key=lambda r: (r.bbox_pdf_points[1], r.bbox_pdf_points[0]))

    used_caps: set[int] = set()
    pairs: list[tuple[LayoutRegion, LayoutRegion | None]] = []
    for fig in figures:
        fcx, fcy = _center(fig.bbox_pdf_points)
        best, best_d = None, float("inf")
        for i, cap in enumerate(captions):
            if i in used_caps:
                continue
            ccx, ccy = _center(cap.bbox_pdf_points)
            d = abs(ccy - fcy) + abs(ccx - fcx) * 0.1  # vertical distance dominates
            if d < best_d:
                best_d, best = d, i
        if best is not None:
            used_caps.add(best)
            cap = captions[best]
            merged = LayoutRegion(_union(fig.bbox_pdf_points, cap.bbox_pdf_points),
                                   fig.label, fig.confidence)
            pairs.append((merged, cap))
        else:
            pairs.append((fig, None))
    return pairs


def regions_to_figure_configs(
    pairs: list[tuple[LayoutRegion, LayoutRegion | None]],
    page: int,
) -> list[FigureConfig]:
    configs: list[FigureConfig] = []
    for idx, (merged, _cap) in enumerate(pairs, start=1):
        fig_id = f"fig_p{page:04d}_{idx:02d}"
        configs.append(FigureConfig(
            id=fig_id, page=page, bbox=list(merged.bbox_pdf_points),
        ))
    return configs


class FakeDetector:
    """Test double returning pre-set regions per page number."""
    def __init__(self, regions_per_page: dict[int, list[LayoutRegion]]):
        self._regions = regions_per_page

    def load(self, weights_dir: Path, device: str) -> None:
        pass

    def detect(self, page: "fitz.Page", dpi: int = 150) -> list[LayoutRegion]:
        # page number unknown here; dispatcher passes page_num separately via a wrapper
        # for tests, key by 1-based page index in the dict
        return self._regions.get(getattr(page, "_test_page_num", 1), [])


class DocLayoutYoloDetector:
    """Default backend: DocLayout-YOLO (doclayout-yolo package).

    The model is loaded from the HuggingFace Hub (`hantian/yolo`) via
    `PyTorchModelHubMixin.from_pretrained`, which auto-downloads on first use
    and caches afterwards. `weights_dir` is used as the HF cache root
    (`HF_HOME`) so weights land under `<weights_dir>/huggingface/` rather
    than the default `~/.cache/huggingface/`.
    """
    def __init__(self):
        self._model = None
        self._device = "cpu"
        self._names: dict[int, str] = {}

    def load(self, weights_dir: Path, device: str) -> None:
        import os
        weights_dir = Path(weights_dir)
        weights_dir.mkdir(parents=True, exist_ok=True)
        # Route HuggingFace Hub's cache into the configured weights_dir so
        # weights are NOT stored in ~/.cache/huggingface (spec requirement).
        # This must be set before the doclayout_yolo import / from_pretrained
        # call so HF picks up the cache root at first use.
        os.environ["HF_HOME"] = str(weights_dir / "huggingface")
        from doclayout_yolo import YOLOv10  # type: ignore
        self._device = device
        # 'hantian/yolo' is the DocLayout-YOLO official model on HuggingFace Hub.
        # PyTorchModelHubMixin.from_pretrained downloads it on first use and
        # caches under $HF_HOME afterwards. weights_dir is honored via HF_HOME
        # above; HF manages its own cache layout underneath.
        self._model = YOLOv10.from_pretrained("hantian/yolo")
        self._names = self._model.names  # {class_index: class_name}

    def detect(self, page: "fitz.Page", dpi: int = 150) -> list[LayoutRegion]:
        assert self._model is not None, "Detector.load() not called"
        pix = page.get_pixmap(dpi=dpi)
        scale = 72.0 / dpi
        import numpy as np
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        if pix.n == 4:
            img = img[:, :, :3]
        elif pix.n == 1:
            img = np.stack([img[:, :, 0]] * 3, axis=-1)
        results = self._model.predict(img, device=self._device, verbose=False)
        regions: list[LayoutRegion] = []
        for r in results:
            for box in r.boxes:
                x0, y0, x1, y1 = box.xyxy[0].tolist()
                regions.append(LayoutRegion(
                    bbox_pdf_points=[x0 * scale, y0 * scale, x1 * scale, y1 * scale],
                    label=self._names[int(box.cls)],
                    confidence=float(box.conf),
                ))
        return regions
```

- [ ] **Step 5: Update `check_deps.py` to report ML deps**

In `scripts/check_deps.py`, add to `PY_DEPS` (after opencv):
```python
    ("torch", "torch", {"auto"}, "torch"),
    ("doclayout_yolo", "doclayout-yolo", {"auto"}, "doclayout-yolo"),
```
These are optional (their `modes` set is `{"auto"}` so missing blocks only `auto`, not other modes). They must be marked optional in the `BIN_DEPS`/optional sense - but `PY_DEPS` entries are currently non-optional. Add an `optional` flag: change the `PY_DEPS` tuples to 5-tuples `(import, display, modes, install, optional)` and treat optional=True like the binary deps (WARN, not MISSING). Update `collect_status`/`has_required_missing`/`format_report` accordingly. Mark torch + doclayout-yolo `optional=True`. **This is a small refactor of check_deps - keep existing behavior for the 5 current deps (all optional=False).**

- [ ] **Step 6: Update `install_deps.sh` with `--ml`**

Add a `--ml` flag that additionally installs `requirements-ml.txt`. In `--dry-run` mode, echo the extra `pip install -r requirements-ml.txt`. Roughly:
```bash
ML=0
if [[ "${1:-}" == "--ml" ]]; then ML=1; fi
# ... existing pip install -r requirements.txt ...
if [[ "$ML" -eq 1 ]]; then
  run python3 -m pip install --user -r "$SCRIPT_DIR/../requirements-ml.txt"
fi
```

- [ ] **Step 7: Run tests to verify they pass**

Run:
```bash
cd /home/imalne/learn_vibe_coding/.claude/skills/paper-pdf-figures
pytest tests/test_model_detect.py -v
pytest tests/ -q
```
Expected: all model_detect tests pass (12); full suite 83 passed (was 71; +12). The binding check is "all green, no regressions".

- [ ] **Step 8: Commit**

```bash
cd /home/imalne/learn_vibe_coding
git add .claude/skills/paper-pdf-figures/requirements-ml.txt .claude/skills/paper-pdf-figures/scripts/model_detect.py .claude/skills/paper-pdf-figures/scripts/check_deps.py .claude/skills/paper-pdf-figures/scripts/install_deps.sh .claude/skills/paper-pdf-figures/tests/test_model_detect.py
git commit -m "feat(paper-pdf-figures): model_detect backend + ML deps + weight-dir (Phase 5 Task 1)"
```

---

## Task 2: Dispatcher `auto` mode + figure-caption merge + integration tests

**Files:**
- Modify: `.claude/skills/paper-pdf-figures/scripts/extract_pdf_figures.py` (add `auto` branch + 5 new args)
- Modify: `.claude/skills/paper-pdf-figures/tests/test_extract_pdf_figures.py` (+auto tests using FakeDetector)

**Interfaces:**
- Consumes: `model_detect.{resolve_weights_dir, pair_and_merge, regions_to_figure_configs, DocLayoutYoloDetector, FakeDetector, LayoutRegion}` from Task 1; Phase 2 `crop_figures`/`FigureConfig`; Phase 0 `Manifest`/`validate`.
- Produces: `--mode auto` end-to-end: load detector -> per page detect -> filter/merge -> `crop_figures` -> manifest + previews. `--dry-run` = candidates only.
- Produces: `_resolve_device(arg) -> str` (`auto` -> `cuda` if available else `cpu`).

- [ ] **Step 1: Write the failing integration tests (use FakeDetector)**

Append to `.claude/skills/paper-pdf-figures/tests/test_extract_pdf_figures.py`:
```python
def test_auto_mode_crops_figure_and_caption(vector_pdf, tmp_path, monkeypatch):
    # FakeDetector returns a figure + caption on page 1
    import model_detect
    regions = [
        model_detect.LayoutRegion([100, 100, 400, 300], "figure", 0.9),
        model_detect.LayoutRegion([100, 310, 400, 360], "figure_caption", 0.8),
    ]
    # patch DocLayoutYoloDetector -> FakeDetector
    fake = model_detect.FakeDetector({1: regions})
    monkeypatch.setattr(model_detect, "DocLayoutYoloDetector", lambda: fake)

    out = tmp_path / "out"
    r = _run(vector_pdf, out, "--mode", "auto", "--paper-slug", "p", "--dpi", "150")
    assert r.returncode == 0, r.stderr
    assert "figures: 1" in r.stdout
    m = manifest.Manifest.load(out / "p" / "manifest.json")
    assert len(m.figures) == 1
    f = m.figures[0]
    assert f.id == "fig_p0001_01"
    assert f.bbox_pdf_points == [100, 100, 400, 360]   # merged
    assert f.extraction_method == "manual-bbox"        # reuses crop_figures
    assert (out / "p" / "figures" / "fig_p0001_01" / "fig_p0001_01.pdf").is_file()
    assert (out / "p" / "figures" / "fig_p0001_01" / "fig_p0001_01.png").is_file()
    assert manifest.validate(m.to_dict()) == []


def test_auto_mode_dry_run_no_figures_dir(vector_pdf, tmp_path, monkeypatch):
    import model_detect
    regions = [model_detect.LayoutRegion([100, 100, 400, 300], "figure", 0.9)]
    fake = model_detect.FakeDetector({1: regions})
    monkeypatch.setattr(model_detect, "DocLayoutYoloDetector", lambda: fake)

    out = tmp_path / "out"
    r = _run(vector_pdf, out, "--mode", "auto", "--paper-slug", "p", "--dry-run")
    assert r.returncode == 0, r.stderr
    assert "candidates:" in r.stdout
    assert not (out / "p" / "figures").exists()
    assert not (out / "p" / "manifest.json").exists()


def test_auto_mode_missing_ml_deps_errors(vector_pdf, tmp_path, monkeypatch):
    # Simulate torch missing by making DocLayoutYoloDetector.load raise ImportError
    import model_detect

    class _NoML:
        def load(self, *a, **k):
            raise ImportError("torch not found")
        def detect(self, *a, **k):
            raise RuntimeError("not loaded")
    monkeypatch.setattr(model_detect, "DocLayoutYoloDetector", lambda: _NoML())

    # ALSO need to simulate the pre-flight check failing: patch check_deps probe
    # Simpler: the dispatcher checks `import torch` before loading; patch it.
    import builtins
    real_import = builtins.__import__
    def fake_import(name, *a, **k):
        if name == "torch":
            raise ImportError("torch not found")
        return real_import(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", fake_import)

    out = tmp_path / "out"
    r = _run(vector_pdf, out, "--mode", "auto", "--paper-slug", "p")
    assert r.returncode == 1
    assert "ML backend" in r.stderr or "requirements-ml.txt" in r.stderr
    assert "Traceback" not in r.stderr


def test_auto_mode_min_confidence_filters(vector_pdf, tmp_path, monkeypatch):
    import model_detect
    regions = [
        model_detect.LayoutRegion([100, 100, 400, 300], "figure", 0.2),   # below default 0.3
    ]
    fake = model_detect.FakeDetector({1: regions})
    monkeypatch.setattr(model_detect, "DocLayoutYoloDetector", lambda: fake)

    out = tmp_path / "out"
    r = _run(vector_pdf, out, "--mode", "auto", "--paper-slug", "p")
    assert r.returncode == 0, r.stderr
    m = manifest.Manifest.load(out / "p" / "manifest.json")
    assert len(m.figures) == 0
    assert "WARN_NO_FIGURES" in [w.code for w in m.warnings]
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd /home/imalne/learn_vibe_coding/.claude/skills/paper-pdf-figures
pytest tests/test_extract_pdf_figures.py -k auto -v
```
Expected: 4 FAIL (`auto` exits 1 "not implemented yet").

- [ ] **Step 3: Add the `auto` branch to `extract_pdf_figures.py`**

In `scripts/extract_pdf_figures.py`:

a) Add imports at top:
```python
from model_detect import (
    DocLayoutYoloDetector, LayoutRegion, pair_and_merge,
    regions_to_figure_configs, resolve_weights_dir,
)
```

b) Add `_resolve_device` helper:
```python
def _resolve_device(arg: str) -> str:
    if arg == "auto":
        try:
            import torch
            return "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            return "cpu"
    return arg
```

c) Add the new args to the argparse block:
```python
    parser.add_argument("--weights-dir", default=None)
    parser.add_argument("--device", default="auto", choices=["auto", "cpu", "cuda"])
    parser.add_argument("--min-confidence", type=float, default=0.3)
    parser.add_argument("--labels", default="figure,figure_caption")
    parser.add_argument("--apply", action="store_true")
```

d) Change the mode gate to allow `auto`:
```python
    if args.mode not in ("embedded", "manual", "detect", "auto"):
        print(f"mode '{args.mode}' is not implemented yet", file=sys.stderr)
        return 1
```

e) Add a pre-flight ML check + auto branch. After the `formats`/`warnings` setup and before `try: doc = fitz.open(...)`:
```python
    if args.mode == "auto":
        try:
            import torch  # noqa: F401
            import doclayout_yolo  # noqa: F401
        except ImportError:
            print("ERROR: --mode auto requires ML backend; "
                  "pip install -r requirements-ml.txt", file=sys.stderr)
            return 1
        if not (0 <= args.min_confidence <= 1):
            print(f"ERROR: --min-confidence must be in [0, 1], got {args.min_confidence}",
                  file=sys.stderr)
            return 1
```

f) In the `try: ... finally: doc.close()` block, add an `else` (auto) branch after the `detect` branch:
```python
        else:  # auto
            labels = [s.strip() for s in args.labels.split(",") if s.strip()]
            weights_dir = resolve_weights_dir(args.weights_dir)
            detector = DocLayoutYoloDetector()
            detector.load(weights_dir, _resolve_device(args.device))
            indices = (sorted(p - 1 for p in pages_set) if pages_set is not None
                       else list(range(len(doc))))
            all_figure_configs = []
            all_candidates = []   # LayoutRegion records for manifest
            pages_with_hits = 0
            for pno in indices:
                if pno < 0 or pno >= len(doc):
                    continue
                regions = detector.detect(doc[pno], dpi=150)
                if not regions:
                    continue
                pages_with_hits += 1
                pairs = pair_and_merge(regions, labels=labels,
                                       min_confidence=args.min_confidence)
                configs = regions_to_figure_configs(pairs, page=pno + 1)
                all_figure_configs.extend(configs)
                # record candidates (every region, for manifest + preview)
                all_candidates.extend(regions)
                # stash page num for preview drawing
                for r in regions:
                    pass
                if not args.dry_run:
                    # preview with labels
                    from figure_detect import draw_candidates_preview
                    # build Candidate records for the preview fn
                    from manifest import Candidate
                    cands = [Candidate(page=pno + 1, bbox_pdf_points=r.bbox_pdf_points,
                                       score=r.confidence) for r in regions]
                    png = draw_candidates_preview(doc[pno], cands, dpi=100)
                    cand_dir = paper_dir / "candidates"
                    cand_dir.mkdir(parents=True, exist_ok=True)
                    (cand_dir / f"page_{pno + 1:04d}_candidates.png").write_bytes(png)
            if not args.dry_run:
                import json
                (paper_dir / "candidates").mkdir(parents=True, exist_ok=True)
                (paper_dir / "candidates" / "candidates.json").write_text(
                    json.dumps({"candidates": [
                        {"page": i + 1, "bbox_pdf_points": r.bbox_pdf_points,
                         "label": r.label, "confidence": r.confidence}
                        for i, r in enumerate(all_candidates)
                    ]}, indent=2, ensure_ascii=False))
            # crop
            if not args.dry_run:
                records = crop_figures(doc, all_figure_configs, out_dir, slug,
                                       dpi=args.dpi, formats=formats, warnings=warnings)
            else:
                records = []
            # expose for summary
            args._auto_figures = len(records)
            args._auto_candidates = len(all_candidates)
            args._auto_pages = pages_with_hits
            # repurpose `records` for manifest: auto produces figures
            # (reuse the manual branch's manifest path)
```

g) In the manifest-construction section, add an `auto` arm that adds `Figure` records (like manual) AND `Candidate` records (with label/confidence) from `all_candidates`:
```python
    elif args.mode == "auto":
        for rec in records:
            m.add_figure(rec)
        if not records and not args.dry_run:
            m.add_warning("WARN_NO_FIGURES")
        # add candidates with label/confidence
        # (all_candidates is in scope from the auto branch)
```
**Note:** `all_candidates` must be assigned in a scope visible here. Restructure so `all_candidates` is initialized before the `try` block: `all_candidates: list = []`.

h) Summary print:
```python
    elif args.mode == "auto":
        print(f"figures: {getattr(args, '_auto_figures', 0)}")
        print(f"candidates: {getattr(args, '_auto_candidates', 0)} "
              f"across {getattr(args, '_auto_pages', 0)} pages")
```

**This task has more moving parts - the implementer may need to adjust variable scoping (`all_candidates`, `records`) and the summary counters. The binding intent: auto mode produces `figures[]` (cropped) + `candidates[]` (with label/confidence) + previews; dry-run skips crops.**

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
cd /home/imalne/learn_vibe_coding/.claude/skills/paper-pdf-figures
pytest tests/test_extract_pdf_figures.py -k auto -v
pytest tests/ -q
```
Expected: 4 auto tests pass; full suite 87 passed (was 83; +4).

- [ ] **Step 5: Commit**

```bash
cd /home/imalne/learn_vibe_coding
git add .claude/skills/paper-pdf-figures/scripts/extract_pdf_figures.py .claude/skills/paper-pdf-figures/tests/test_extract_pdf_figures.py
git commit -m "feat(paper-pdf-figures): CLI auto mode with model detect + figure-caption merge (Phase 5 Task 2)"
```

---

## Task 3: Schema extension (label/confidence) + .gitignore models/ + real-paper acceptance

**Files:**
- Modify: `.claude/skills/paper-pdf-figures/templates/manifest.schema.json` (candidates +`label`/`confidence`)
- Modify: `.claude/skills/paper-pdf-figures/.gitignore` or root `.gitignore` (`models/`)
- (No code) Real-paper acceptance smoke

- [ ] **Step 1: Extend the manifest schema for candidate label/confidence**

In `templates/manifest.schema.json`, the `candidates.items.properties` currently has `page`, `bbox_pdf_points`, `score`. Add optional `label` and `confidence`:
```json
          "label": {"type": "string"},
          "confidence": {"type": ["number", "null"], "minimum": 0, "maximum": 1}
```
(Add to `properties` only, NOT to `required` - they're optional. `additionalProperties: false` stays, so only listed fields allowed.)

- [ ] **Step 2: Add `models/` to `.gitignore`**

The root `.gitignore` already has Python/OS entries. Add:
```
# Model weights (Phase 5 auto mode, downloaded at runtime)
.claude/skills/paper-pdf-figures/models/
```

- [ ] **Step 3: Real-paper acceptance smoke**

Run auto on the vector paper (the one that frustrated the heuristic detect):
```bash
cd /home/imalne/learn_vibe_coding
python3 .claude/skills/paper-pdf-figures/scripts/extract_pdf_figures.py \
    2606.28301v1.pdf --mode auto --out /tmp/p5smoke --paper-slug vec \
    --pages 2,5,9,11,12,13 --dpi 300
```
Confirm:
- Figures cropped (count > 0)
- Each cropped PDF has vector drawings (`get_drawings() > 0`) + text
- Manifest schema-valid
- Source PDF unchanged (sha256 before == after)

Also run on `2606.26615v1.pdf` (raster) to confirm auto works there too.

- [ ] **Step 4: Verify Phase 5 acceptance (spec §11)**

- [ ] **A1**: auto crops figures on the vector paper (no config.yaml needed).
- [ ] **A2**: figure + caption merged into one crop (bbox union).
- [ ] **A3**: manifest records figures + candidates (with label/confidence).
- [ ] **A4**: source PDF unchanged.
- [ ] **A5**: full suite passes; `check_deps` reports torch + doclayout-yolo.
- [ ] **A6**: `--dry-run` writes candidates/previews only, no `figures/`.

- [ ] **Step 5: Commit**

```bash
cd /home/imalne/learn_vibe_coding
git add .claude/skills/paper-pdf-figures/templates/manifest.schema.json .gitignore
git commit -m "feat(paper-pdf-figures): schema candidate label/confidence + gitignore models (Phase 5 Task 3)"
```

---

## Self-Review Notes

**Spec coverage:**
- §4 model selection (DocLayout-YOLO) + backend protocol -> Task 1.
- §5 ML deps optional + weight-dir 3-level + check_deps + install_deps --ml -> Task 1.
- §6 CLI auto + 5 args -> Task 2.
- §7 figure-caption merge + dedup + id -> Task 1 (`pair_and_merge`, `dedup_iou`, `regions_to_figure_configs`).
- §8 manifest candidate label/confidence -> Task 3.
- §9 tests (FakeDetector for CI) -> Tasks 1+2.

**Placeholder scan:** the Task 2 dispatcher integration is described as a delta (add args, add branch, restructure scoping) rather than a full file rewrite, because the file is now large. The implementer must read the current `extract_pdf_figures.py` and apply the changes carefully. If scoping issues arise (all_candidates/records visibility), restructure minimally.

**API risk:** `doclayout_yolo.YOLOv10` API (predict/boxes.cls/boxes.conf/boxes.xyxy) is the standard ultralytics interface; `doclayout-yolo` wraps it. Verified during plan writing by probing the installed package. If the actual API differs (e.g., class name, result attribute), Task 1 Step 4's `DocLayoutYoloDetector.detect` needs adjustment - the FakeDetector tests don't exercise the real model, so CI stays green; the real-paper smoke (Task 3) catches API mismatches.

**Type consistency:** `LayoutRegion(bbox_pdf_points, label, confidence)` flows detector -> pair_and_merge -> regions_to_figure_configs -> `FigureConfig(id, page, bbox)`. `Candidate(page, bbox_pdf_points, score)` reused for previews (score=confidence). Schema `candidates[].label`/`confidence` match the JSON written by the dispatcher.

**Backward compat:** `check_deps.py` refactor (PY_DEPS 4-tuple -> 5-tuple with optional flag) must preserve behavior for the 5 existing deps (all optional=False). Existing 71 tests must pass.
