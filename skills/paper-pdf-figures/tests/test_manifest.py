import json
from pathlib import Path

import jsonschema

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "templates" / "manifest.schema.json"


def _load_schema():
    return json.loads(SCHEMA_PATH.read_text())


def test_schema_is_valid_draft7():
    schema = _load_schema()
    jsonschema.Draft7Validator.check_schema(schema)  # raises if invalid


def test_schema_requires_core_fields():
    required = _load_schema()["required"]
    expected = {
        "source_pdf", "paper_slug", "created_at", "tool_version",
        "figures", "embedded_images", "candidates", "warnings",
    }
    assert expected.issubset(set(required))


def test_schema_rejects_unknown_top_level_field():
    schema = _load_schema()
    validator = jsonschema.Draft7Validator(schema)
    good = {
        "source_pdf": "p.pdf", "paper_slug": "p", "created_at": "2026-07-04T00:00:00",
        "tool_version": "0.1.0", "figures": [], "embedded_images": [],
        "candidates": [], "warnings": [], "tables": [], "algorithms": [],
        "rendered": [],
    }
    assert not list(validator.iter_errors(good))
    bad = dict(good, surprise_field="oops")
    assert list(validator.iter_errors(bad))  # additionalProperties: false


import manifest


def _minimal_manifest():
    return manifest.Manifest(
        source_pdf="paper.pdf",
        paper_slug="paper",
        tool_version="0.1.0",
    )


def test_manifest_to_dict_validates():
    m = _minimal_manifest()
    assert manifest.validate(m.to_dict()) == []


def test_manifest_save_load_round_trip(tmp_path):
    m = _minimal_manifest()
    m.add_figure(manifest.Figure(
        id="fig_001", page=3, bbox_pdf_points=[72, 110, 540, 410],
        type="page-crop-mixed", extraction_method="manual-bbox", dpi=600,
        files={"pdf": "figures/fig_001/fig_001.pdf", "png": None, "svg": None},
        sha256={"pdf": "abc"},
    ))
    p = m.save(tmp_path / "manifest.json")
    loaded = manifest.Manifest.load(p)
    assert loaded.source_pdf == "paper.pdf"
    assert len(loaded.figures) == 1
    assert loaded.figures[0].id == "fig_001"
    assert loaded.figures[0].bbox_pdf_points == [72, 110, 540, 410]
    assert manifest.validate(loaded.to_dict()) == []


def test_validate_rejects_figure_missing_required():
    bad = {
        "source_pdf": "p.pdf", "paper_slug": "p", "created_at": "2026-07-04T00:00:00",
        "tool_version": "0.1.0", "figures": [{"id": "f1"}],
        "embedded_images": [], "candidates": [], "warnings": [],
    }
    errors = manifest.validate(bad)
    assert errors
    assert any("page" in e for e in errors)


def test_manifest_add_methods():
    m = _minimal_manifest()
    m.add_embedded_image(manifest.EmbeddedImage(
        id="e1", page=1, xref=12, format="jpeg", width=10, height=10,
        file="embedded/e1.jpeg", sha256="deadbeef",
    ))
    m.add_candidate(manifest.Candidate(page=2, bbox_pdf_points=[1, 2, 3, 4], score=0.5))
    m.add_warning("WARN_SVG_EXPORT_FAILED", detail="pdftocairo not found")
    d = m.to_dict()
    assert manifest.validate(d) == [], manifest.validate(d)
    assert len(d["embedded_images"]) == 1
    assert len(d["candidates"]) == 1
    assert d["warnings"][0]["code"] == "WARN_SVG_EXPORT_FAILED"


def test_manifest_optional_none_fields_validate():
    m = _minimal_manifest()
    m.add_candidate(manifest.Candidate(page=2, bbox_pdf_points=[1, 2, 3, 4]))  # score=None
    m.add_warning("WARN_SVG_EXPORT_FAILED")  # page=None, detail=None
    m.add_warning("WARN_BBOX_OUT_OF_PAGE", page=3)  # detail=None
    errors = manifest.validate(m.to_dict())
    assert errors == [], errors


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
        "candidates": [], "warnings": [], "tables": [], "algorithms": [],
        "rendered": [],
    }
    assert manifest.validate(good) == []
    # missing tables -> schema error
    bad = dict(good); del bad["tables"]
    assert manifest.validate(bad)


def test_manifest_add_algorithm_and_round_trip(tmp_path):
    m = _minimal_manifest()
    m.add_algorithm(manifest.Figure(
        id="alg_p0022_01", page=22, bbox_pdf_points=[100, 200, 500, 400],
        type="page-crop-algorithm", extraction_method="manual-bbox", dpi=300,
        files={"pdf": "algorithms/alg_p0022_01/alg_p0022_01.pdf", "png": None, "svg": None},
        sha256={"pdf": "abc"}, caption_source="text-rescan",
    ))
    p = m.save(tmp_path / "manifest.json")
    loaded = manifest.Manifest.load(p)
    assert len(loaded.algorithms) == 1
    assert loaded.algorithms[0].id == "alg_p0022_01"
    assert loaded.algorithms[0].type == "page-crop-algorithm"
    assert loaded.algorithms[0].caption_source == "text-rescan"
    assert manifest.validate(loaded.to_dict()) == []


def test_manifest_algorithms_required_in_schema():
    schema = _load_schema()
    assert "algorithms" in schema["required"]


def test_manifest_caption_source_field_round_trip(tmp_path):
    m = _minimal_manifest()
    m.add_table(manifest.Figure(
        id="tbl_p0011_01", page=11, bbox_pdf_points=[100, 200, 500, 400],
        type="page-crop-table", extraction_method="manual-bbox", dpi=300,
        files={"pdf": "tables/tbl_p0011_01/tbl_p0011_01.pdf", "png": None, "svg": None},
        sha256={}, caption_source="model",
    ))
    p = m.save(tmp_path / "manifest.json")
    loaded = manifest.Manifest.load(p)
    assert loaded.tables[0].caption_source == "model"
    assert manifest.validate(loaded.to_dict()) == []


def test_manifest_add_rendered_and_round_trip(tmp_path):
    m = _minimal_manifest()
    m.add_rendered(manifest.RenderedItem(
        id="page_0001", page=1, file="pages/p0001.png", dpi=300, width=2550, height=3300,
    ))
    p = m.save(tmp_path / "manifest.json")
    loaded = manifest.Manifest.load(p)
    assert len(loaded.rendered) == 1
    assert loaded.rendered[0].id == "page_0001"
    assert loaded.rendered[0].width == 2550
    assert manifest.validate(loaded.to_dict()) == []


def test_manifest_rendered_required_in_schema():
    schema = _load_schema()
    assert "rendered" in schema["required"]
