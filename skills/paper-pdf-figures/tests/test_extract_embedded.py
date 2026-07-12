import hashlib

import fitz

import extract_embedded
import manifest


def test_extract_dedups_same_xref_across_pages(embedded_pdf, tmp_path):
    pdf_path, _ = embedded_pdf
    doc = fitz.open(str(pdf_path))
    out_dir = tmp_path / "out"

    results = extract_embedded.extract_embedded_images(doc, out_dir, "paper")

    assert len(results) == 1, "same image on 2 pages must dedup to 1 record"
    rec = results[0]
    assert rec.page == 1                      # first page it appears on, 1-based
    assert rec.format == "png"
    assert rec.width == 12 and rec.height == 10
    assert rec.id == f"embedded_p{rec.page:04d}_xref{rec.xref:06d}"
    # file written with the spec naming convention, relative to out_dir
    expected_name = f"embedded/p{rec.page:04d}_xref{rec.xref:06d}.png"
    assert rec.file == expected_name
    saved = (out_dir / "paper" / expected_name).read_bytes()
    assert saved[:8] == b"\x89PNG\r\n\x1a\n"              # valid PNG magic
    assert rec.sha256 == hashlib.sha256(saved).hexdigest()  # sha matches saved file
    doc.close()


def test_extract_records_are_manifest_valid(embedded_pdf, tmp_path):
    pdf_path, _ = embedded_pdf
    doc = fitz.open(str(pdf_path))

    m = manifest.Manifest("fixture.pdf", "paper", "0.1.0")
    for rec in extract_embedded.extract_embedded_images(doc, tmp_path / "out", "paper"):
        m.add_embedded_image(rec)

    assert manifest.validate(m.to_dict()) == []
    doc.close()


def test_dry_run_writes_no_files(embedded_pdf, tmp_path):
    pdf_path, _ = embedded_pdf
    doc = fitz.open(str(pdf_path))
    out_dir = tmp_path / "out"

    results = extract_embedded.extract_embedded_images(
        doc, out_dir, "paper", dry_run=True
    )

    assert len(results) == 1
    assert not out_dir.exists() or not any(out_dir.rglob("*"))
    doc.close()


def test_pages_filter_restricts_extraction(embedded_pdf, tmp_path):
    # Build a PDF with DIFFERENT images on two pages, then extract only page 2.
    import io
    from PIL import Image
    import fitz as _fitz

    buf1 = io.BytesIO(); Image.new("RGB", (8, 8), "red").save(buf1, "PNG")
    buf2 = io.BytesIO(); Image.new("RGB", (9, 7), "blue").save(buf2, "PNG")
    doc = _fitz.open()
    p1 = doc.new_page(); p1.insert_image(_fitz.Rect(0, 0, 80, 80), stream=buf1.getvalue())
    p2 = doc.new_page(); p2.insert_image(_fitz.Rect(0, 0, 90, 70), stream=buf2.getvalue())

    results = extract_embedded.extract_embedded_images(
        doc, tmp_path / "out", "paper", pages={2}
    )
    assert len(results) == 1
    assert results[0].page == 2
    assert results[0].width == 9 and results[0].height == 7
    doc.close()


def test_pages_filter_assigns_lowest_page_for_shared_xref(tmp_path):
    """Same image on pages 1 and 2; pass pages as an unordered set {2, 1}."""
    import io
    from PIL import Image

    buf = io.BytesIO(); Image.new("RGB", (8, 8), "green").save(buf, "PNG")
    doc = fitz.open()
    for _ in range(2):
        page = doc.new_page()
        page.insert_image(fitz.Rect(0, 0, 80, 80), stream=buf.getvalue())

    results = extract_embedded.extract_embedded_images(
        doc, tmp_path / "out", "paper", pages={2, 1}
    )
    assert len(results) == 1
    assert results[0].page == 1, "shared xref must be assigned to the lowest page"
    doc.close()


class _FakePage:
    def __init__(self, images):
        self._images = images

    def get_images(self, full=True):
        return self._images


class _FakeDoc:
    """Mimics the fitz.Document interface extract_embedded_images uses."""
    def __init__(self, pages, extract):
        self._pages = pages          # list of lists of (xref,) tuples
        self._extract = extract      # dict xref -> dict | Exception

    def __len__(self):
        return len(self._pages)

    def __getitem__(self, i):
        return _FakePage(self._pages[i])

    def extract_image(self, xref):
        r = self._extract.get(xref)
        if isinstance(r, Exception):
            raise r
        return r


def test_extract_skips_bad_xref_with_warning(tmp_path):
    fake = _FakeDoc(
        pages=[[(1,), (2,), (3,)]],
        extract={
            1: {"ext": "png", "image": b"\x89PNG\r\n\x1a\n", "width": 10, "height": 10},
            2: RuntimeError("corrupt xref"),
            3: {"ext": "png", "image": b"\x89PNG\r\n\x1a\n", "width": 5, "height": 5},
        },
    )
    warnings = []
    results = extract_embedded.extract_embedded_images(
        fake, tmp_path / "out", "p", warnings=warnings)
    assert len(results) == 2                       # xref 2 skipped
    assert {r.xref for r in results} == {1, 3}
    assert any(w[0] == "WARN_EXTRACT_IMAGE_FAILED" and w[1] == 1 for w in warnings)


def test_extract_skips_zero_dimension_with_warning(tmp_path):
    fake = _FakeDoc(
        pages=[[(10,)]],
        extract={10: {"ext": "png", "image": b"\x89PNG\r\n\x1a\n", "width": 0, "height": 0}},
    )
    warnings = []
    results = extract_embedded.extract_embedded_images(
        fake, tmp_path / "out", "p", warnings=warnings)
    assert results == []
    assert any(w[0] == "WARN_ZERO_DIMENSION_IMAGE" for w in warnings)
