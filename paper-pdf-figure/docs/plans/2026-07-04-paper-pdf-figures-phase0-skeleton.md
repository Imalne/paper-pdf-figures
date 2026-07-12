# Paper PDF Figures — Phase 0 (Skeleton) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the `paper-pdf-figures` skill scaffold so Claude Code recognizes `/paper-pdf-figures`, dependencies can be checked, and the manifest data structure + schema are in place and validated — before any extraction logic is added in Phase 1.

**Architecture:** A Claude Code skill at `.claude/skills/paper-pdf-figures/` with a thin `SKILL.md` entry, a `manifest.py` module (dataclasses + JSON-schema validation), a `check_deps.py` that reports per-mode availability, and an `install_deps.sh`. No PDF processing yet — Phase 0 only delivers the skeleton + manifest schema + dependency checker.

**Tech Stack:** Python ≥3.9, PyMuPDF/Pillow/PyYAML/numpy/opencv (runtime, not exercised yet), pytest + jsonschema (dev/test).

## Global Constraints

(From the spec `paper-pdf-figure/docs/designs/paper-pdf-figure.md` — every task inherits these.)

- Skill name: `paper-pdf-figures` (plural); skill root: `.claude/skills/paper-pdf-figures/`
- Never modify the original PDF; offline by default; no network, no uploads
- `manifest.json` is the single source of truth — no per-figure `metadata.json`
- `tool_version` is read from `VERSION` file; initial version `0.1.0`
- `allowed-tools` in SKILL.md frontmatter: exactly `Bash(python3 *)`, `Read`, `Write`
- External binaries (`pdftocairo`, `pdfimages`, `mutool`) are optional — missing ones must degrade gracefully, not crash
- Subprocess calls use list form (no shell); filenames sanitized; output confined to user-specified dir
- Tests run from the skill root: `cd .claude/skills/paper-pdf-figures && pytest tests/`

---

## File Structure

Phase 0 creates these files. Each has one responsibility.

| Path | Responsibility |
| --- | --- |
| `.claude/skills/paper-pdf-figures/SKILL.md` | Skill entry: frontmatter + short workflow, references docs/ |
| `.claude/skills/paper-pdf-figures/README.md` | Human overview: what it does, deps, install, security note |
| `.claude/skills/paper-pdf-figures/VERSION` | Single line `0.1.0`; source of truth for `tool_version` |
| `.claude/skills/paper-pdf-figures/requirements.txt` | Runtime Python deps |
| `.claude/skills/paper-pdf-figures/requirements-dev.txt` | Dev/test deps (pytest, jsonschema) |
| `.claude/skills/paper-pdf-figures/templates/manifest.schema.json` | JSON Schema (draft-07) for manifest.json |
| `.claude/skills/paper-pdf-figures/scripts/manifest.py` | Manifest dataclasses + schema validation + load/save |
| `.claude/skills/paper-pdf-figures/scripts/check_deps.py` | Check Python modules + binaries; report per-mode availability |
| `.claude/skills/paper-pdf-figures/scripts/install_deps.sh` | Install pip + apt deps with sudo detection |
| `.claude/skills/paper-pdf-figures/tests/conftest.py` | pytest config: add `scripts/` to sys.path |
| `.claude/skills/paper-pdf-figures/tests/test_manifest.py` | Tests for manifest.py |
| `.claude/skills/paper-pdf-figures/tests/test_check_deps.py` | Tests for check_deps.py |

Later phases add `extract_pdf_figures.py`, `extract_embedded.py`, `crop_export.py`, `figure_detect.py`, `render_pages.py`, `contact_sheet.py`, `package.sh`, `docs/*`, `tests/fixtures/*`.

---

## Task 1: Scaffold skill directory + metadata

