"""Heuristic candidate figure detection (Phase 4: --mode detect, dry-run).

Renders each page at low DPI, binarizes (content=255), closes with a
DPI-scaled kernel to merge a figure's scattered content into blobs, finds
connected components, filters by area/aspect/margins, and merges nearby
candidates. Returns Candidate records with PDF-point bboxes. Does NOT crop.
"""
from __future__ import annotations

import cv2
import fitz
import numpy as np

from manifest import Candidate


def detect_candidates(
    page_num: int,
    page: "fitz.Page",
    dpi: int = 100,
    min_area_ratio: float = 0.03,
    max_area_ratio: float = 0.85,
    merge_distance: float = 20.0,
    exclude_margins: float = 30.0,
) -> list[Candidate]:
    """Return candidate figure regions on `page` as Candidate records.

    `merge_distance` and `exclude_margins` are in PDF points. `score` is the
    area ratio (component pixels / page pixels), in (0, 1].
    """
    pix = page.get_pixmap(dpi=dpi)
    n_channels = pix.n
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, n_channels)
    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY) if n_channels >= 3 else np.array(img)

    # blank out margins (exclude header/footer/edge noise)
    margin_px = int(exclude_margins * dpi / 72.0)
    if margin_px > 0:
        gray[:margin_px, :] = 255
        gray[-margin_px:, :] = 255
        gray[:, :margin_px] = 255
        gray[:, -margin_px:] = 255

    # binarize: content (dark) -> 255
    binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]

    # close with a DPI-scaled kernel to merge a figure's content into blobs
    k = max(1, int(dpi * 0.15))
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (k, k))
    closed = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)

    num, _labels, stats, _centroids = cv2.connectedComponentsWithStats(closed, connectivity=8)
    page_area = pix.width * pix.height
    scale = 72.0 / dpi  # pixel -> PDF point

    hits: list[Candidate] = []
    for i in range(1, num):  # 0 = background
        x, y, w, h, area = stats[i]
        if w <= 0 or h <= 0:
            continue
        ratio = area / page_area
        if ratio < min_area_ratio or ratio > max_area_ratio:
            continue
        aspect = w / h
        if aspect > 10 or aspect < 0.1:  # skip very thin (text lines)
            continue
        bbox_pdf = [x * scale, y * scale, (x + w) * scale, (y + h) * scale]
        hits.append(Candidate(page=page_num, bbox_pdf_points=bbox_pdf, score=float(ratio)))

    return _merge_nearby(hits, merge_distance)


def _rects_within(a: "fitz.Rect", b: "fitz.Rect", dist: float) -> bool:
    """True if the gap between a and b is < dist in BOTH axes."""
    gap_x = max(0.0, max(a.x0, b.x0) - min(a.x1, b.x1))
    gap_y = max(0.0, max(a.y0, b.y0) - min(a.y1, b.y1))
    return gap_x < dist and gap_y < dist


def _merge_nearby(hits: list[Candidate], merge_dist: float) -> list[Candidate]:
    """Iteratively merge candidates whose rects are within merge_dist (PDF points)."""
    if len(hits) <= 1:
        return list(hits)
    changed = True
    result = list(hits)
    while changed:
        changed = False
        merged: list[Candidate] = []
        used = [False] * len(result)
        for i, h in enumerate(result):
            if used[i]:
                continue
            ri = fitz.Rect(*h.bbox_pdf_points)
            score = h.score
            for j in range(i + 1, len(result)):
                if used[j]:
                    continue
                rj = fitz.Rect(*result[j].bbox_pdf_points)
                if _rects_within(ri, rj, merge_dist):
                    ri = fitz.Rect(min(ri.x0, rj.x0), min(ri.y0, rj.y0),
                                   max(ri.x1, rj.x1), max(ri.y1, rj.y1))
                    score = max(score, result[j].score)
                    used[j] = True
                    changed = True
            used[i] = True
            merged.append(Candidate(
                page=h.page,
                bbox_pdf_points=[ri.x0, ri.y0, ri.x1, ri.y1],
                score=score,
            ))
        result = merged
    return result


def draw_candidates_preview(page: "fitz.Page", hits: list[Candidate], dpi: int = 100) -> bytes:
    """Render `page` with red rectangles around each candidate; return PNG bytes."""
    pix = page.get_pixmap(dpi=dpi)
    n_channels = pix.n
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, n_channels)
    # cv2 uses BGR
    if n_channels == 1:
        bgr = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    elif n_channels == 4:
        bgr = cv2.cvtColor(img, cv2.COLOR_RGBA2BGR)
    else:
        bgr = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
    scale = dpi / 72.0  # PDF point -> pixel
    for h in hits:
        x0, y0, x1, y1 = h.bbox_pdf_points
        cv2.rectangle(bgr, (int(x0 * scale), int(y0 * scale)),
                       (int(x1 * scale), int(y1 * scale)), (0, 0, 255), 2)
    ok, buf = cv2.imencode(".png", bgr)
    if not ok:
        raise RuntimeError("failed to encode preview PNG")
    return buf.tobytes()
