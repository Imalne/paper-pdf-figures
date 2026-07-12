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


def test_render_regions_skips_degenerate_bbox(multi_page_pdf, tmp_path):
    """Zero-area / inverted bbox must be skipped, not crash the batch."""
    from crop_export import FigureConfig
    doc = fitz.open(str(multi_page_pdf))
    figs = [
        FigureConfig(id="ok", page=1, bbox=[50, 50, 300, 300]),
        FigureConfig(id="zero", page=1, bbox=[0, 0, 0, 0]),        # zero-area
        FigureConfig(id="inverted", page=1, bbox=[300, 300, 50, 50]),  # inverted
    ]
    items = render_pages.render_regions(doc, figs, tmp_path / "out", "paper", dpi=72)
    doc.close()
    assert len(items) == 1  # only the valid one
    assert items[0].id == "ok"