**Files:**
- Create: `.claude/skills/paper-pdf-figures/SKILL.md`
- Create: `.claude/skills/paper-pdf-figures/README.md`
- Create: `.claude/skills/paper-pdf-figures/VERSION`
- Create: `.claude/skills/paper-pdf-figures/requirements.txt`
- Create: `.claude/skills/paper-pdf-figures/requirements-dev.txt`
- Create: `.claude/skills/paper-pdf-figures/scripts/.gitkeep`
- Create: `.claude/skills/paper-pdf-figures/templates/.gitkeep`
- Create: `.claude/skills/paper-pdf-figures/docs/.gitkeep`

**Interfaces:**
- Produces: `VERSION` file containing exactly `0.1.0\n` — later tasks read it via `pathlib.Path("VERSION").read_text().strip()`.
- Produces: `SKILL.md` with frontmatter `name: paper-pdf-figures` and `allowed-tools: [Bash(python3 *), Read, Write]`.

- [ ] **Step 1: Create directory structure and empty placeholders**

Run:
```bash
cd /home/imalne/learn_vibe_coding
mkdir -p .claude/skills/paper-pdf-figures/{scripts,templates,tests,docs,tests/fixtures}
touch .claude/skills/paper-pdf-figures/{scripts,templates,docs}/.gitkeep
```

- [ ] **Step 2: Write `VERSION`**

File `.claude/skills/paper-pdf-figures/VERSION`:
```
0.1.0
```

- [ ] **Step 3: Write `SKILL.md`**

File `.claude/skills/paper-pdf-figures/SKILL.md`:
````markdown
---
name: paper-pdf-figures
description: Extract and save figures from academic PDF papers, including embedded raster images and vector-preserving page crops. Use when the user wants to extract, crop, archive, or batch-save images/figures from research papers.
allowed-tools:
  - Bash(python3 *)
  - Read
  - Write
---

# Paper PDF Figures

Use this skill when the user wants to extract or save figures from academic PDF files.

## Main workflow

1. Identify the input PDF path and output directory.
2. Check dependencies:
   ```bash
   python3 ${CLAUDE_SKILL_DIR}/scripts/check_deps.py
   ```
3. Choose an extraction mode:
   * `embedded`: extract original embedded raster images.
   * `manual`: crop figure regions from user-provided bbox config.
   * `detect`: dry-run candidate figure detection (no crop).
   * `render`: render full pages or selected regions to PNG.
   * `auto`: run embedded + detect + (optional) manual, plus contact sheet.
4. Run:
   ```bash
   python3 ${CLAUDE_SKILL_DIR}/scripts/extract_pdf_figures.py "$ARGUMENTS"
   ```
5. Report:
   * number of embedded images extracted;
   * number of figure crops exported;
   * output directory;
   * manifest path;
   * warnings or failed pages.

## Important rules

* Never modify the original PDF.
* Do not upload PDFs or images to external services.
* Prefer vector-preserving PDF/SVG export for page-level figures.
* Use high-DPI PNG only as preview or raster fallback.
* `detect` only outputs candidates — do not auto-crop; ask the user to confirm bbox.

## Additional references

* Detailed workflow: docs/workflow.md
* Extraction modes: docs/extraction-modes.md
* Troubleshooting: docs/troubleshooting.md
````

- [ ] **Step 4: Write `README.md`**

File `.claude/skills/paper-pdf-figures/README.md`:
```markdown
# paper-pdf-figures

A Claude Code skill that extracts and saves figures from academic PDF papers: embedded raster images, vector-preserving page crops, candidate detection (dry-run), and high-DPI PNG previews. Offline; never modifies the source PDF.

## Install

```bash
pip install -r requirements.txt
bash scripts/install_deps.sh   # optional system packages (poppler-utils)
python3 scripts/check_deps.py  # verify
```

Then place this directory under `.claude/skills/` (project) or `~/.claude/skills/` (user).

## Modes

| Mode | What it does |
| --- | --- |
| `embedded` | Extract embedded raster images (JPEG/PNG/JP2/TIFF). |
| `manual` | Crop figure regions from a `config.yaml` of bbox values. |
| `detect` | Dry-run: output candidate figure bboxes + preview images. |
| `render` | Render full pages or regions to PNG. |
| `auto` | Run embedded + detect + optional manual, plus a contact sheet. |

## Security

No network, no uploads, no unrequested deletes. Output is confined to the user-specified directory. External commands are called with argument lists (no shell). See the design doc at `paper-pdf-figure/docs/designs/paper-pdf-figure.md`.
```

