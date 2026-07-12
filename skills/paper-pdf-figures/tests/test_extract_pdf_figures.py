import hashlib
import io
import subprocess
import sys
from pathlib import Path

import fitz
from PIL import Image

import manifest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "extract_pdf_figures.py"


def _run(pdf_path, out_dir, *extra):
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(pdf_path), "--out", str(out_dir), *extra],
        capture_output=True, text=True,
    )


def _two_image_pdf(tmp_path):
    buf1 = io.BytesIO(); Image.new("RGB", (8, 8), "red").save(buf1, "PNG")
    buf2 = io.BytesIO(); Image.new("RGB", (9, 7), "blue").save(buf2, "PNG")
    pdf_path = tmp_path / "two.pdf"
    doc = fitz.open()
    p1 = doc.new_page(); p1.insert_image(fitz.Rect(0, 0, 80, 80), stream=buf1.getvalue())
    p2 = doc.new_page(); p2.insert_image(fitz.Rect(0, 0, 90, 70), stream=buf2.getvalue())
    doc.save(str(pdf_path)); doc.close()
    return pdf_path, buf1.getvalue(), buf2.getvalue()


def test_embedded_mode_writes_manifest_and_files(embedded_pdf, tmp_path):
    pdf_path, _ = embedded_pdf
    out = tmp_path / "out"
    r = _run(pdf_path, out, "--mode", "embedded", "--paper-slug", "paper")
    assert r.returncode == 0, r.stderr
    manifest_path = out / "paper" / "manifest.json"
    assert manifest_path.is_file()
    m = manifest.Manifest.load(manifest_path)
    assert len(m.embedded_images) == 1
    rec = m.embedded_images[0]
    saved = (out / "paper" / rec.file).read_bytes()
    assert saved[:8] == b"\x89PNG\r\n\x1a\n"              # valid PNG
    assert rec.sha256 == hashlib.sha256(saved).hexdigest()  # sha matches saved file
    assert manifest.validate(m.to_dict()) == []
    assert "embedded_images: 1" in r.stdout


def test_pages_filter_via_cli(tmp_path):
    pdf_path, _, _ = _two_image_pdf(tmp_path)
    out = tmp_path / "out"
    r = _run(pdf_path, out, "--mode", "embedded", "--paper-slug", "p", "--pages", "2")
    assert r.returncode == 0, r.stderr
    m = manifest.Manifest.load(out / "p" / "manifest.json")
    assert len(m.embedded_images) == 1
    assert m.embedded_images[0].page == 2


def test_overwrite_protection(embedded_pdf, tmp_path):
    pdf_path, _ = embedded_pdf
    out = tmp_path / "out"
    assert _run(pdf_path, out, "--paper-slug", "p").returncode == 0
    r2 = _run(pdf_path, out, "--paper-slug", "p")
    assert r2.returncode == 1
    assert "already exists" in r2.stderr


def test_overwrite_flag_replaces(embedded_pdf, tmp_path):
    pdf_path, _ = embedded_pdf
    out = tmp_path / "out"
    assert _run(pdf_path, out, "--paper-slug", "p").returncode == 0
    r2 = _run(pdf_path, out, "--paper-slug", "p", "--overwrite")
    assert r2.returncode == 0, r2.stderr


def test_invalid_mode_argparse_errors(embedded_pdf, tmp_path):
    """All 5 modes are implemented; an unknown mode is rejected by argparse (exit 2)."""
    pdf_path, _ = embedded_pdf
    r = _run(pdf_path, tmp_path / "out", "--mode", "invalidmode")
    assert r.returncode == 2
    assert "invalid choice" in r.stderr


def test_paper_slug_default_from_filename(embedded_pdf, tmp_path):
    pdf_path, _ = embedded_pdf
    out = tmp_path / "out"
    r = _run(pdf_path, out)
    assert r.returncode == 0, r.stderr
    assert (out / "fixture" / "manifest.json").is_file()


