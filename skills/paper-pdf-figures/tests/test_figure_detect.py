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