- [ ] **Step 5: Write `requirements.txt` and `requirements-dev.txt`**

File `.claude/skills/paper-pdf-figures/requirements.txt`:
```
pymupdf>=1.23.0
pillow>=10.0.0
pyyaml>=6.0
numpy>=1.24.0
opencv-python>=4.8.0
```

File `.claude/skills/paper-pdf-figures/requirements-dev.txt`:
```
-r requirements.txt
pytest>=7.4.0
jsonschema>=4.20.0
```

- [ ] **Step 6: Verify SKILL.md frontmatter parses as YAML**

Run:
```bash
cd /home/imalne/learn_vibe_coding
python3 -c "import yaml,sys; d=yaml.safe_load(open('.claude/skills/paper-pdf-figures/SKILL.md').read().split('---')[1]); assert d['name']=='paper-pdf-figures'; assert d['allowed-tools']==['Bash(python3 *)','Read','Write']; print('ok')"
```
Expected output: `ok`

- [ ] **Step 7: Commit**

```bash
git add .claude/skills/paper-pdf-figures/
git commit -m "feat(paper-pdf-figures): scaffold skill directory and metadata (Phase 0)"
```

---

## Task 2: Manifest JSON Schema + test config

**Files:**
- Create: `.claude/skills/paper-pdf-figures/templates/manifest.schema.json`
- Create: `.claude/skills/paper-pdf-figures/tests/conftest.py`
- Create: `.claude/skills/paper-pdf-figures/tests/test_manifest.py`

**Interfaces:**
- Produces: `templates/manifest.schema.json` — a draft-07 JSON Schema. Task 3's `manifest.py` will load this file to validate manifests.
- Produces: `tests/conftest.py` — inserts `scripts/` on `sys.path` so tests can `import manifest`, `import check_deps`.

- [ ] **Step 1: Write `tests/conftest.py`**

File `.claude/skills/paper-pdf-figures/tests/conftest.py`:
```python
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
```

- [ ] **Step 2: Write the schema**

File `.claude/skills/paper-pdf-figures/templates/manifest.schema.json`:
```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "PaperPdfFiguresManifest",
  "type": "object",
  "required": ["source_pdf", "paper_slug", "created_at", "tool_version", "figures", "embedded_images", "candidates", "warnings"],
  "additionalProperties": false,
  "properties": {
    "source_pdf": {"type": "string"},
    "paper_slug": {"type": "string"},
    "created_at": {"type": "string", "format": "date-time"},
    "tool_version": {"type": "string"},
    "run_args": {"type": "object"},
    "figures": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["id", "page", "bbox_pdf_points", "type", "files", "extraction_method", "dpi"],
        "additionalProperties": false,
        "properties": {
          "id": {"type": "string"},
          "page": {"type": "integer", "minimum": 1},
          "bbox_pdf_points": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4},
          "type": {"type": "string"},
          "caption": {"type": "string"},
          "files": {
            "type": "object",
            "additionalProperties": false,
            "properties": {
              "pdf": {"type": ["string", "null"]},
              "png": {"type": ["string", "null"]},
              "svg": {"type": ["string", "null"]}
            }
          },
          "sha256": {
            "type": "object",
            "additionalProperties": false,
            "properties": {
              "pdf": {"type": "string"},
              "png": {"type": "string"},
              "svg": {"type": "string"}
            }
          },
          "extraction_method": {"type": "string"},
          "dpi": {"type": "integer", "minimum": 1}
        }
      }
    },
    "embedded_images": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["id", "page", "xref", "format", "width", "height", "file", "sha256"],
        "additionalProperties": false,
        "properties": {
          "id": {"type": "string"},
          "page": {"type": "integer", "minimum": 1},
          "xref": {"type": "integer", "minimum": 1},
          "format": {"type": "string"},
          "width": {"type": "integer", "minimum": 1},
          "height": {"type": "integer", "minimum": 1},
          "file": {"type": "string"},
          "sha256": {"type": "string"}
        }
      }
    },
    "candidates": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["page", "bbox_pdf_points"],
        "additionalProperties": false,
        "properties": {
          "page": {"type": "integer", "minimum": 1},
          "bbox_pdf_points": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4},
          "score": {"type": ["number", "null"]}
        }
      }
    },
    "warnings": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["code"],
        "additionalProperties": false,
        "properties": {
          "code": {"type": "string"},
          "page": {"type": ["integer", "null"], "minimum": 1},
          "detail": {"type": ["string", "null"]}
        }
      }
    }
  }
}
```