def test_overwrite_clears_stale_files(tmp_path):
    """--overwrite must remove orphan image files from a prior run."""
    import io
    from PIL import Image

    buf1 = io.BytesIO(); Image.new("RGB", (8, 8), "red").save(buf1, "PNG")
    buf2 = io.BytesIO(); Image.new("RGB", (9, 7), "blue").save(buf2, "PNG")
    pdf_path = tmp_path / "two.pdf"
    doc = fitz.open()
    p1 = doc.new_page(); p1.insert_image(fitz.Rect(0, 0, 80, 80), stream=buf1.getvalue())
    p2 = doc.new_page(); p2.insert_image(fitz.Rect(0, 0, 90, 70), stream=buf2.getvalue())
    doc.save(str(pdf_path)); doc.close()

    out = tmp_path / "out"
    assert _run(pdf_path, out, "--paper-slug", "p", "--pages", "1").returncode == 0
    embedded_dir = out / "p" / "embedded"
    assert len(list(embedded_dir.glob("*.png"))) == 1

    r2 = _run(pdf_path, out, "--paper-slug", "p", "--pages", "2", "--overwrite")
    assert r2.returncode == 0, r2.stderr
    files = list(embedded_dir.glob("*.png"))
    assert len(files) == 1, f"stale orphan files left behind: {[f.name for f in files]}"
    m = manifest.Manifest.load(out / "p" / "manifest.json")
    assert len(m.embedded_images) == 1
    assert m.embedded_images[0].page == 2


def test_validation_failure_leaves_no_manifest(embedded_pdf, tmp_path, monkeypatch):
    """If schema validation fails, no manifest.json must be written (M2)."""
    import extract_pdf_figures

    pdf_path, _ = embedded_pdf
    out = tmp_path / "out"
    monkeypatch.setattr(extract_pdf_figures, "validate", lambda d: ["fake validation error"])
    rc = extract_pdf_figures.main([str(pdf_path), "--out", str(out), "--paper-slug", "p"])
    assert rc == 1
    assert not (out / "p" / "manifest.json").exists()


def test_source_pdf_unchanged_after_extraction(embedded_pdf, tmp_path):
    pdf_path, _ = embedded_pdf
    before = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
    r = _run(pdf_path, tmp_path / "out", "--paper-slug", "p")
    assert r.returncode == 0, r.stderr
    after = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
    assert before == after, "source PDF must not be modified"


def test_manual_mode_crops_figures_from_config(vector_pdf, tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        f"pdf: {vector_pdf}\n"
        "figures:\n"
        "  - id: fig_001\n"
        "    page: 1\n"
        "    bbox: [60, 60, 210, 210]\n"
        "    caption: Red box.\n"
        "  - id: fig_002\n"
        "    page: 1\n"
        "    bbox: [290, 290, 550, 550]\n"
    )
    out = tmp_path / "out"
    r = _run(vector_pdf, out, "--mode", "manual", "--config", str(cfg),
             "--paper-slug", "p", "--dpi", "150")
    assert r.returncode == 0, r.stderr
    assert "figures: 2" in r.stdout
    m = manifest.Manifest.load(out / "p" / "manifest.json")
    assert len(m.figures) == 2
    assert m.figures[0].id == "fig_001"
    assert m.figures[0].bbox_pdf_points == [60, 60, 210, 210]
    assert m.figures[0].extraction_method == "manual-bbox"
    assert m.figures[0].dpi == 150
    assert (out / "p" / "figures" / "fig_001" / "fig_001.pdf").is_file()
    assert (out / "p" / "figures" / "fig_001" / "fig_001.png").is_file()
    assert (out / "p" / "figures" / "fig_002" / "fig_002.pdf").is_file()
    assert manifest.validate(m.to_dict()) == []


def test_manual_mode_requires_config(embedded_pdf, tmp_path):
    pdf_path, _ = embedded_pdf
    r = _run(pdf_path, tmp_path / "out", "--mode", "manual")
    assert r.returncode == 1
    assert "requires --config" in r.stderr


def test_manual_mode_formats_filter(vector_pdf, tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "figures:\n"
        "  - id: fig_001\n"
        "    page: 1\n"
        "    bbox: [60, 60, 210, 210]\n"
    )
    out = tmp_path / "out"
    r = _run(vector_pdf, out, "--mode", "manual", "--config", str(cfg),
             "--paper-slug", "p", "--formats", "pdf")
    assert r.returncode == 0, r.stderr
    assert (out / "p" / "figures" / "fig_001" / "fig_001.pdf").is_file()
    assert not (out / "p" / "figures" / "fig_001" / "fig_001.png").exists()


