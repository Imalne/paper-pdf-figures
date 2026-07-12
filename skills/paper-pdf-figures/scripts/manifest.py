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
    caption_source: str | None = None


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
    label: str | None = None
    confidence: float | None = None


@dataclass
class WarningEntry:
    code: str
    page: int | None = None
    detail: str | None = None


@dataclass
class RenderedItem:
    id: str
    page: int
    file: str
    dpi: int
    width: int
    height: int


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
    tables: list[Figure] = field(default_factory=list)
    algorithms: list[Figure] = field(default_factory=list)
    rendered: list[RenderedItem] = field(default_factory=list)

    def add_figure(self, fig: Figure) -> None:
        self.figures.append(fig)

    def add_embedded_image(self, img: EmbeddedImage) -> None:
        self.embedded_images.append(img)

    def add_candidate(self, cand: Candidate) -> None:
        self.candidates.append(cand)

    def add_warning(self, code: str, page: int | None = None, detail: str | None = None) -> None:
        self.warnings.append(WarningEntry(code=code, page=page, detail=detail))

    def add_table(self, t: Figure) -> None:
        self.tables.append(t)

    def add_algorithm(self, t: Figure) -> None:
        self.algorithms.append(t)

    def add_rendered(self, r: RenderedItem) -> None:
        self.rendered.append(r)

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
            tables=[Figure(**t) for t in d.get("tables", [])],
            algorithms=[Figure(**a) for a in d.get("algorithms", [])],
            rendered=[RenderedItem(**r) for r in d.get("rendered", [])],
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
