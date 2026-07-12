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

    If `huggingface.co` is unreachable (e.g. behind a firewall / in some WSL2
    setups), set `HF_ENDPOINT=https://hf-mirror.com` (or another mirror) in
    the environment to route downloads through a mirror.
    """
    def __init__(self):
        self._model = None
        self._device = "cpu"
        self._names: dict[int, str] = {}

    def load(self, weights_dir: Path, device: str) -> None:
        import os
        import socket
        weights_dir = Path(weights_dir)
        weights_dir.mkdir(parents=True, exist_ok=True)
        # Route HuggingFace Hub's cache into the configured weights_dir so
        # weights are NOT stored in ~/.cache/huggingface (spec requirement).
        os.environ["HF_HOME"] = str(weights_dir / "huggingface")
        # Honor an explicit HF_ENDPOINT (e.g. https://hf-mirror.com) set by
        # the caller (run.sh export or manual env var); do NOT override.
        os.environ.setdefault("HF_ENDPOINT", "https://huggingface.co")

        repo = "juliozhao/DocLayout-YOLO-DocStructBench"
        fname = "doclayout_yolo_docstructbench_imgsz1024.pt"

        # If the weight file is already cached, force offline mode so
        # hf_hub_download skips the online etag check (avoids network errors
        # from broken proxies / unreachable endpoints on cached weights).
        from huggingface_hub import hf_hub_download
        try:
            from huggingface_hub import try_to_load_from_cache
            cached = try_to_load_from_cache(repo_id=repo, filename=fname,
                                            cache_dir=weights_dir / "huggingface")
            if cached is not None and cached != "None":
                os.environ["HF_HUB_OFFLINE"] = "1"
        except Exception:
            pass  # cache check is best-effort

        # SOCKS proxy fix: if the environment has a SOCKS proxy (all_proxy /
        # http_proxy / https_proxy = socks://...) but httpx doesn't have socksio
        # installed, httpx will crash. Temporarily clear proxy env vars so
        # httpx connects directly. Restore them after download.
        proxy_vars = {}
        socks_present = False
        for var in ("http_proxy", "https_proxy", "all_proxy",
                     "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
            val = os.environ.get(var, "")
            if val:
                proxy_vars[var] = val
                if "socks" in val.lower():
                    socks_present = True
        if socks_present:
            try:
                import socksio  # noqa: F401
            except ImportError:
                # httpx can't use SOCKS without socksio -> clear proxies
                for var in proxy_vars:
                    os.environ.pop(var, None)
                print("  [proxy] SOCKS proxy detected but socksio not installed; "
                      "clearing proxy env vars for direct connection")

        from doclayout_yolo import YOLOv10  # type: ignore
        self._device = device
        # Try the current endpoint with a 10s timeout; on failure, auto-fallback
        # to the other endpoint (huggingface.co <-> hf-mirror.com) and retry once.
        old_timeout = socket.getdefaulttimeout()
        weight_file = None
        for attempt in range(2):
            ep = os.environ.get("HF_ENDPOINT", "https://huggingface.co")
            try:
                socket.setdefaulttimeout(10)
                weight_file = hf_hub_download(repo_id=repo, filename=fname)
                break
            except Exception as e:
                if attempt == 0:
                    # Auto-fallback: switch to the other endpoint.
                    fallback = "https://hf-mirror.com" if "huggingface.co" in ep else "https://huggingface.co"
                    print(f"  [HF fallback] {ep} failed ({type(e).__name__}); retrying via {fallback}")
                    os.environ["HF_ENDPOINT"] = fallback
                    # If weights are cached, force offline on retry.
                    if os.environ.get("HF_HUB_OFFLINE") != "1":
                        try:
                            from huggingface_hub import try_to_load_from_cache
                            cached = try_to_load_from_cache(
                                repo_id=repo, filename=fname,
                                cache_dir=weights_dir / "huggingface")
                            if cached is not None and cached != "None":
                                os.environ["HF_HUB_OFFLINE"] = "1"
                                print(f"  [HF fallback] weights cached; switching to offline mode")
                        except Exception:
                            pass
                else:
                    socket.setdefaulttimeout(old_timeout)
                    # Restore proxy env vars if we cleared them
                    if socks_present:
                        for var, val in proxy_vars.items():
                            os.environ[var] = val
                    raise
        socket.setdefaulttimeout(old_timeout)
        # Restore proxy env vars if we cleared them
        if socks_present:
            for var, val in proxy_vars.items():
                os.environ[var] = val
        self._model = YOLOv10(weight_file)
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