def test_manual_mode_leaves_source_pdf_unchanged(vector_pdf, tmp_path):
    import hashlib

    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "figures:\n"
        "  - id: fig_001\n"
        "    page: 1\n"
        "    bbox: [60, 60, 210, 210]\n"
    )
    before = hashlib.sha256(vector_pdf.read_bytes()).hexdigest()
    r = _run(vector_pdf, tmp_path / "out", "--mode", "manual", "--config", str(cfg),
             "--paper-slug", "p")
    assert r.returncode == 0, r.stderr
    after = hashlib.sha256(vector_pdf.read_bytes()).hexdigest()
    assert before == after


def test_manual_mode_missing_config_clean_error(vector_pdf, tmp_path):
    r = _run(vector_pdf, tmp_path / "out", "--mode", "manual",
             "--config", str(tmp_path / "nonexistent.yaml"), "--paper-slug", "p")
    assert r.returncode == 1
    assert "ERROR:" in r.stderr
    assert "Traceback" not in r.stderr


def test_manual_mode_malformed_yaml_clean_error(vector_pdf, tmp_path):
    cfg = tmp_path / "bad.yaml"
    cfg.write_text("figures: [this is not valid yaml: : :\n")
    r = _run(vector_pdf, tmp_path / "out", "--mode", "manual",
             "--config", str(cfg), "--paper-slug", "p")
    assert r.returncode == 1
    assert "ERROR:" in r.stderr
    assert "Traceback" not in r.stderr


def test_dpi_validation(vector_pdf, tmp_path):
    cfg = tmp_path / "c.yaml"
    cfg.write_text("figures:\n  - id: fig_001\n    page: 1\n    bbox: [60, 60, 210, 210]\n")
    r = _run(vector_pdf, tmp_path / "out", "--mode", "manual", "--config", str(cfg),
             "--paper-slug", "p", "--dpi", "0")
    assert r.returncode == 1
    assert "dpi" in r.stderr.lower()


def test_detect_mode_writes_previews_and_candidates(detect_pdf, tmp_path):
    out = tmp_path / "out"
    r = _run(detect_pdf, out, "--mode", "detect", "--paper-slug", "p",
             "--min-area-ratio", "0.02")
    assert r.returncode == 0, r.stderr
    assert "candidates:" in r.stdout
    assert (out / "p" / "candidates" / "page_0001_candidates.png").is_file()
    cj = out / "p" / "candidates" / "candidates.json"
    assert cj.is_file()
    import json
    data = json.loads(cj.read_text())
    assert "candidates" in data and len(data["candidates"]) >= 1
    m = manifest.Manifest.load(out / "p" / "manifest.json")
    assert len(m.candidates) >= 1
    assert manifest.validate(m.to_dict()) == []


def test_detect_mode_dry_run_writes_nothing(detect_pdf, tmp_path):
    out = tmp_path / "out"
    r = _run(detect_pdf, out, "--mode", "detect", "--paper-slug", "p",
             "--min-area-ratio", "0.02", "--dry-run")
    assert r.returncode == 0, r.stderr
    assert "candidates:" in r.stdout
    assert not (out / "p" / "candidates").exists()
    assert not (out / "p" / "manifest.json").exists()


def test_detect_mode_pages_filter(detect_pdf, tmp_path):
    # 2-page PDF with content only on page 1
    import fitz
    two = tmp_path / "two.pdf"
    doc = fitz.open()
    p1 = doc.new_page(width=612, height=792)
    import random
    rng = random.Random(1)
    for _ in range(60):
        p1.draw_rect(fitz.Rect(100 + rng.random()*270, 100 + rng.random()*270,
                               112 + rng.random()*270, 112 + rng.random()*270),
                     color=(0, 0, 0), fill=(0, 0, 0))
    doc.new_page(width=612, height=792)  # blank page 2
    doc.save(str(two)); doc.close()

    out = tmp_path / "out"
    r = _run(two, out, "--mode", "detect", "--paper-slug", "p",
             "--min-area-ratio", "0.02", "--pages", "1")
    assert r.returncode == 0, r.stderr
    assert (out / "p" / "candidates" / "page_0001_candidates.png").is_file()
    assert not (out / "p" / "candidates" / "page_0002_candidates.png").exists()


def test_detect_inverted_area_ratios_errors(detect_pdf, tmp_path):
    r = _run(detect_pdf, tmp_path / "out", "--mode", "detect", "--paper-slug", "p",
             "--min-area-ratio", "0.9", "--max-area-ratio", "0.1")
    assert r.returncode == 1
    assert "ERROR:" in r.stderr
    assert "must be <=" in r.stderr


