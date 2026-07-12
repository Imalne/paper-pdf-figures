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
    assert tbl_merged.bbox_pdf_points == [100, 400, 400, 540]


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
