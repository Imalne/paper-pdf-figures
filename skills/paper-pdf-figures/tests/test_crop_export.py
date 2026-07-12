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