def test_missing_pdf_clean_error(tmp_path):
    r = _run(tmp_path / "nonexistent.pdf", tmp_path / "out", "--mode", "embedded")
    assert r.returncode == 1
    assert "ERROR:" in r.stderr
    assert "cannot open" in r.stderr.lower()
    assert "Traceback" not in r.stderr


def test_non_pdf_clean_error(tmp_path):
    bad = tmp_path / "not-a-pdf.pdf"
    bad.write_bytes(b"this is not a pdf")
    r = _run(bad, tmp_path / "out", "--mode", "embedded")
    assert r.returncode == 1
    assert "ERROR:" in r.stderr
    assert "Traceback" not in r.stderr


def test_bad_pages_spec_clean_error(embedded_pdf, tmp_path):
    pdf_path, _ = embedded_pdf
    r = _run(pdf_path, tmp_path / "out", "--mode", "embedded", "--pages", "abc")
    assert r.returncode == 1
    assert "ERROR:" in r.stderr
    assert "pages" in r.stderr.lower()
    assert "Traceback" not in r.stderr


def test_paper_slug_sanitized_no_path_escape(embedded_pdf, tmp_path):
    pdf_path, _ = embedded_pdf
    out = tmp_path / "out"
    r = _run(pdf_path, out, "--mode", "embedded", "--paper-slug", "../../evil")
    assert r.returncode == 0, r.stderr
    # slug must be sanitized (no "..") and stay under out. _sanitize_slug maps
    # each non-alnum char to '_', so "../../evil" -> "______evil" (6 underscores).
    slug_dir = out / "______evil"
    assert ".." not in str(slug_dir.resolve())
    assert (slug_dir / "manifest.json").is_file()


def test_unknown_format_warning(detect_pdf, tmp_path):
    r = _run(detect_pdf, tmp_path / "out", "--mode", "detect", "--paper-slug", "p",
             "--min-area-ratio", "0.02", "--formats", "svg,tiff")
    assert r.returncode == 0, r.stderr
    m = manifest.Manifest.load(tmp_path / "out" / "p" / "manifest.json")
    codes = [w.code for w in m.warnings]
    assert codes.count("WARN_UNKNOWN_FORMAT") == 2


def test_page_out_of_range_warning(embedded_pdf, tmp_path):
    pdf_path, _ = embedded_pdf
    r = _run(pdf_path, tmp_path / "out", "--mode", "embedded", "--paper-slug", "p",
             "--pages", "1,99")
    assert r.returncode == 0, r.stderr
    m = manifest.Manifest.load(tmp_path / "out" / "p" / "manifest.json")
    codes = [w.code for w in m.warnings]
    assert "WARN_PAGE_OUT_OF_RANGE" in codes
    assert any(w.page == 99 for w in m.warnings if w.code == "WARN_PAGE_OUT_OF_RANGE")


def test_pages_zero_clean_error(embedded_pdf, tmp_path):
    pdf_path, _ = embedded_pdf
    r = _run(pdf_path, tmp_path / "out", "--mode", "embedded", "--paper-slug", "p", "--pages", "0")
    assert r.returncode == 1
    assert "ERROR:" in r.stderr
    assert ">= 1" in r.stderr or "page" in r.stderr.lower()
    assert "Traceback" not in r.stderr


def test_pages_negative_clean_error(embedded_pdf, tmp_path):
    pdf_path, _ = embedded_pdf
    r = _run(pdf_path, tmp_path / "out", "--mode", "embedded", "--paper-slug", "p", "--pages", "1,-5")
    assert r.returncode == 1
    assert "ERROR:" in r.stderr
    assert "Traceback" not in r.stderr


def test_overwrite_missing_pdf_preserves_existing(embedded_pdf, tmp_path):
    pdf_path, _ = embedded_pdf
    out = tmp_path / "out"
    assert _run(pdf_path, out, "--paper-slug", "p").returncode == 0
    manifest_before = (out / "p" / "manifest.json").read_text()
    r = _run(tmp_path / "nonexistent.pdf", out, "--paper-slug", "p", "--overwrite")
    assert r.returncode == 1
    assert (out / "p" / "manifest.json").is_file()
    assert (out / "p" / "manifest.json").read_text() == manifest_before


# ===== Phase 5: auto mode tests (FakeDetector, no real model) =====
# These call main() IN-PROCESS (not via _run subprocess) so monkeypatch on
# model_detect.DocLayoutYoloDetector takes effect.