- [ ] **Step 3: Write the failing schema tests**

File `.claude/skills/paper-pdf-figures/tests/test_manifest.py`:
```python
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
        "candidates": [], "warnings": [],
    }
    assert not list(validator.iter_errors(good))
    bad = dict(good, surprise_field="oops")
    assert list(validator.iter_errors(bad))  # additionalProperties: false
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
cd /home/imalne/learn_vibe_coding/.claude/skills/paper-pdf-figures
pip install -q jsonschema pytest
pytest tests/test_manifest.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
cd /home/imalne/learn_vibe_coding
git add .claude/skills/paper-pdf-figures/templates/manifest.schema.json .claude/skills/paper-pdf-figures/tests/
git commit -m "feat(paper-pdf-figures): add manifest JSON schema and test config (Phase 0)"
```

---

## Task 3: Manifest dataclasses + validation + load/save

**Files:**
- Create: `.claude/skills/paper-pdf-figures/scripts/manifest.py`
- Modify: `.claude/skills/paper-pdf-figures/tests/test_manifest.py` (append tests)

**Interfaces:**
- Produces: `manifest.Manifest(source_pdf, paper_slug, tool_version, ...)` dataclass with `.add_figure()`, `.add_embedded_image()`, `.add_candidate()`, `.add_warning(code, page=None, detail=None)`, `.to_dict()`, `.save(path)`, `.load(path)` classmethod, `.from_dict(d)` classmethod.
- Produces: `manifest.Figure`, `manifest.EmbeddedImage`, `manifest.Candidate`, `manifest.WarningEntry` dataclasses (field names match `templates/manifest.schema.json` exactly).
- Produces: `manifest.validate(manifest_dict, schema_path=SCHEMA_PATH) -> list[str]` — returns error messages; empty list = valid. Phase 1+ will call this after each run.

- [ ] **Step 1: Write the failing tests (append to `tests/test_manifest.py`)**

Append to `.claude/skills/paper-pdf-figures/tests/test_manifest.py`:
```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd /home/imalne/learn_vibe_coding/.claude/skills/paper-pdf-figures
pytest tests/test_manifest.py -v
```
Expected: the 4 new tests FAIL with `ModuleNotFoundError: No module named 'manifest'` (the 3 schema tests from Task 2 still pass).

- [ ] **Step 3: Write `scripts/manifest.py`**

