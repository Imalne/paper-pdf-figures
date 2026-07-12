import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import io
import pytest


@pytest.fixture
def embedded_pdf(tmp_path):
    """A tiny PDF with one PNG embedded on two pages (for dedup testing).

    Returns (path, original_png_bytes). The same image bytes are inserted on
    both pages so the extractor should dedup to a single output file.
    """
    import fitz
    from PIL import Image

    img = Image.new("RGB", (12, 10), "red")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    img_bytes = buf.getvalue()

    doc = fitz.open()
    for _ in range(2):
        page = doc.new_page()
        page.insert_image(fitz.Rect(0, 0, 120, 100), stream=img_bytes)
    pdf_path = tmp_path / "fixture.pdf"
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path, img_bytes


@pytest.fixture
def vector_pdf(tmp_path):
    """A 1-page PDF with drawn vector shapes + text, for crop testing.

    Page is US Letter (612x792). A red rect at (72,72)-(200,200) with the
    text 'FIGURE 1' inside it; a blue rect at (300,300)-(540,540).
    """
    import fitz

    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.draw_rect(fitz.Rect(72, 72, 200, 200), color=(1, 0, 0), width=2)
    page.insert_text((90, 130), "FIGURE 1", fontsize=14)
    page.draw_rect(fitz.Rect(300, 300, 540, 540), color=(0, 0, 1), width=2)
    p = tmp_path / "vector.pdf"
    doc.save(str(p))
    doc.close()
    return p


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
    # dense "figure" cluster (200 rects so the close kernel merges them
    # into one blob; 60 left too many gaps for k=dpi*0.15 to bridge)
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


@pytest.fixture
def multi_page_pdf(tmp_path):
    """A 3-page PDF with text on each page, for render-mode testing.

    Each page is US Letter (612x792) with a short text label so whole-page
    renders produce non-empty PNGs and the contact sheet has thumbnails.
    """
    import fitz

    doc = fitz.open()
    for i in range(3):
        page = doc.new_page(width=612, height=792)
        page.insert_text((100, 100), f"Page {i + 1}", fontsize=14)
    p = tmp_path / "multi.pdf"
    doc.save(str(p))
    doc.close()
    return p
