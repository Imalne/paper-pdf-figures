#!/usr/bin/env python3
"""CLI dispatcher for paper-pdf-figures.

Phase 1: --mode embedded.  Phase 2: --mode manual.  Phase 4: --mode detect.
Phase 5: --mode auto (model-detection auto-crop).  Phase 5.3: --mode render
(whole-page / bbox-region render to PNG + contact sheet).
All user-input failures produce a clean ERROR: line and exit 1; recoverable
per-item failures become manifest warnings.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import fitz
import yaml

from crop_export import FigureConfig, crop_figures, parse_config
from extract_embedded import extract_embedded_images
from figure_detect import detect_candidates, draw_candidates_preview
from manifest import Candidate, Manifest, validate
import postprocess

VERSION_FILE = Path(__file__).resolve().parent.parent / "VERSION"
DEFAULT_FORMATS = ["pdf", "png"]
KNOWN_FORMATS = {"pdf", "png"}  # svg is Phase 3
DETECT_DPI = 100
AUTO_DETECT_DPI = 150


def read_version() -> str:
    try:
        return VERSION_FILE.read_text().strip()
    except OSError:
        return "0.0.0"


def parse_pages(spec: str | None) -> set[int] | None:
    if not spec:
        return None
    pages: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            if "-" in part:
                lo_s, hi_s = part.split("-", 1)
                lo, hi = int(lo_s), int(hi_s)
            else:
                lo = hi = int(part)
        except ValueError:
            raise ValueError(f"invalid page spec '{part}'")
        if lo < 1 or hi < 1:
            raise ValueError(f"page numbers must be >= 1, got '{part}'")
        if lo > hi:
            raise ValueError(f"invalid page range '{part}' (start > end)")
        pages.update(range(lo, hi + 1))
    return pages or None


def parse_formats(spec: str | None) -> list[str]:
    if not spec:
        return list(DEFAULT_FORMATS)
    return [f.strip() for f in spec.split(",") if f.strip()]


def _sanitize_slug(s: str) -> str:
    return "".join(c if (c.isalnum() or c in "-_") else "_" for c in s)


def paper_slug_from_pdf(pdf_path: Path) -> str:
    return _sanitize_slug(pdf_path.stem)


def _resolve_device(arg: str) -> str:
    if arg == "auto":
        try:
            import torch
            return "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            return "cpu"
    return arg


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="extract_pdf_figures")
    parser.add_argument("pdf_path")
    parser.add_argument("--mode", default="embedded",
                        choices=["embedded", "manual", "detect", "render", "auto"])
    parser.add_argument("--out", required=True)
    parser.add_argument("--paper-slug", default=None)
    parser.add_argument("--pages", default=None)
    parser.add_argument("--config", default=None)
    parser.add_argument("--dpi", type=int, default=300)
    parser.add_argument("--formats", default=None)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    # detect params
    parser.add_argument("--min-area-ratio", type=float, default=0.03)
    parser.add_argument("--max-area-ratio", type=float, default=0.85)
    parser.add_argument("--merge-distance", type=float, default=20.0)
    parser.add_argument("--exclude-margins", type=float, default=30.0)
    parser.add_argument("--two-column", default="auto", choices=["auto", "true", "false"])
    # auto params (Phase 5)
    parser.add_argument("--weights-dir", default=None)
    parser.add_argument("--device", default="auto", choices=["auto", "cpu", "cuda"])
    parser.add_argument("--min-confidence", type=float, default=0.3)
    parser.add_argument("--labels", default="figure,table",
                        help="primary layout labels to crop (default figure,table); "
                             "captions auto-inferred as {primary}_caption; "
                             "caption labels (figure_caption/table_caption) are ignored")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--caption-driven-fallback", action="store_true",
                        help="when a table_caption has no paired table body, "
                             "infer the body from adjacent text blocks and crop it "
                             "(rescues tables the model missed); default off")
    args = parser.parse_args(argv)

    # Note: argparse `choices` already restricts --mode to the 5 implemented modes;
    # an invalid mode exits 2 before reaching here.
    if args.mode == "manual" and not args.config:
        print("ERROR: --mode manual requires --config CONFIG.yaml", file=sys.stderr)
        return 1
    if args.dpi < 1:
        print(f"ERROR: --dpi must be >= 1, got {args.dpi}", file=sys.stderr)
        return 1
    if args.mode == "detect":
        if not (0 < args.min_area_ratio < 1) or not (0 < args.max_area_ratio <= 1):
            print("ERROR: --min-area-ratio and --max-area-ratio must be in (0, 1]",
                  file=sys.stderr)
            return 1
        if args.min_area_ratio > args.max_area_ratio:
            print(f"ERROR: --min-area-ratio ({args.min_area_ratio}) must be <= "
                  f"--max-area-ratio ({args.max_area_ratio})", file=sys.stderr)
            return 1
    if args.mode == "auto":
        try:
            import torch  # noqa: F401
            import huggingface_hub  # noqa: F401
            import doclayout_yolo  # noqa: F401
        except ImportError:
            print("ERROR: --mode auto requires ML backend; "
                  "pip install -r requirements-ml.txt", file=sys.stderr)
            return 1
        if not (0 <= args.min_confidence <= 1):
            print(f"ERROR: --min-confidence must be in [0, 1], got {args.min_confidence}",
                  file=sys.stderr)
            return 1

    # parse --pages early so malformed input is a clean error
    try:
        pages_set = parse_pages(args.pages)
    except ValueError as e:
        print(f"ERROR: invalid --pages spec '{args.pages}': {e}", file=sys.stderr)
        return 1

    pdf_path = Path(args.pdf_path)
    out_dir = Path(args.out)
    slug = _sanitize_slug(args.paper_slug) if args.paper_slug else paper_slug_from_pdf(pdf_path)
    paper_dir = out_dir / slug
    manifest_path = paper_dir / "manifest.json"

    if not args.dry_run and manifest_path.exists() and not args.overwrite:
        print(f"ERROR: {manifest_path} already exists; use --overwrite to replace",
              file=sys.stderr)
        return 1

    formats = parse_formats(args.formats)
    warnings: list[tuple[str, int | None, str | None]] = []
    if args.mode in ("manual", "detect", "auto"):
        for f in formats:
            if f not in KNOWN_FORMATS:
                warnings.append(("WARN_UNKNOWN_FORMAT", None, f"format '{f}' not supported, skipped"))

    try:
        doc = fitz.open(str(pdf_path))
    except (OSError, RuntimeError) as e:
        print(f"ERROR: cannot open PDF '{pdf_path}': {e}", file=sys.stderr)
        return 1

    # --overwrite: clear existing output only AFTER the PDF opens successfully,
    # so a bad/missing PDF cannot delete the user's prior output.
    if not args.dry_run and args.overwrite and paper_dir.exists():
        shutil.rmtree(paper_dir)

    if pages_set:
        for p in pages_set:
            if p < 1 or p > len(doc):
                warnings.append(("WARN_PAGE_OUT_OF_RANGE", p,
                                 f"page {p} out of range (1..{len(doc)}), skipped"))

    # mode outputs
    records: list = []           # embedded images OR figures OR candidates
    all_candidates: list = []    # auto: LayoutRegion-ish dicts for manifest
    all_table_configs: list = []  # auto: (FigureConfig, caption_source) tuples for tables
    table_records: list = []     # auto: cropped Figure records for tables
    algorithm_records: list = []  # auto: cropped Figure records for algorithms
    rendered: list = []          # render: RenderedItem records
    pages_with_hits = 0

    try:
        if args.mode == "embedded":
            records = extract_embedded_images(
                doc, out_dir, slug, pages=pages_set, dry_run=args.dry_run, warnings=warnings,
            )
        elif args.mode == "manual":
            try:
                figures = parse_config(args.config)
                records = crop_figures(
                    doc, figures, out_dir, slug,
                    dpi=args.dpi, formats=formats, dry_run=args.dry_run, warnings=warnings,
                )
            except (OSError, yaml.YAMLError, ValueError, KeyError) as e:
                print(f"ERROR: {e}", file=sys.stderr)
                return 1
        elif args.mode == "detect":
            indices = (sorted(p - 1 for p in pages_set) if pages_set is not None
                       else list(range(len(doc))))
            candidates_dir = paper_dir / "candidates"
            if not args.dry_run:
                candidates_dir.mkdir(parents=True, exist_ok=True)
            for pno in indices:
                if pno < 0 or pno >= len(doc):
                    continue
                hits = detect_candidates(
                    pno + 1, doc[pno], dpi=DETECT_DPI,
                    min_area_ratio=args.min_area_ratio,
                    max_area_ratio=args.max_area_ratio,
                    merge_distance=args.merge_distance,
                    exclude_margins=args.exclude_margins,
                )
                if hits:
                    pages_with_hits += 1
                records.extend(hits)
                if not args.dry_run:
                    png = draw_candidates_preview(doc[pno], hits, dpi=DETECT_DPI)
                    (candidates_dir / f"page_{pno + 1:04d}_candidates.png").write_bytes(png)
            if not args.dry_run:
                (candidates_dir / "candidates.json").write_text(
                    json.dumps({"candidates": [
                        {"page": c.page, "bbox_pdf_points": c.bbox_pdf_points,
                         "score": c.score}
                        for c in records
                    ]}, indent=2, ensure_ascii=False)
                )
        elif args.mode == "render":
            from render_pages import (
                render_pages as _render_pages,
                render_regions,
                make_contact_sheet,
            )
            if args.config:
                try:
                    figures = parse_config(args.config)
                except (OSError, yaml.YAMLError, ValueError, KeyError) as e:
                    print(f"ERROR: {e}", file=sys.stderr)
                    return 1
                rendered = render_regions(
                    doc, figures, out_dir, slug,
                    dpi=args.dpi, dry_run=args.dry_run,
                )
            else:
                rendered = _render_pages(
                    doc, pages_set, out_dir, slug,
                    dpi=args.dpi, dry_run=args.dry_run,
                )
            if not args.dry_run:
                make_contact_sheet(rendered, out_dir, slug)
        else:  # auto
            import model_detect
            labels = [s.strip() for s in args.labels.split(",") if s.strip()]
            weights_dir = model_detect.resolve_weights_dir(args.weights_dir)
            # Use module attribute (not `from ... import`) so tests can monkeypatch.
            detector = model_detect.DocLayoutYoloDetector()
            detector.load(weights_dir, _resolve_device(args.device))
            indices = (sorted(p - 1 for p in pages_set) if pages_set is not None
                       else list(range(len(doc))))
            all_figure_configs = []
            for pno in indices:
                if pno < 0 or pno >= len(doc):
                    continue
                regions = detector.detect(doc[pno], dpi=AUTO_DETECT_DPI)
                if not regions:
                    continue
                pages_with_hits += 1
                for r in regions:
                    all_candidates.append({
                        "page": pno + 1, "bbox_pdf_points": r.bbox_pdf_points,
                        "label": r.label, "confidence": r.confidence,
                    })
                # Build (primary, inferred-caption) groups. Skip labels that
                # are themselves captions (e.g. figure_caption passed via the
                # old --labels style) - they have no caption of their own and
                # would collide with their primary's id prefix.
                CAPTION_LABELS = {"figure_caption", "table_caption", "formula_caption",
                                  "table_footnote"}
                group_specs = [(p, f"{p}_caption")
                               for p in labels if p not in CAPTION_LABELS]
                groups = model_detect.pair_and_merge_multi(
                    regions, group_specs=group_specs, min_confidence=args.min_confidence)
                # Phase 5.3: caption-driven fallback. When --caption-driven-fallback
                # is set, collect orphan table_caption regions (those NOT paired with
                # any table primary by pair_and_merge_multi), infer a table body from
                # adjacent text blocks, and append synthetic table regions to the
                # table group. Synthetic regions are tagged caption_source=
                # "caption-driven" (tracked by object identity) so they bypass the
                # model/text-rescan/none caption_source logic below. Default OFF.
                synthetic_ids: set[int] = set()
                if args.caption_driven_fallback and "table" in labels:
                    paired_caps: set[int] = set()
                    for _primary, _pairs in groups.items():
                        if _primary == "table":
                            for _merged, paired_cap in _pairs:
                                if paired_cap is not None:
                                    paired_caps.add(id(paired_cap))
                    orphan_caps = [r for r in regions
                                   if r.label == "table_caption"
                                   and r.confidence >= args.min_confidence
                                   and id(r) not in paired_caps]
                    if orphan_caps:
                        synthetic = postprocess.caption_driven_fallback(
                            orphan_caps, regions, doc[pno])
                        for syn in synthetic:
                            synthetic_ids.add(id(syn))
                            groups.setdefault("table", []).append((syn, None))
                for primary, pairs in groups.items():
                    if primary == "table":
                        # caption rescan for tables that didn't pair via model.
                        # paired_cap is not None -> caption_source "model".
                        # paired_cap is None -> rescan plain text/title regions
                        # for a "Table N:" caption; found -> "text-rescan",
                        # not found -> "none".
                        # Synthetic fallback regions (tracked in synthetic_ids)
                        # are tagged "caption-driven" and skip the rescan.
                        rescan_pairs = []
                        for merged, paired_cap in pairs:
                            if id(merged) in synthetic_ids:
                                rescan_pairs.append((merged, "caption-driven"))
                            elif paired_cap is not None:
                                rescan_pairs.append((merged, "model"))
                            else:
                                def text_of(region):
                                    page_clip = fitz.Rect(*region.bbox_pdf_points)
                                    return doc[pno].get_textbox(page_clip)
                                rescanned, source = postprocess.rescan_table_caption(
                                    merged, regions, pno + 1, text_of=text_of)
                                rescan_pairs.append((rescanned, source))
                        for idx, (merged, source) in enumerate(rescan_pairs, start=1):
                            fig_id = f"tbl_p{pno + 1:04d}_{idx:02d}"
                            all_table_configs.append((
                                FigureConfig(id=fig_id, page=pno + 1,
                                             bbox=list(merged.bbox_pdf_points)),
                                source,
                            ))
                    else:
                        # Derive a unique id prefix per group so two non-table
                        # primaries (e.g. figure + figure_caption) can't collide.
                        # figure -> "fig"; anything else -> sanitized.
                        id_prefix = ("fig" if primary == "figure"
                                     else "".join(c if c.isalnum() else "_"
                                                  for c in primary)[:8] or "reg")
                        configs = model_detect.regions_to_figure_configs(
                            pairs, page=pno + 1, id_prefix=id_prefix)
                        all_figure_configs.extend(configs)
                if not args.dry_run:
                    cands_dir = paper_dir / "candidates"
                    cands_dir.mkdir(parents=True, exist_ok=True)
                    cands = [Candidate(page=pno + 1, bbox_pdf_points=r.bbox_pdf_points,
                                      score=r.confidence) for r in regions]
                    png = draw_candidates_preview(doc[pno], cands, dpi=DETECT_DPI)
                    (cands_dir / f"page_{pno + 1:04d}_candidates.png").write_bytes(png)
            if not args.dry_run and all_candidates:
                cands_dir = paper_dir / "candidates"
                cands_dir.mkdir(parents=True, exist_ok=True)
                (cands_dir / "candidates.json").write_text(
                    json.dumps({"candidates": all_candidates}, indent=2, ensure_ascii=False)
                )
            if not args.dry_run:
                records = crop_figures(doc, all_figure_configs, out_dir, slug,
                                       dpi=args.dpi, formats=formats, warnings=warnings)
                # tables: crop to tables/ first, then classify each crop's text
                # into table vs algorithm; move algorithm crops to algorithms/.
                table_configs_only = [c for c, _ in all_table_configs]
                table_records_raw = crop_figures(doc, table_configs_only, out_dir, slug,
                                                 dpi=args.dpi, formats=formats,
                                                 warnings=warnings, output_subdir="tables")
                # match configs to crop records by id (crop_figures may skip
                # failed crops, so the lists can differ in length)
                rec_by_id = {rec.id: rec for rec in table_records_raw}
                final_table_records = []
                algorithm_records = []
                for cfg, source in all_table_configs:
                    rec = rec_by_id.get(cfg.id)
                    if rec is None:
                        continue  # crop failed (WARN_CROP_FAILED already recorded)
                    pdf_rel = rec.files.get("pdf")
                    if pdf_rel:
                        cdoc = fitz.open(str(out_dir / slug / pdf_rel))
                        try:
                            text = cdoc[0].get_text()
                        finally:
                            cdoc.close()
                        kind = postprocess.classify_table_or_algorithm(text)
                    else:
                        kind = "table"  # no pdf text to classify; assume table
                    if kind == "algorithm":
                        # move tables/{id}/ -> algorithms/{alg_id}/, rename files
                        new_id = cfg.id.replace("tbl_", "alg_", 1)
                        old_dir = out_dir / slug / "tables" / cfg.id
                        new_dir = out_dir / slug / "algorithms" / new_id
                        new_dir.parent.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(old_dir), str(new_dir))
                        for f in new_dir.iterdir():
                            if f.name.startswith("tbl_"):
                                f.rename(new_dir / f.name.replace("tbl_", "alg_", 1))
                        rec.id = new_id
                        rec.type = "page-crop-algorithm"
                        rec.files = {
                            k: (v.replace("tables/", "algorithms/").replace("tbl_", "alg_")
                                if v else v)
                            for k, v in rec.files.items()
                        }
                        rec.caption_source = source
                        algorithm_records.append(rec)
                    else:
                        rec.type = "page-crop-table"
                        rec.caption_source = source
                        final_table_records.append(rec)
                table_records = final_table_records
            else:
                records = []
                table_records = []
                algorithm_records = []
    finally:
        doc.close()

    m = Manifest(
        source_pdf=str(pdf_path),
        paper_slug=slug,
        tool_version=read_version(),
        run_args={
            "mode": args.mode, "pages": args.pages, "config": args.config,
            "dpi": args.dpi, "formats": args.formats, "dry_run": args.dry_run,
            "min_area_ratio": args.min_area_ratio, "max_area_ratio": args.max_area_ratio,
            "merge_distance": args.merge_distance, "exclude_margins": args.exclude_margins,
            "two_column": args.two_column,
            "caption_driven_fallback": args.caption_driven_fallback,
            "min_confidence": args.min_confidence, "labels": args.labels,
            "device": args.device,
        },
    )
    if args.mode == "embedded":
        for rec in records:
            m.add_embedded_image(rec)
        if not records:
            m.add_warning("WARN_NO_EMBEDDED_IMAGES")
    elif args.mode in ("manual", "auto"):
        for rec in records:
            m.add_figure(rec)
        if not records and not args.dry_run:
            m.add_warning("WARN_NO_FIGURES")
        if args.mode == "auto":
            for rec in table_records:
                m.add_table(rec)
            for rec in algorithm_records:
                m.add_algorithm(rec)
            if not table_records and not args.dry_run:
                m.add_warning("WARN_NO_TABLES")
    elif args.mode == "render":
        for rec in rendered:
            m.add_rendered(rec)
        if not rendered and not args.dry_run:
            m.add_warning("WARN_NO_RENDERED")
    else:  # detect
        for rec in records:
            m.add_candidate(rec)
        if not records:
            m.add_warning("WARN_NO_FIGURE_CANDIDATES")

    # auto: also record candidates (with label/confidence) in manifest
    if args.mode == "auto" and all_candidates:
        for c in all_candidates:
            m.add_candidate(Candidate(
                page=c["page"], bbox_pdf_points=c["bbox_pdf_points"],
                score=c["confidence"], label=c["label"], confidence=c["confidence"],
            ))

    for code, page, detail in warnings:
        m.add_warning(code, page, detail)

    if not args.dry_run:
        errs = validate(m.to_dict())
        if errs:
            print("ERROR: manifest failed schema validation:", file=sys.stderr)
            for e in errs:
                print(f"  {e}", file=sys.stderr)
            return 1
        m.save(manifest_path)

    print(f"source_pdf: {pdf_path}")
    print(f"paper_slug: {slug}")
    if args.mode == "embedded":
        print(f"embedded_images: {len(records)}")
    elif args.mode in ("manual", "auto"):
        print(f"figures: {len(records)}")
        if args.mode == "auto":
            print(f"tables: {len(table_records)}")
            print(f"algorithms: {len(algorithm_records)}")
            print(f"candidates: {len(all_candidates)} across {pages_with_hits} pages")
    elif args.mode == "render":
        print(f"rendered: {len(rendered)}")
    else:  # detect
        print(f"candidates: {len(records)} across {pages_with_hits} pages")
    if not args.dry_run:
        print(f"manifest: {manifest_path}")
    print(f"warnings: {[w.code for w in m.warnings]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
