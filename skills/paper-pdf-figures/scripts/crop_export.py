"""Crop figure regions from a PDF by bbox (Phase 2: --mode manual).

Uses page.show_pdf_page(clip=bbox) to embed the cropped region as a Form
XObject in a fresh 1-page PDF, preserving vector content and text. Renders a
PNG preview from that page at the requested DPI.
"""
from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path

import fitz
import yaml

from manifest import Figure

DEFAULT_FORMATS = ["pdf", "png"]


@dataclass
class FigureConfig:
    id: str
    page: int
    bbox: list[float]
    caption: str = ""
    export: list[str] | None = None


def parse_config(path: str | Path) -> list[FigureConfig]:
    data = yaml.safe_load(Path(path).read_text())
    figures = []
    for f in data.get("figures", []):
        bbox = [float(x) for x in f["bbox"]]
        if len(bbox) != 4:
            raise ValueError(f"figure {f.get('id')} bbox must have 4 values, got {len(bbox)}")
        page = int(f["page"])
        if page < 1:
            raise ValueError(f"figure {f.get('id')} page must be >= 1, got {page}")
        figures.append(FigureConfig(
            id=str(f["id"]),
            page=page,
            bbox=bbox,
            caption=str(f.get("caption", "")),
            export=list(f["export"]) if f.get("export") else None,
        ))
    return figures


def crop_figures(
    doc: "fitz.Document",
    figures: list[FigureConfig],
    out_dir: Path | str,
    paper_slug: str,
    dpi: int = 300,
    formats: list[str] | None = None,
    dry_run: bool = False,
    warnings: list | None = None,
    output_subdir: str = "figures",
) -> list[Figure]:
    """Crop each figure's bbox region into a vector PDF + PNG preview.

    Returns one Figure per FigureConfig (in order). Duplicate ids raise ValueError.
    `output_subdir` selects the on-disk subdirectory under `<out_dir>/<paper_slug>/`
    (default "figures"); the Figure.files paths are written relative to the
    paper directory (e.g. "tables/<id>/<id>.pdf") so the manifest stays portable.
    """
    if formats is None:
        formats = list(DEFAULT_FORMATS)
    out_dir = Path(out_dir)
    figs_dir = out_dir / paper_slug / output_subdir
    if not dry_run:
        figs_dir.mkdir(parents=True, exist_ok=True)

    seen_ids: set[str] = set()
    results: list[Figure] = []

    for fig in figures:
        if fig.id in seen_ids:
            raise ValueError(f"duplicate figure id: {fig.id}")
        seen_ids.add(fig.id)

        if fig.page < 1 or fig.page > len(doc):
            raise ValueError(f"figure {fig.id} page {fig.page} out of range (1..{len(doc)})")

        clip = fitz.Rect(*fig.bbox)
        fig_dir = figs_dir / fig.id if not dry_run else None
        try:
            pdf_doc = fitz.open()
            try:
                p = pdf_doc.new_page(width=clip.width, height=clip.height)
                p.show_pdf_page(p.rect, doc, fig.page - 1, clip=clip)
                pdf_bytes = pdf_doc.tobytes()
                png_bytes = p.get_pixmap(dpi=dpi).tobytes("png")
            finally:
                pdf_doc.close()
        except Exception as e:
            if warnings is not None:
                warnings.append(("WARN_CROP_FAILED", fig.page, f"{fig.id}: {e}"))
            if fig_dir is not None and fig_dir.exists():
                shutil.rmtree(fig_dir)
            continue

        files = {"pdf": None, "png": None, "svg": None}
        sha: dict[str, str] = {}
        fig_formats = fig.export if fig.export is not None else formats
        if not dry_run:
            fig_dir.mkdir(parents=True, exist_ok=True)
            if "pdf" in fig_formats:
                (fig_dir / f"{fig.id}.pdf").write_bytes(pdf_bytes)
                files["pdf"] = f"{output_subdir}/{fig.id}/{fig.id}.pdf"
                sha["pdf"] = hashlib.sha256(pdf_bytes).hexdigest()
            if "png" in fig_formats:
                (fig_dir / f"{fig.id}.png").write_bytes(png_bytes)
                files["png"] = f"{output_subdir}/{fig.id}/{fig.id}.png"
                sha["png"] = hashlib.sha256(png_bytes).hexdigest()

        results.append(Figure(
            id=fig.id,
            page=fig.page,
            bbox_pdf_points=list(fig.bbox),
            type="page-crop",
            extraction_method="manual-bbox",
            dpi=dpi,
            files=files,
            sha256=sha,
            caption=fig.caption,
        ))
    return results
