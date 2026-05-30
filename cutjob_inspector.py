#!/usr/bin/env python3
"""Inspect Graphtec .cutjob command-list files.

The files Graphtec writes here are plain text cut commands. They no longer
contain editable text labels, but the outline coordinates can be measured and
rendered for layout calibration.
"""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path


POINT_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)")
MM_PER_INCH = 25.4


def path_commands(cutjob_path: Path) -> tuple[str, list[list[tuple[float, float]]]]:
    svg_parts: list[str] = []
    subpaths: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []

    def start_path(points: list[tuple[float, float]]) -> None:
        nonlocal current
        if current:
            subpaths.append(current)
        current = list(points)

    for line in cutjob_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        command = line.strip()
        points = [(float(x), float(y)) for x, y in POINT_RE.findall(command)]
        if not points:
            continue

        if command.startswith("move "):
            start_path(points[:1])
            svg_parts.append(f"M {points[0][0]:.3f} {points[0][1]:.3f}")
        elif command.startswith("draw "):
            current.extend(points[:1])
            svg_parts.append(f"L {points[0][0]:.3f} {points[0][1]:.3f}")
        elif command.startswith("bezier moveto"):
            start_path(points[:1])
            svg_parts.append(f"M {points[0][0]:.3f} {points[0][1]:.3f}")
        elif command.startswith("bezier drawto") and len(points) >= 3:
            current.extend(points[-3:])
            svg_parts.append(
                "C " + " ".join(f"{x:.3f} {y:.3f}" for x, y in points[-3:])
            )

    if current:
        subpaths.append(current)

    return " ".join(svg_parts), subpaths


def bounding_box(points: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), min(ys), max(xs), max(ys)


def box_size(box: tuple[float, float, float, float]) -> tuple[float, float]:
    x1, y1, x2, y2 = box
    return x2 - x1, y2 - y1


def merge_clusters(
    boxes: list[tuple[float, float, float, float]],
    *,
    gap_x: float,
    gap_y: float,
) -> list[tuple[float, float, float, float, int]]:
    clusters: list[list[tuple[float, float, float, float]]] = [[box] for box in boxes]
    changed = True

    while changed:
        changed = False
        merged: list[list[tuple[float, float, float, float]]] = []
        used = [False] * len(clusters)

        for index, cluster in enumerate(clusters):
            if used[index]:
                continue
            used[index] = True
            group = list(cluster)
            x1 = min(box[0] for box in group)
            y1 = min(box[1] for box in group)
            x2 = max(box[2] for box in group)
            y2 = max(box[3] for box in group)

            expanded = True
            while expanded:
                expanded = False
                for other_index, other in enumerate(clusters):
                    if used[other_index]:
                        continue
                    ox1 = min(box[0] for box in other)
                    oy1 = min(box[1] for box in other)
                    ox2 = max(box[2] for box in other)
                    oy2 = max(box[3] for box in other)
                    separated = (
                        ox1 > x2 + gap_x
                        or ox2 < x1 - gap_x
                        or oy1 > y2 + gap_y
                        or oy2 < y1 - gap_y
                    )
                    if separated:
                        continue
                    group.extend(other)
                    used[other_index] = True
                    changed = True
                    expanded = True
                    x1 = min(x1, ox1)
                    y1 = min(y1, oy1)
                    x2 = max(x2, ox2)
                    y2 = max(y2, oy2)

            merged.append(group)
        clusters = merged

    measured = []
    for cluster in clusters:
        x1 = min(box[0] for box in cluster)
        y1 = min(box[1] for box in cluster)
        x2 = max(box[2] for box in cluster)
        y2 = max(box[3] for box in cluster)
        measured.append((x1, y1, x2, y2, len(cluster)))
    return sorted(measured, key=lambda box: (box[1], box[0]))


def write_preview(path_data: str, output_path: Path) -> None:
    output_path.write_text(
        f"""<svg xmlns="http://www.w3.org/2000/svg" width="8.5in" height="12in" viewBox="-5 -5 225 315">
<rect x="0" y="0" width="215.9" height="304.8" fill="white" stroke="#cccccc"/>
<path d="{path_data}" fill="none" stroke="#ff5a5f" stroke-width="0.35"/>
</svg>
""",
        encoding="utf-8",
    )


def write_measurements(
    clusters: list[tuple[float, float, float, float, int]], output_path: Path
) -> None:
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "cluster",
                "x_mm",
                "y_mm",
                "width_mm",
                "height_mm",
                "width_in",
                "height_in",
                "subpaths",
            ]
        )
        for index, (x1, y1, x2, y2, count) in enumerate(clusters, start=1):
            width, height = box_size((x1, y1, x2, y2))
            writer.writerow(
                [
                    index,
                    f"{x1:.3f}",
                    f"{y1:.3f}",
                    f"{width:.3f}",
                    f"{height:.3f}",
                    f"{width / MM_PER_INCH:.3f}",
                    f"{height / MM_PER_INCH:.3f}",
                    count,
                ]
            )


def inspect(cutjob_path: Path, output_dir: Path, gap_x: float, gap_y: float) -> None:
    path_data, subpaths = path_commands(cutjob_path)
    boxes = []
    for subpath in subpaths:
        box = bounding_box(subpath)
        width, height = box_size(box)
        if width >= 0.2 and height >= 0.2:
            boxes.append(box)

    clusters = merge_clusters(boxes, gap_x=gap_x, gap_y=gap_y)
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = cutjob_path.stem.replace(" ", "_")
    write_preview(path_data, output_dir / f"{stem}_preview.svg")
    write_measurements(clusters, output_dir / f"{stem}_measurements.csv")

    print(f"{cutjob_path.name}: {len(boxes)} subpaths, {len(clusters)} measured clusters")
    for index, (x1, y1, x2, y2, count) in enumerate(clusters, start=1):
        width, height = box_size((x1, y1, x2, y2))
        print(
            f"{index:02d} x={x1:7.2f} y={y1:7.2f} "
            f"w={width:7.2f}mm h={height:7.2f}mm "
            f"({width / MM_PER_INCH:.2f}in x {height / MM_PER_INCH:.2f}in) "
            f"subpaths={count}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect Graphtec .cutjob geometry.")
    parser.add_argument("cutjob", nargs="+", type=Path)
    parser.add_argument("-o", "--output", type=Path, default=Path("cutjob_inspection"))
    parser.add_argument("--gap-x", type=float, default=3.5)
    parser.add_argument("--gap-y", type=float, default=2.5)
    args = parser.parse_args()

    for cutjob_path in args.cutjob:
        inspect(cutjob_path.expanduser().resolve(), args.output, args.gap_x, args.gap_y)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