File `.claude/skills/paper-pdf-figures/scripts/manifest.py`:
```python
"""Manifest data structure and schema validation for paper-pdf-figures."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import jsonschema
except ImportError:  # pragma: no cover
    jsonschema = None

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "templates" / "manifest.schema.json"


@dataclass
class Figure:
    id: str
    page: int
    bbox_pdf_points: list[float]
    type: str
    extraction_method: str
    dpi: int
    files: dict[str, str | None] = field(
        default_factory=lambda: {"pdf": None, "png": None, "svg": None}
    )
    sha256: dict[str, str] = field(default_factory=dict)
    caption: str = ""


@dataclass
class EmbeddedImage:
    id: str
    page: int
    xref: int
    format: str
    width: int
    height: int
    file: str
    sha256: str


@dataclass
class Candidate:
    page: int
    bbox_pdf_points: list[float]
    score: float | None = None


@dataclass
class WarningEntry:
    code: str
    page: int | None = None
    detail: str | None = None


@dataclass
class Manifest:
    source_pdf: str
    paper_slug: str
    tool_version: str
    created_at: str = field(
        default_factory=lambda: datetime.now().isoformat(timespec="seconds")
    )
    run_args: dict[str, Any] = field(default_factory=dict)
    figures: list[Figure] = field(default_factory=list)
    embedded_images: list[EmbeddedImage] = field(default_factory=list)
    candidates: list[Candidate] = field(default_factory=list)
    warnings: list[WarningEntry] = field(default_factory=list)

    def add_figure(self, fig: Figure) -> None:
        self.figures.append(fig)

    def add_embedded_image(self, img: EmbeddedImage) -> None:
        self.embedded_images.append(img)

    def add_candidate(self, cand: Candidate) -> None:
        self.candidates.append(cand)

    def add_warning(self, code: str, page: int | None = None, detail: str | None = None) -> None:
        self.warnings.append(WarningEntry(code=code, page=page, detail=detail))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def save(self, path: str | Path) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False))
        return p

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Manifest":
        return cls(
            source_pdf=d["source_pdf"],
            paper_slug=d["paper_slug"],
            tool_version=d["tool_version"],
            created_at=d.get("created_at", ""),
            run_args=d.get("run_args", {}),
            figures=[Figure(**f) for f in d.get("figures", [])],
            embedded_images=[EmbeddedImage(**e) for e in d.get("embedded_images", [])],
            candidates=[Candidate(**c) for c in d.get("candidates", [])],
            warnings=[WarningEntry(**w) for w in d.get("warnings", [])],
        )

    @classmethod
    def load(cls, path: str | Path) -> "Manifest":
        return cls.from_dict(json.loads(Path(path).read_text()))


def validate(manifest_dict: dict[str, Any], schema_path: str | Path = SCHEMA_PATH) -> list[str]:
    """Return a list of human-readable error messages; empty list means valid."""
    if jsonschema is None:
        raise RuntimeError("jsonschema not installed; pip install jsonschema")
    schema = json.loads(Path(schema_path).read_text())
    validator = jsonschema.Draft7Validator(schema)
    errors = sorted(validator.iter_errors(manifest_dict), key=lambda e: list(e.path))
    return [f"{'/'.join(map(str, e.path)) or '<root>'}: {e.message}" for e in errors]
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
cd /home/imalne/learn_vibe_coding/.claude/skills/paper-pdf-figures
pytest tests/test_manifest.py -v
```
Expected: 8 passed (3 schema + 5 manifest).

- [ ] **Step 5: Commit**

```bash
cd /home/imalne/learn_vibe_coding
git add .claude/skills/paper-pdf-figures/scripts/manifest.py .claude/skills/paper-pdf-figures/tests/test_manifest.py
git commit -m "feat(paper-pdf-figures): add manifest dataclasses, validation, load/save (Phase 0)"
```

---

## Task 4: Dependency checker

**Files:**
- Create: `.claude/skills/paper-pdf-figures/scripts/check_deps.py`
- Create: `.claude/skills/paper-pdf-figures/tests/test_check_deps.py`

**Interfaces:**
- Produces: `check_deps.collect_status(which_fn=shutil.which, module_checker=check_py_module) -> dict` — pure function, injectable fakes for testing.
- Produces: `check_deps.unavailable_modes(status) -> list[str]`, `check_deps.format_report(status) -> str`, `check_deps.has_required_missing(status) -> bool`.
- Produces: `check_deps.main() -> int` (exit code: 0 if all required deps present, 1 otherwise) — the `SKILL.md` workflow calls this script.

- [ ] **Step 1: Write the failing tests**