def _auto_main(monkeypatch, regions_per_page, *cli_args):
    """Run the dispatcher in-process with FakeDetector patched in."""
    import model_detect
    fake = model_detect.FakeDetector(regions_per_page)
    monkeypatch.setattr(model_detect, "DocLayoutYoloDetector", lambda: fake)
    import extract_pdf_figures
    return extract_pdf_figures.main(list(cli_args))


def test_auto_mode_crops_figure_and_caption(vector_pdf, tmp_path, monkeypatch, capsys):
    regions = [
        ("figure", [100, 100, 400, 300], 0.9),
        ("figure_caption", [100, 310, 400, 360], 0.8),
    ]
    import model_detect
    regions_per_page = {1: [
        model_detect.LayoutRegion(bbox, label, conf)
        for (label, bbox, conf) in regions
    ]}
    out = tmp_path / "out"
    rc = _auto_main(monkeypatch, regions_per_page,
                    str(vector_pdf), "--mode", "auto", "--paper-slug", "p", "--dpi", "150",
                    "--out", str(out))
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    assert "figures: 1" in captured.out
    m = manifest.Manifest.load(out / "p" / "manifest.json")
    assert len(m.figures) == 1
    f = m.figures[0]
    assert f.id == "fig_p0001_01"
    assert f.bbox_pdf_points == [100, 100, 400, 360]   # merged figure+caption
    assert f.extraction_method == "manual-bbox"        # reuses crop_figures
    assert (out / "p" / "figures" / "fig_p0001_01" / "fig_p0001_01.pdf").is_file()
    assert (out / "p" / "figures" / "fig_p0001_01" / "fig_p0001_01.png").is_file()
    assert manifest.validate(m.to_dict()) == []


def test_auto_mode_dry_run_no_figures_dir(vector_pdf, tmp_path, monkeypatch, capsys):
    import model_detect
    regions_per_page = {1: [
        model_detect.LayoutRegion([100, 100, 400, 300], "figure", 0.9),
    ]}
    out = tmp_path / "out"
    rc = _auto_main(monkeypatch, regions_per_page,
                    str(vector_pdf), "--mode", "auto", "--paper-slug", "p", "--dry-run",
                    "--out", str(out))
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    assert "candidates:" in captured.out
    assert not (out / "p" / "figures").exists()
    assert not (out / "p" / "manifest.json").exists()


def test_auto_mode_min_confidence_filters(vector_pdf, tmp_path, monkeypatch, capsys):
    import model_detect
    regions_per_page = {1: [
        model_detect.LayoutRegion([100, 100, 400, 300], "figure", 0.2),
    ]}
    out = tmp_path / "out"
    rc = _auto_main(monkeypatch, regions_per_page,
                    str(vector_pdf), "--mode", "auto", "--paper-slug", "p",
                    "--out", str(out))
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    m = manifest.Manifest.load(out / "p" / "manifest.json")
    assert len(m.figures) == 0
    assert "WARN_NO_FIGURES" in [w.code for w in m.warnings]