File `.claude/skills/paper-pdf-figures/tests/test_check_deps.py`:
```python
import check_deps


def test_check_py_module_present():
    assert check_deps.check_py_module("os") is True


def test_check_py_module_absent():
    assert check_deps.check_py_module("nope_not_a_module_xyz") is False


def test_check_binary_present():
    assert check_deps.check_binary("python3", which_fn=lambda n: f"/usr/bin/{n}") is True


def test_check_binary_absent():
    assert check_deps.check_binary("nope", which_fn=lambda n: None) is False


def _status_with(present_map):
    """Build a status dict; present_map maps display name -> bool (default True)."""
    status = {}
    for _imp, display, modes, pkg in check_deps.PY_DEPS:
        status[display] = {
            "present": present_map.get(display, True),
            "modes": set(modes), "kind": "python", "install": pkg, "optional": False,
        }
    for _name, display, optional, pkg, note in check_deps.BIN_DEPS:
        status[display] = {
            "present": present_map.get(display, True),
            "modes": set(), "kind": "binary", "install": pkg,
            "optional": optional, "note": note,
        }
    return status


def test_unavailable_modes_all_present():
    assert check_deps.unavailable_modes(_status_with({})) == []


def test_opencv_missing_blocks_detect_and_auto():
    unavail = set(check_deps.unavailable_modes(_status_with({"opencv-python": False})))
    assert {"detect", "auto"} <= unavail


def test_optional_binary_missing_does_not_block_modes():
    assert check_deps.unavailable_modes(_status_with({"pdftocairo": False})) == []


def test_has_required_missing():
    assert check_deps.has_required_missing(_status_with({"PyMuPDF": False})) is True
    assert check_deps.has_required_missing(_status_with({})) is False


def test_format_report_mentions_missing_and_note():
    report = check_deps.format_report(_status_with({"PyMuPDF": False, "pdftocairo": False}))
    assert "[MISSING] PyMuPDF" in report
    assert "[WARN] pdftocairo" in report
    assert "SVG export unavailable" in report
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd /home/imalne/learn_vibe_coding/.claude/skills/paper-pdf-figures
pytest tests/test_check_deps.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'check_deps'`.

- [ ] **Step 3: Write `scripts/check_deps.py`**

File `.claude/skills/paper-pdf-figures/scripts/check_deps.py`:
```python
#!/usr/bin/env python3
"""Check dependencies for paper-pdf-figures and report per-mode availability."""
from __future__ import annotations

import importlib
import shutil
import sys

# (import_name, display, modes_blocked_if_missing, install_pkg)
PY_DEPS = [
    ("fitz", "PyMuPDF", {"embedded", "manual", "render", "auto"}, "pymupdf"),
    ("PIL", "Pillow", {"embedded", "manual", "render", "auto"}, "pillow"),
    ("yaml", "PyYAML", {"manual", "auto"}, "pyyaml"),
    ("numpy", "numpy", {"detect", "auto"}, "numpy"),
    ("cv2", "opencv-python", {"detect", "auto"}, "opencv-python"),
]

# (binary, display, optional, install_pkg, note_if_missing)
BIN_DEPS = [
    ("pdftocairo", "pdftocairo", True, "poppler-utils",
     "SVG export unavailable (PDF+PNG still work)."),
    ("pdfimages", "pdfimages", True, "poppler-utils",
     "Embedded-image cross-check unavailable (PyMuPDF extraction still works)."),
    ("mutool", "mutool", True, "mupdf-tools",
     "Fallback extraction unavailable (not used in MVP)."),
]

ALL_MODES = {"embedded", "manual", "detect", "render", "auto"}


def check_py_module(import_name: str, importer=importlib.import_module) -> bool:
    try:
        importer(import_name)
        return True
    except ImportError:
        return False


def check_binary(name: str, which_fn=shutil.which) -> bool:
    return which_fn(name) is not None


def collect_status(which_fn=shutil.which, module_checker=check_py_module) -> dict:
    status = {}
    for imp, display, modes, pkg in PY_DEPS:
        status[display] = {
            "present": module_checker(imp),
            "modes": set(modes),
            "kind": "python",
            "install": pkg,
            "optional": False,
        }
    for name, display, optional, pkg, note in BIN_DEPS:
        status[display] = {
            "present": check_binary(name, which_fn),
            "modes": set(),
            "kind": "binary",
            "install": pkg,
            "optional": optional,
            "note": note,
        }
    return status


def unavailable_modes(status: dict) -> list[str]:
    blocked: set[str] = set()
    for info in status.values():
        if not info["present"] and info["modes"]:
            blocked |= info["modes"]
    return sorted(blocked)


def has_required_missing(status: dict) -> bool:
    return any(
        not info["present"] and info["modes"] and not info["optional"]
        for info in status.values()
    )


def format_report(status: dict) -> str:
    lines = []
    py_ok = sys.version_info >= (3, 9)
    py_ver = ".".join(map(str, sys.version_info[:3]))
    lines.append(f"[{'OK' if py_ok else 'FAIL'}] Python {py_ver} (>=3.9 required)")
    for display, info in status.items():
        if info["present"]:
            mark = "OK"
        elif info["optional"]:
            mark = "WARN"
        else:
            mark = "MISSING"
        lines.append(f"[{mark}] {display}")
    unavailable = unavailable_modes(status)
    if unavailable:
        lines.append(f"Unavailable modes (missing required deps): {', '.join(unavailable)}")
    else:
        lines.append("All modes available.")
    for display, info in status.items():
        if not info["present"] and info["kind"] == "binary":
            lines.append(f"Note: {display} missing — {info['note']}")
    return "\n".join(lines)


def main() -> int:
    status = collect_status()
    print(format_report(status))
    return 1 if has_required_missing(status) else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
cd /home/imalne/learn_vibe_coding/.claude/skills/paper-pdf-figures
pytest tests/test_check_deps.py -v
```
Expected: 9 passed.

- [ ] **Step 5: Run check_deps.py for real and confirm it reports the current (empty) environment honestly**

Run:
```bash
cd /home/imalne/learn_vibe_coding/.claude/skills/paper-pdf-figures
python3 scripts/check_deps.py; echo "exit=$?"
```
Expected: prints `[MISSING] PyMuPDF` etc. (the current system has none installed), lists unavailable modes, `exit=1`. This is correct behavior — Phase 0 does not install runtime deps.

- [ ] **Step 6: Commit**

```bash
cd /home/imalne/learn_vibe_coding
git add .claude/skills/paper-pdf-figures/scripts/check_deps.py .claude/skills/paper-pdf-figures/tests/test_check_deps.py
git commit -m "feat(paper-pdf-figures): add dependency checker with per-mode reporting (Phase 0)"
```

---

## Task 5: Dependency installer script

**Files:**
- Create: `.claude/skills/paper-pdf-figures/scripts/install_deps.sh`
- Create: `.claude/skills/paper-pdf-figures/tests/test_install_deps.py`

**Interfaces:**
- Produces: `scripts/install_deps.sh` — installs pip runtime deps + poppler-utils (if apt + sudo available). Supports `--dry-run` flag (prints plan, makes no changes). Referenced by `README.md` install instructions.

- [ ] **Step 1: Write the failing test**

File `.claude/skills/paper-pdf-figures/tests/test_install_deps.py`:
```python
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "install_deps.sh"


def test_dry_run_prints_plan_and_exits_zero():
    result = subprocess.run(
        ["bash", str(SCRIPT), "--dry-run"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "[dry-run]" in result.stdout
    assert "pip install" in result.stdout
    assert "poppler-utils" in result.stdout
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd /home/imalne/learn_vibe_coding/.claude/skills/paper-pdf-figures
pytest tests/test_install_deps.py -v
```
Expected: FAIL (file does not exist, non-zero exit).

- [ ] **Step 3: Write `scripts/install_deps.sh`**