def test_auto_mode_missing_ml_deps_errors(vector_pdf, tmp_path, monkeypatch, capsys):
    # Simulate torch missing: hide the modules so the pre-flight import fails.
    import builtins
    real_import = builtins.__import__
    def fake_import(name, *a, **k):
        if name in ("torch", "doclayout_yolo", "huggingface_hub"):
            raise ImportError(f"{name} not found")
        return real_import(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", fake_import)
    import extract_pdf_figures
    rc = extract_pdf_figures.main([str(vector_pdf), "--mode", "auto", "--paper-slug", "p",
                                  "--out", str(tmp_path / "out")])
    captured = capsys.readouterr()
    assert rc == 1
    assert "ML backend" in captured.err or "requirements-ml.txt" in captured.err
    assert "Traceback" not in captured.err


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


def test_auto_mode_old_style_labels_no_crash(vector_pdf, tmp_path, monkeypatch, capsys):
    """Old-style --labels figure,figure_caption must not crash (caption ignored)."""
    import model_detect
    regions = [
        model_detect.LayoutRegion([100, 100, 400, 300], "figure", 0.9),
        model_detect.LayoutRegion([100, 310, 400, 360], "figure_caption", 0.8),
    ]
    fake = model_detect.FakeDetector({1: regions})
    monkeypatch.setattr(model_detect, "DocLayoutYoloDetector", lambda: fake)
    import extract_pdf_figures
    rc = extract_pdf_figures.main([str(vector_pdf), "--mode", "auto", "--paper-slug", "p",
                                   "--labels", "figure,figure_caption", "--dpi", "150",
                                   "--out", str(tmp_path / "out")])
    out = capsys.readouterr()
    assert rc == 0, out.err
    assert "Traceback" not in out.err
    # figure group produces 1 figure; figure_caption group is skipped (caption label)
    assert "figures: 1" in out.out
    assert "tables: 0" in out.out


def test_auto_mode_separates_algorithm(tmp_path, monkeypatch, capsys):
    """A table whose cropped text contains 'Algorithm N' -> moved to algorithms/."""
    import model_detect
    # build a 1-page PDF whose table region crops to algorithm-looking text
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


def test_auto_mode_caption_rescan_recovers_table_caption(tmp_path, monkeypatch, capsys):
    """Table with no table_caption pair, but a 'Table N:' in plain text -> merged."""
    import model_detect
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.draw_rect(fitz.Rect(100, 100, 400, 200), color=(0, 0, 0), width=1)
    page.insert_text((100, 220), "Table 1: Real caption below.", fontsize=10)
    tbl_pdf = tmp_path / "tbl.pdf"
    doc.save(str(tbl_pdf)); doc.close()
    # detector returns: table + a plain_text region covering the caption
    regions = [
        model_detect.LayoutRegion([100, 100, 400, 200], "table", 0.9),
        model_detect.LayoutRegion([100, 210, 400, 230], "plain text", 0.9),  # misclassified caption
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


def test_auto_caption_driven_fallback_rescues_orphan_table(tmp_path, monkeypatch, capsys):
    """table_caption detected but no table primary -> fallback infers + crops a table.

    WITH --caption-driven-fallback: 1 table rescued (caption_source="caption-driven",
    bbox extends below the caption into the inferred body). WITHOUT the flag: 0 tables
    (orphan caption dropped) - backward compat.
    """
    import model_detect, fitz
    # build a page with a caption and dense body text below it
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((135, 120), "Table 1: caption.", fontsize=10)
    for i in range(5):
        page.insert_text((135, 160 + i * 25), "row col1 col2 col3", fontsize=9)
    fake_pdf = tmp_path / "fake.pdf"
    doc.save(str(fake_pdf)); doc.close()

    # detector returns ONLY a table_caption (orphan) - no table primary
    regions = [model_detect.LayoutRegion([130, 105, 480, 130], "table_caption", 0.9)]
    fake = model_detect.FakeDetector({1: regions})
    monkeypatch.setattr(model_detect, "DocLayoutYoloDetector", lambda: fake)
    import extract_pdf_figures
    # WITHOUT fallback: 0 tables (orphan caption dropped)
    rc = extract_pdf_figures.main([str(fake_pdf), "--mode", "auto", "--paper-slug", "p",
                                   "--dpi", "150", "--out", str(tmp_path / "out1")])
    out1 = capsys.readouterr()
    assert rc == 0, out1.err
    assert "tables: 0" in out1.out
    # WITH fallback: 1 table rescued
    rc = extract_pdf_figures.main([str(fake_pdf), "--mode", "auto", "--paper-slug", "p",
                                   "--dpi", "150", "--caption-driven-fallback",
                                   "--out", str(tmp_path / "out2")])
    out2 = capsys.readouterr()
    assert rc == 0, out2.err
    assert "tables: 1" in out2.out
    m = manifest.Manifest.load(tmp_path / "out2" / "p" / "manifest.json")
    assert len(m.tables) == 1
    assert m.tables[0].caption_source == "caption-driven"
    # bbox should extend below the caption (body inferred)
    assert m.tables[0].bbox_pdf_points[3] > 150
    assert manifest.validate(m.to_dict()) == []


def test_auto_caption_driven_fallback_default_off(tmp_path, monkeypatch, capsys):
    """Without the flag, orphan captions are NOT rescued (backward compat)."""
    import model_detect, fitz
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((135, 120), "Table 1: caption.", fontsize=10)
    for i in range(5):
        page.insert_text((135, 160 + i * 25), "row col1 col2 col3", fontsize=9)
    fake_pdf = tmp_path / "fake.pdf"; doc.save(str(fake_pdf)); doc.close()
    regions = [model_detect.LayoutRegion([130, 105, 480, 130], "table_caption", 0.9)]
    fake = model_detect.FakeDetector({1: regions})
    monkeypatch.setattr(model_detect, "DocLayoutYoloDetector", lambda: fake)
    import extract_pdf_figures
    rc = extract_pdf_figures.main([str(fake_pdf), "--mode", "auto", "--paper-slug", "p",
                                   "--dpi", "150", "--out", str(tmp_path / "out")])
    out = capsys.readouterr()
    assert rc == 0, out.err
    assert "tables: 0" in out.out  # no fallback -> 0 tables


def test_auto_caption_driven_fallback_skips_when_table_not_in_labels(vector_pdf, tmp_path, monkeypatch, capsys):
    """--labels figure --caption-driven-fallback must NOT create table groups."""
    import model_detect, fitz
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((135, 120), "Table 1: caption.", fontsize=10)
    for i in range(5):
        page.insert_text((135, 160 + i * 25), "row col1 col2 col3", fontsize=9)
    fake_pdf = tmp_path / "fake.pdf"; doc.save(str(fake_pdf)); doc.close()
    regions = [model_detect.LayoutRegion([130, 105, 480, 130], "table_caption", 0.9)]
    fake = model_detect.FakeDetector({1: regions})
    monkeypatch.setattr(model_detect, "DocLayoutYoloDetector", lambda: fake)
    import extract_pdf_figures
    rc = extract_pdf_figures.main([str(fake_pdf), "--mode", "auto", "--paper-slug", "p",
                                   "--labels", "figure", "--caption-driven-fallback",
                                   "--dpi", "150", "--out", str(tmp_path / "out")])
    out = capsys.readouterr()
    assert rc == 0, out.err
    assert "tables: 0" in out.out  # no table group created


# ===== Phase 5.3: render mode tests =====

def test_render_mode_whole_pages(multi_page_pdf, tmp_path):
    """--mode render with no --config renders whole pages -> pages/*.png + contact sheet."""
    out = tmp_path / "out"
    r = _run(multi_page_pdf, out, "--mode", "render", "--paper-slug", "p", "--dpi", "72")
    assert r.returncode == 0, r.stderr
    assert "rendered:" in r.stdout
    m = manifest.Manifest.load(out / "p" / "manifest.json")
    assert len(m.rendered) >= 1
    assert (out / "p" / "pages" / "p0001.png").is_file()
    assert (out / "p" / "summary_contact_sheet.png").is_file()
    assert manifest.validate(m.to_dict()) == []


def test_render_mode_with_config_regions(vector_pdf, tmp_path):
    """--mode render --config renders bbox regions -> regions/*.png + contact sheet."""
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "figures:\n"
        "  - id: r1\n"
        "    page: 1\n"
        "    bbox: [60, 60, 210, 210]\n"
    )
    out = tmp_path / "out"
    r = _run(vector_pdf, out, "--mode", "render", "--config", str(cfg),
             "--paper-slug", "p", "--dpi", "72")
    assert r.returncode == 0, r.stderr
    m = manifest.Manifest.load(out / "p" / "manifest.json")
    assert len(m.rendered) == 1
    assert m.rendered[0].id == "r1"
    assert (out / "p" / "regions" / "r1.png").is_file()
    assert (out / "p" / "summary_contact_sheet.png").is_file()


def test_render_mode_pages_filter(multi_page_pdf, tmp_path):
    """--mode render --pages 1 renders only page 1 (not page 2)."""
    out = tmp_path / "out"
    r = _run(multi_page_pdf, out, "--mode", "render", "--paper-slug", "p",
             "--pages", "1", "--dpi", "72")
    assert r.returncode == 0, r.stderr
    assert (out / "p" / "pages" / "p0001.png").is_file()
    assert not (out / "p" / "pages" / "p0002.png").exists()


def test_render_mode_warn_no_rendered(tmp_path):
    """All pages out of range -> WARN_NO_RENDERED."""
    import fitz
    doc = fitz.open(); doc.new_page(); doc.new_page()
    pdf = tmp_path / "two.pdf"; doc.save(str(pdf)); doc.close()
    out = tmp_path / "out"
    r = _run(pdf, out, "--mode", "render", "--paper-slug", "p", "--pages", "99")
    assert r.returncode == 0, r.stderr
    m = manifest.Manifest.load(out / "p" / "manifest.json")
    assert "WARN_NO_RENDERED" in [w.code for w in m.warnings]
    assert len(m.rendered) == 0