File `.claude/skills/paper-pdf-figures/scripts/install_deps.sh`:
```bash
#!/usr/bin/env bash
# Install dependencies for paper-pdf-figures.
# Usage: bash install_deps.sh [--dry-run]
set -euo pipefail

DRY_RUN=0
if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=1
fi

run() {
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "[dry-run] $*"
  else
    "$@"
  fi
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REQS="$SCRIPT_DIR/../requirements.txt"

echo "==> Installing Python dependencies"
run python3 -m pip install --user -r "$REQS"

echo "==> Checking for system package manager"
if command -v apt-get >/dev/null 2>&1; then
  if sudo -n true 2>/dev/null; then
    echo "==> Installing poppler-utils via apt (sudo available)"
    run sudo apt-get install -y poppler-utils
  else
    echo "WARN: apt-get present but sudo not available non-interactively."
    echo "      Run manually: sudo apt-get install -y poppler-utils"
    echo "      Without poppler-utils, SVG export (pdftocairo) is unavailable."
  fi
else
  echo "WARN: apt-get not found. Install poppler-utils manually for SVG export."
  echo "      Without poppler-utils, SVG export (pdftocairo) is unavailable."
fi

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "==> [dry-run] Done (no changes made)"
else
  echo "==> Done. Verify with: python3 scripts/check_deps.py"
fi
```

- [ ] **Step 4: Make the script executable and run the test**

Run:
```bash
cd /home/imalne/learn_vibe_coding/.claude/skills/paper-pdf-figures
chmod +x scripts/install_deps.sh
pytest tests/test_install_deps.py -v
```
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
cd /home/imalne/learn_vibe_coding
git add .claude/skills/paper-pdf-figures/scripts/install_deps.sh .claude/skills/paper-pdf-figures/tests/test_install_deps.py
git commit -m "feat(paper-pdf-figures): add install_deps.sh with dry-run mode (Phase 0)"
```

---

## Phase 0 Acceptance

After all 5 tasks, verify the full Phase 0 acceptance criteria from the spec (§11 Phase 0):

- [ ] **A1: Skill is recognized.** `SKILL.md` frontmatter parses with `name: paper-pdf-figures` and the three `allowed-tools` entries (verified in Task 1 Step 6).
- [ ] **A2: check_deps reports per-mode availability.** `python3 scripts/check_deps.py` runs, prints OK/WARN/MISSING per dep, lists unavailable modes, exits 1 when required deps missing (verified in Task 4 Step 5).
- [ ] **A3: manifest loads/validates.** `manifest.Manifest` round-trips through save/load and validates against the schema (verified in Task 3 Step 4).
- [ ] **A4: Full test suite passes.** Run:
  ```bash
  cd /home/imalne/learn_vibe_coding/.claude/skills/paper-pdf-figures
  pip install -q -r requirements-dev.txt
  pytest tests/ -v
  ```
  Expected: all tests pass (3 schema + 5 manifest + 9 check_deps + 1 install_deps = 18).

Phase 0 produces no extraction logic — that is Phase 1's plan. The deliverable is a recognizable skill skeleton with a validated manifest schema and an honest dependency checker.

---

## Self-Review Notes

**Spec coverage (Phase 0 scope only):**
- §4 directory structure → Task 1 (scaffold) + Tasks 2–5 (files).
- §5.2 dependency tiering → Task 4 (`check_deps.py` encodes the table) + Task 5 (`install_deps.sh`).
- §8 manifest schema → Task 2 (schema) + Task 3 (dataclasses/validate).
- §15.2 `allowed-tools` minimal three → Task 1 Step 3/6.
- §11 Phase 0 deliverables (SKILL.md, VERSION, check_deps.py, install_deps.sh, manifest.py + schema) → all covered.
- Phase 0 does NOT cover: extraction, cropping, detect, render, contact sheet, packaging — those are Phase 1+ plans.

**Placeholder scan:** none — every code step contains complete code, every command has expected output.

**Type consistency:** `Manifest.add_warning(code, page, detail)` matches `WarningEntry(code, page, detail)`; `Figure`/`EmbeddedImage`/`Candidate` field names match `manifest.schema.json` properties exactly; `validate()` signature `(manifest_dict, schema_path=SCHEMA_PATH) -> list[str]` is consistent across Task 3 tests and the interface block.
