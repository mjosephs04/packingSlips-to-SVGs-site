#!/usr/bin/env python3
"""
Parse Custom Sports Sleeves packing slip PDFs and generate per-color SVG cut files.

This intentionally generates editable SVG text rather than Graphtec .gstudio files.
Graphtec's project format is proprietary binary data, while SVG gives us a reliable
handoff format that Graphtec software can import and convert to outlines/cut paths.
"""

from __future__ import annotations

import argparse
import csv
import html
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable
from xml.sax.saxutils import escape as xml_escape


ITEM_RE = re.compile(
    r"^\s*(?P<product>.+?)\s+\$[\d,.]+\s+(?P<qty>\d+)\s+(?:\(?\$[\d,.]+\)?|-?\$[\d,.]+)"
)

COLOR_SWATCHES = {
    "athletic yellow": "#f5c542",
    "black": "#111111",
    "forest green": "#1f5f35",
    "forrest green": "#1f5f35",
    "gold": "#c9a227",
    "kelly green": "#2e9b4f",
    "navy": "#15284b",
    "pink": "#f28ab2",
    "purple": "#6f3fa0",
    "pruple": "#6f3fa0",
    "red": "#c72f2f",
    "royal blue": "#2453b3",
    "vegas gold": "#b9a36a",
    "white": "#f7f7f2",
}

FONT_TRANSLATIONS = {
    "adventure": "SF Fedora",
    "asos": "Full Pack 2025",
    "college": "College",
    "iceberg": "iceberg",
    "jersey": "Sports Jersey",
    "marker": "Bangers",
    "roboto": "Roboto",
    "rounded": "Dosis",
    "tough": "Black Ops One",
}

FONT_PROFILES = {
    "adventure": {"width_factor": 0.95, "number_width_factor": 0.7, "max_height_in": 1.35, "long_max_height_in": 1.75},
    "asos": {"width_factor": 1.0, "number_width_factor": 0.72, "max_height_in": 1.25, "long_max_height_in": 1.55},
    "college": {"width_factor": 1.12, "number_width_factor": 0.74, "max_height_in": 1.55, "long_max_height_in": 1.8},
    "iceberg": {"width_factor": 1.0, "number_width_factor": 0.72, "max_height_in": 1.25, "long_max_height_in": 1.55},
    "jersey": {"width_factor": 1.08, "number_width_factor": 0.82, "max_height_in": 1.45, "long_max_height_in": 1.75},
    "marker": {"width_factor": 1.1, "number_width_factor": 0.82, "max_height_in": 1.65, "long_max_height_in": 2.05},
    "roboto": {"width_factor": 1.16, "number_width_factor": 0.7, "max_height_in": 1.35, "long_max_height_in": 1.65},
    "rounded": {"width_factor": 1.05, "number_width_factor": 0.7, "max_height_in": 1.25, "long_max_height_in": 1.55},
    "tough": {"width_factor": 1.05, "number_width_factor": 0.82, "max_height_in": 1.25, "long_max_height_in": 1.6},
}

SKIP_TEXT_VALUES = {"", "no", "none", "n/a", "na"}


@dataclass(frozen=True)
class CutItem:
    order: str
    ship_to: str
    product: str
    product_color: str
    size: str
    kind: str
    text: str
    font: str
    color: str
    qty: int


def run_pdftotext(pdf_path: Path) -> str:
    try:
        result = subprocess.run(
            ["pdftotext", "-layout", str(pdf_path), "-"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except FileNotFoundError:
        raise SystemExit(
            "pdftotext was not found. Install Poppler first, then rerun this script."
        )
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"pdftotext failed:\n{exc.stderr.strip()}") from exc
    return normalize_text(result.stdout)


def normalize_text(value: str) -> str:
    return (
        value.replace("\u00ad", "-")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
        .replace("\xa0", " ")
    )


def clean_field(value: str) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    return value.strip(" ,:")


def compact_line(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def normalize_color(value: str) -> str:
    value = clean_field(value)
    if value.lower() == "forrest green":
        return "Forest Green"
    if value.lower() == "pruple":
        return "Purple"
    return value


def safe_filename(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._ -]+", "", value).strip()
    value = re.sub(r"\s+", "_", value)
    return value or "Unknown"


def rx_value(text: str, pattern: str) -> str:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    return clean_field(match.group(1)) if match else ""


def product_base_color(product: str) -> str:
    if " - " in product:
        return clean_field(product.rsplit(" - ", 1)[1].split("/")[0])
    return ""


def page_order(page: str) -> str:
    match = re.search(r"Order\s+#\s+(\d+)", page)
    return match.group(1) if match else ""


def page_ship_to(page: str) -> str:
    match = re.search(r"Ship To:\s*([^\n]+)", page)
    if not match:
        return ""
    return clean_field(re.split(r"\s+Order\s+#", match.group(1))[0])


def iter_order_items(page: str) -> Iterable[tuple[str, int, str]]:
    lines = page.splitlines()
    in_items = False
    current_product = ""
    current_qty = 0
    detail_lines: list[str] = []

    def flush() -> tuple[str, int, str] | None:
        if not current_product:
            return None
        return current_product, current_qty, clean_field(" ".join(detail_lines))

    for line in lines:
        if "Item" in line and "Description" in line and "Qty" in line:
            in_items = True
            continue
        if not in_items:
            continue
        if re.search(r"\bSub Total:", line):
            item = flush()
            if item:
                yield item
            break

        match = ITEM_RE.match(line)
        if match:
            item = flush()
            if item:
                yield item
            current_product = clean_field(match.group("product"))
            current_qty = int(match.group("qty"))
            detail_lines = []
            continue

        stripped = compact_line(line)
        if stripped and not stripped.startswith("$"):
            detail_lines.append(stripped)
    else:
        item = flush()
        if item:
            yield item


def add_item(
    items: list[CutItem],
    *,
    order: str,
    ship_to: str,
    product: str,
    product_color: str,
    size: str,
    kind: str,
    text: str,
    font: str,
    color: str,
    qty: int,
) -> None:
    text = clean_field(text)
    if text.lower() in SKIP_TEXT_VALUES:
        return
    items.append(
        CutItem(
            order=order,
            ship_to=ship_to,
            product=product,
            product_color=product_color,
            size=size,
            kind=kind,
            text=text,
            font=clean_field(font) or "Arial",
            color=normalize_color(color) or "Unknown",
            qty=max(qty, 1),
        )
    )


def parse_custom_item(
    order: str, ship_to: str, product: str, qty: int, details: str
) -> list[CutItem]:
    items: list[CutItem] = []
    product_color = product_base_color(product)
    size = rx_value(details, r"\bSize:\s*(.*?)(?:,\s*(?:Text|Custom Number|Number|Right Arm|Left Arm|pplr)|$)")

    number = rx_value(details, r"\bNumber \(Optional\):\s*(.*?),\s*Number Font\*:")
    number_font = rx_value(details, r"\bNumber Font\*:\s*(.*?),\s*Number Font Color:")
    number_color = rx_value(details, r"\bNumber Font Color:\s*(.*?)(?:,\s*Text \(No Emojis\)\*:|,\s*pplr|$)")
    if number:
        add_item(
            items,
            order=order,
            ship_to=ship_to,
            product=product,
            product_color=product_color,
            size=size,
            kind="Number",
            text=number,
            font=number_font,
            color=number_color,
            qty=qty,
        )

    text_number_text = rx_value(
        details, r"\bText \(No Emojis\)\*:\s*(.*?),\s*Text Font\*:"
    )
    text_number_font = rx_value(
        details, r"\bText Font\*:\s*(.*?),\s*Text Font Color:"
    )
    text_number_color = rx_value(
        details, r"\bText Font Color:\s*(.*?)(?:,\s*pplr|$)"
    )
    if text_number_text:
        add_item(
            items,
            order=order,
            ship_to=ship_to,
            product=product,
            product_color=product_color,
            size=size,
            kind="Text",
            text=text_number_text,
            font=text_number_font,
            color=text_number_color,
            qty=qty,
        )

    custom_number = rx_value(
        details, r"\bCustom Number\*:\s*(.*?),\s*Choose Font\*:"
    )
    custom_number_font = rx_value(
        details, r"\bChoose Font\*:\s*(.*?),\s*Choose A\s+Color\*:"
    )
    custom_number_color = rx_value(
        details, r"\bChoose A\s+Color\*:\s*(.*?)(?:,\s*pplr|$)"
    )
    if custom_number:
        add_item(
            items,
            order=order,
            ship_to=ship_to,
            product=product,
            product_color=product_color,
            size=size,
            kind="Number",
            text=custom_number,
            font=custom_number_font,
            color=custom_number_color,
            qty=qty,
        )

    simple_text = rx_value(details, r"\bText:\s*(.*?),\s*Choose Font:")
    simple_font = rx_value(details, r"\bChoose Font:\s*(.*?),\s*Choose A\s+Color:")
    simple_color = rx_value(details, r"\bChoose A\s+Color:\s*(.*?)(?:,\s*pplr|$)")
    if simple_text:
        add_item(
            items,
            order=order,
            ship_to=ship_to,
            product=product,
            product_color=product_color,
            size=size,
            kind="Text",
            text=simple_text,
            font=simple_font,
            color=simple_color,
            qty=qty,
        )

    headband_text = rx_value(details, r"\bText\*:\s*(.*?),\s*Font\*:")
    headband_font = rx_value(details, r"\bFont\*:\s*(.*?),\s*Font Color:")
    headband_color = rx_value(details, r"\bFont Color:\s*(.*?)(?:,\s*pplr|$)")
    if headband_text:
        add_item(
            items,
            order=order,
            ship_to=ship_to,
            product=product,
            product_color=product_color,
            size=size,
            kind="Text",
            text=headband_text,
            font=headband_font,
            color=headband_color,
            qty=qty,
        )

    compression_text = rx_value(
        details, r"\bText \(No Emojis\)\*:\s*(.*?),\s*Fonts\*:"
    )
    compression_font = rx_value(
        details, r"\bFonts\*:\s*(.*?),\s*Choose Font Color:"
    )
    compression_color = rx_value(
        details, r"\bChoose Font Color:\s*(.*?)(?:,\s*pplr|$)"
    )
    if compression_text:
        add_item(
            items,
            order=order,
            ship_to=ship_to,
            product=product,
            product_color=product_color,
            size=size,
            kind="Text",
            text=compression_text,
            font=compression_font,
            color=compression_color,
            qty=qty,
        )

    forearm_font = rx_value(details, r"\bFont\*:\s*(.*?),\s*Font Color\*:")
    forearm_color = rx_value(details, r"\bFont Color\*:\s*(.*?)(?:,\s*pplr|$)")
    right_arm = rx_value(details, r"\bRight Arm\*:\s*(.*?),\s*Left Arm\*:")
    left_arm = rx_value(details, r"\bLeft Arm\*:\s*(.*?),\s*Font\*:")
    if right_arm:
        add_item(
            items,
            order=order,
            ship_to=ship_to,
            product=product,
            product_color=product_color,
            size=size,
            kind="Right Arm",
            text=right_arm,
            font=forearm_font,
            color=forearm_color,
            qty=qty,
        )
    if left_arm:
        add_item(
            items,
            order=order,
            ship_to=ship_to,
            product=product,
            product_color=product_color,
            size=size,
            kind="Left Arm",
            text=left_arm,
            font=forearm_font,
            color=forearm_color,
            qty=qty,
        )

    return items


def parse_pdf_text(text: str) -> list[CutItem]:
    cut_items: list[CutItem] = []
    for page in text.split("\f"):
        order = page_order(page)
        if not order:
            continue
        ship_to = page_ship_to(page)
        for product, qty, details in iter_order_items(page):
            cut_items.extend(parse_custom_item(order, ship_to, product, qty, details))
    return cut_items


def color_key(item: CutItem) -> str:
    return item.color.lower()


def svg_fill(color: str) -> str:
    return COLOR_SWATCHES.get(color.lower(), "#111111")


def translated_font(font: str) -> str:
    return FONT_TRANSLATIONS.get(font.strip().lower(), font.strip() or "Arial")


def font_profile(font: str) -> dict[str, float]:
    return FONT_PROFILES.get(
        font.strip().lower(),
        {
            "width_factor": 1.0,
            "number_width_factor": 0.72,
            "max_height_in": 1.3,
            "long_max_height_in": 1.6,
        },
    )


def max_height_for_box(box: LayoutBox) -> float:
    profile = font_profile(box.item.font)
    if box.item.kind.lower() == "number":
        return 1.55 * 96
    text_length = len(box.item.text.strip())
    if text_length >= 12:
        return profile.get("long_max_height_in", profile["max_height_in"]) * 96
    return profile["max_height_in"] * 96


def base_font_size_for(text: str, kind: str) -> float:
    if kind.lower() == "number":
        return 118
    if len(text) <= 10:
        return 92
    if len(text) <= 18:
        return 76
    return 62


def estimated_text_width(text: str, font_size: float, font: str = "") -> float:
    width = 0.0
    for char in text:
        if char == " ":
            width += font_size * 0.28
        elif char in "1Iil.,'":
            width += font_size * 0.32
        elif char in "MW@#%&":
            width += font_size * 0.86
        elif char.isdigit():
            width += font_size * 0.56
        else:
            width += font_size * 0.62
    return max(width * font_profile(font)["width_factor"], font_size)


def estimated_number_width(text: str, font_size: float, font: str = "") -> float:
    profile = font_profile(font)
    digit_width = font_size * profile["number_width_factor"]
    width = 0.0
    for char in text:
        if char.isdigit():
            width += digit_width
        elif char == " ":
            width += font_size * 0.28
        else:
            width += font_size * 0.62 * profile["width_factor"]
    return max(width, font_size * 0.72)


@dataclass(frozen=True)
class PlacedText:
    item: CutItem
    x: float
    y: float
    font_size: float
    scale_x: float
    scale_y: float
    box_width: float
    box_height: float
    rotation: int = 0


@dataclass(frozen=True)
class LayoutBox:
    item: CutItem
    font_size: float
    scale_x: float
    scale_y: float
    box_width: float
    box_height: float


@dataclass(frozen=True)
class PackBox:
    box: LayoutBox
    rotate: bool = False

    @property
    def width(self) -> float:
        return self.box.box_width

    @property
    def height(self) -> float:
        return self.box.box_height


@dataclass(frozen=True)
class LayoutUnit:
    boxes: list[LayoutBox]

    @property
    def width(self) -> float:
        return sum(box.box_width for box in self.boxes)

    @property
    def height(self) -> float:
        return max(box.box_height for box in self.boxes)


@dataclass
class LayoutRow:
    units: list[LayoutUnit]
    width: float
    height: float


def resize_box_width(box: LayoutBox, new_width: float) -> LayoutBox:
    new_width = max(1.0, new_width)
    width_ratio = new_width / box.box_width
    return LayoutBox(
        item=box.item,
        font_size=box.font_size,
        scale_x=box.scale_x * width_ratio,
        scale_y=box.scale_y,
        box_width=new_width,
        box_height=box.box_height,
    )


def build_layout_units(boxes: list[LayoutBox], column_gap: float) -> list[LayoutUnit]:
    units: list[LayoutUnit] = []
    index = 0
    while index < len(boxes):
        current = boxes[index]
        nxt = boxes[index + 1] if index + 1 < len(boxes) else None
        if (
            nxt
            and current.item.kind.lower() == "number"
            and nxt.item.kind.lower() != "number"
            and current.item.order == nxt.item.order
            and current.item.color == nxt.item.color
        ):
            units.append(LayoutUnit([nxt, current]))
            index += 2
            continue
        units.append(LayoutUnit([current]))
        index += 1
    return units


def fit_unit_to_width(unit: LayoutUnit, max_width: float, column_gap: float) -> LayoutUnit:
    gaps = column_gap * (len(unit.boxes) - 1)
    total_width = unit.width + gaps
    if total_width <= max_width:
        return unit

    boxes = list(unit.boxes)
    overflow = total_width - max_width
    for index, box in enumerate(boxes):
        if box.item.kind.lower() == "number":
            continue
        min_width = 2.25 * 96
        shrink_by = min(overflow, max(0.0, box.box_width - min_width))
        if shrink_by > 0:
            boxes[index] = resize_box_width(box, box.box_width - shrink_by)
            overflow -= shrink_by
        if overflow <= 0:
            break
    return LayoutUnit(boxes)


def unit_with_scale(unit: LayoutUnit, scale: float) -> LayoutUnit:
    if abs(scale - 1.0) < 0.0001:
        return unit
    return LayoutUnit(
        [
            LayoutBox(
                item=box.item,
                font_size=box.font_size,
                scale_x=box.scale_x * scale,
                scale_y=box.scale_y * scale,
                box_width=box.box_width * scale,
                box_height=box.box_height * scale,
            )
            for box in unit.boxes
        ]
    )


def make_rows(
    units: list[LayoutUnit], content_width: float, column_gap: float
) -> list[LayoutRow]:
    rows: list[LayoutRow] = []
    for unit in units:
        unit = fit_unit_to_width(unit, content_width, column_gap)
        unit_width = unit.width + column_gap * (len(unit.boxes) - 1)
        if rows and len(unit.boxes) == 1:
            previous = rows[-1]
            previous_boxes = [box for row_unit in previous.units for box in row_unit.boxes]
            if (
                len(previous_boxes) == 1
                and previous_boxes[0].item.text == unit.boxes[0].item.text
                and previous_boxes[0].item.font == unit.boxes[0].item.font
                and previous_boxes[0].item.color == unit.boxes[0].item.color
            ):
                next_width = previous.width + column_gap + unit_width
                if next_width <= content_width:
                    previous.units.append(unit)
                    previous.width = next_width
                    previous.height = max(previous.height, unit.height)
                    continue
        is_single_number = (
            len(unit.boxes) == 1 and unit.boxes[0].item.kind.lower() == "number"
        )
        if is_single_number and rows:
            previous = rows[-1]
            next_width = previous.width + column_gap + unit_width
            if next_width <= content_width:
                previous.units.append(unit)
                previous.width = next_width
                previous.height = max(previous.height, unit.height)
                continue
        rows.append(LayoutRow([unit], unit_width, unit.height))
    return rows


def scaled_rows_to_fill_width(
    rows: list[LayoutRow], content_width: float, column_gap: float
) -> list[LayoutRow]:
    scaled_rows: list[LayoutRow] = []
    for row in rows:
        fill = (content_width * 0.96) / row.width if row.width else 1.0
        has_text = any(
            box.item.kind.lower() != "number"
            for unit in row.units
            for box in unit.boxes
        )
        max_height = min(
            max_height_for_box(box)
            for unit in row.units
            for box in unit.boxes
        )
        height_cap_scale = max_height / row.height if row.height else 1.0
        # Text rows should use the full width. Pure number rows stay closer to
        # production size unless paired with text. Font-specific caps keep short
        # words from dwarfing longer names in other fonts.
        if has_text:
            row_scale = max(1.0, min(fill, height_cap_scale))
        else:
            row_scale = 1.0
        scaled_units = [unit_with_scale(unit, row_scale) for unit in row.units]
        scaled_width = (
            sum(unit.width for unit in scaled_units)
            + column_gap * (sum(len(unit.boxes) for unit in scaled_units) - 1)
            + column_gap * (len(scaled_units) - 1)
        )
        scaled_height = max(unit.height for unit in scaled_units)
        scaled_rows.append(LayoutRow(scaled_units, scaled_width, scaled_height))
    return scaled_rows


def box_for_item(item: CutItem) -> LayoutBox:
    font_size = 100.0
    is_number = item.kind.lower() == "number"
    if is_number:
        estimated_width = estimated_number_width(item.text, font_size, item.font)
        target_width = 1.5 * 96
        target_height = 2.25 * 96
        estimated_height = font_size * 0.92
        return LayoutBox(
            item=item,
            font_size=font_size,
            scale_x=target_width / estimated_width,
            scale_y=target_height / estimated_height,
            box_width=target_width,
            box_height=target_height,
        )
    else:
        estimated_width = estimated_text_width(item.text, font_size, item.font)
    text_length = len(item.text.strip())
    if is_number:
        target_height = 1.05 * 96
    elif text_length <= 5:
        target_height = 0.95 * 96
    elif text_length <= 10:
        target_height = 0.80 * 96
    else:
        target_height = 0.78 * 96

    # Keep scale proportional. Row-level scaling later grows rows to use width.
    estimated_height = font_size * 0.92
    scale = target_height / estimated_height
    target_width = estimated_width * scale
    box = LayoutBox(
        item=item,
        font_size=font_size,
        scale_x=scale,
        scale_y=scale,
        box_width=target_width,
        box_height=target_height,
    )
    return apply_product_size_profile(box)


def apply_product_size_profile(box: LayoutBox) -> LayoutBox:
    if box.item.kind.lower() == "number":
        return box

    product = box.item.product.lower()
    text_length = len(box.item.text.strip())
    target_width: float | None = None
    target_height: float | None = None

    if "headband" in product:
        target_width = 3.5 * 96 if text_length <= 4 else min(5.5 * 96, max(box.box_width, 4.25 * 96))
        target_height = 1.05 * 96
    elif "arm sleeve" in product:
        target_width = 7.9 * 96
        target_height = 1.55 * 96
    elif "compression" in product:
        target_width = 7.8 * 96
        target_height = 1.45 * 96

    if target_width is None or target_height is None:
        return box

    width_ratio = target_width / box.box_width if box.box_width else 1.0
    height_ratio = target_height / box.box_height if box.box_height else 1.0
    return LayoutBox(
        item=box.item,
        font_size=box.font_size,
        scale_x=box.scale_x * width_ratio,
        scale_y=box.scale_y * height_ratio,
        box_width=target_width,
        box_height=target_height,
    )


def should_rotate_for_packing(box: LayoutBox) -> bool:
    text = box.item.text.strip()
    product = box.item.product.lower()
    is_text = box.item.kind.lower() != "number"

    if "headband" in product:
        return True
    if "arm sleeve" in product and is_text and len(text) >= 5:
        return True
    if "compression" in product and is_text and len(text) >= 8:
        return True
    return False


def make_column_packed_pages(
    boxes: list[LayoutBox],
    page_width: float,
    page_height: float,
    margin: float,
    gap: float,
) -> list[list[PlacedText]]:
    content_width = page_width - margin * 2
    content_height = page_height - margin * 2
    pack_boxes = [PackBox(box, should_rotate_for_packing(box)) for box in boxes]
    pack_boxes.sort(
        key=lambda entry: (
            0 if entry.rotate else 1,
            -entry.height,
            -entry.width,
            entry.box.item.color.lower(),
        )
    )

    pages: list[list[PlacedText]] = []
    current_page: list[PlacedText] = []
    columns: list[dict[str, float]] = []

    def commit_page() -> None:
        nonlocal current_page, columns
        if current_page:
            pages.append(current_page)
        current_page = []
        columns = []

    def current_width() -> float:
        if not columns:
            return 0.0
        return max(column["x"] + column["width"] - margin for column in columns)

    for pack_box in pack_boxes:
        chosen: dict[str, float] | None = None
        for column in columns:
            if (
                pack_box.width <= column["width"] + 0.001
                and column["y"] + pack_box.height <= margin + content_height + 0.001
            ):
                chosen = column
                break

        if chosen is None:
            x = margin if not columns else max(column["x"] + column["width"] for column in columns) + gap
            if columns and x + pack_box.width > margin + content_width:
                commit_page()
                x = margin
            chosen = {"x": x, "y": margin, "width": pack_box.width}
            columns.append(chosen)

        box = pack_box.box
        current_page.append(
            PlacedText(
                item=box.item,
                x=chosen["x"],
                y=chosen["y"],
                font_size=box.font_size,
                scale_x=box.scale_x,
                scale_y=box.scale_y,
                box_width=box.box_width,
                box_height=box.box_height,
                rotation=90 if pack_box.rotate else 0,
            )
        )
        chosen["y"] += pack_box.height + gap
        chosen["width"] = max(chosen["width"], pack_box.width)

        if current_width() > content_width and len(columns) > 1:
            overflow = current_page.pop()
            columns.pop()
            if not current_page:
                current_page.append(overflow)
            else:
                commit_page()
                new_column = {"x": margin, "y": margin + pack_box.height + gap, "width": pack_box.width}
                columns.append(new_column)
                current_page.append(overflow)

    if current_page:
        pages.append(current_page)
    return pages


def fit_box_to_content_width(box: LayoutBox, content_width: float) -> LayoutBox:
    if box.box_width <= content_width:
        return box
    if box.item.kind.lower() == "number":
        return box
    width_ratio = content_width / box.box_width
    return LayoutBox(
        item=box.item,
        font_size=box.font_size,
        scale_x=box.scale_x * width_ratio,
        scale_y=box.scale_y,
        box_width=content_width,
        box_height=box.box_height,
    )


def make_horizontal_packed_pages(
    boxes: list[LayoutBox],
    page_width: float,
    page_height: float,
    margin: float,
    gap: float,
) -> list[list[PlacedText]]:
    content_width = page_width - margin * 2
    content_height = page_height - margin * 2
    pages: list[list[PlacedText]] = []
    current_page: list[PlacedText] = []
    x = margin
    y = margin
    row_height = 0.0

    def new_page() -> None:
        nonlocal current_page, x, y, row_height
        if current_page:
            pages.append(current_page)
        current_page = []
        x = margin
        y = margin
        row_height = 0.0

    def new_row() -> None:
        nonlocal x, y, row_height
        x = margin
        y += row_height + gap
        row_height = 0.0

    for raw_box in boxes:
        box = fit_box_to_content_width(raw_box, content_width)
        if x > margin and x + box.box_width > margin + content_width:
            new_row()
        if y > margin and y + box.box_height > margin + content_height:
            new_page()
        if box.box_height > content_height and current_page:
            new_page()

        current_page.append(
            PlacedText(
                item=box.item,
                x=x,
                y=y,
                font_size=box.font_size,
                scale_x=box.scale_x,
                scale_y=box.scale_y,
                box_width=box.box_width,
                box_height=box.box_height,
                rotation=0,
            )
        )
        x += box.box_width + gap
        row_height = max(row_height, box.box_height)

    if current_page:
        pages.append(current_page)
    return pages


def make_svg_pages(items: list[CutItem]) -> tuple[list[list[PlacedText]], float, float]:
    page_width = 8.5 * 96
    page_height = 12 * 96
    margin = 6.0
    column_gap = 18.0
    row_gap = 0.0
    content_width = page_width - margin * 2
    content_height = page_height - margin * 2

    boxes = [box_for_item(item) for item in expanded_items(items)]
    if any("headband" in box.item.product.lower() or "arm sleeve" in box.item.product.lower() for box in boxes):
        return (
            make_horizontal_packed_pages(boxes, page_width, page_height, margin, column_gap),
            page_width,
            page_height,
        )

    units = build_layout_units(boxes, column_gap)
    rows = scaled_rows_to_fill_width(
        make_rows(units, content_width, column_gap), content_width, column_gap
    )

    pages: list[list[PlacedText]] = []
    current_page: list[PlacedText] = []
    y = margin

    def new_page() -> None:
        nonlocal current_page, y
        if current_page:
            pages.append(current_page)
        current_page = []
        y = margin

    for row in rows:
        if y > margin and y + row.height > margin + content_height:
            new_page()

        x = margin
        for unit in row.units:
            for box in unit.boxes:
                current_page.append(
                    PlacedText(
                        item=box.item,
                        x=x,
                        y=y,
                        font_size=box.font_size,
                        scale_x=box.scale_x,
                        scale_y=box.scale_y,
                        box_width=box.box_width,
                        box_height=box.box_height,
                    )
                )
                x += box.box_width + column_gap
        y += row.height + row_gap

    if current_page:
        pages.append(current_page)

    return pages, page_width, page_height


def expanded_items(items: Iterable[CutItem]) -> list[CutItem]:
    expanded: list[CutItem] = []
    for item in items:
        expanded.extend([item] * item.qty)
    return expanded


def render_svg(color: str, items: list[CutItem], out_path: Path) -> None:
    pages, page_width, page_height = make_svg_pages(items)
    stroke = "#ff5a5f"

    for page_index, placed in enumerate(pages, start=1):
        page_path = out_path
        if page_index > 1:
            page_path = out_path.with_name(f"{out_path.stem}_{page_index}{out_path.suffix}")

        parts = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            (
                f'<svg xmlns="http://www.w3.org/2000/svg" width="8.5in" '
                f'height="12in" viewBox="0 0 {page_width:.0f} {page_height:.0f}">'
            ),
        ]

        for entry in placed:
            item = entry.item
            safe_font = xml_escape(translated_font(item.font))
            baseline = entry.font_size * 0.78
            if entry.rotation == 90:
                transform = (
                    f"translate({entry.x + entry.box_height:.2f} {entry.y:.2f}) "
                    f"rotate(90) scale({entry.scale_x:.4f} {entry.scale_y:.4f})"
                )
            else:
                transform = (
                    f"translate({entry.x:.2f} {entry.y:.2f}) "
                    f"scale({entry.scale_x:.4f} {entry.scale_y:.4f})"
                )
            parts.append(
                f'<g transform="{transform}">'
                f'<text x="0" y="{baseline:.2f}" '
                f'font-family="{safe_font}" font-size="{entry.font_size:.2f}" '
                f'fill="none" stroke="{stroke}" stroke-width="1" '
                f'paint-order="stroke" vector-effect="non-scaling-stroke">'
                f'{xml_escape(item.text)}</text></g>'
            )

        parts.append("</svg>")
        page_path.write_text("\n".join(parts), encoding="utf-8")


def write_manifest_csv(items: list[CutItem], out_path: Path) -> None:
    with out_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "order",
                "ship_to",
                "product",
                "product_color",
                "size",
                "kind",
                "text",
                "font",
                "cut_color",
                "qty",
            ]
        )
        for item in items:
            writer.writerow(
                [
                    item.order,
                    item.ship_to,
                    item.product,
                    item.product_color,
                    item.size,
                    item.kind,
                    item.text,
                    item.font,
                    item.color,
                    item.qty,
                ]
            )


def write_review_html(items: list[CutItem], out_path: Path) -> None:
    rows = []
    for item in items:
        rows.append(
            "<tr>"
            f"<td>{html.escape(item.order)}</td>"
            f"<td>{html.escape(item.ship_to)}</td>"
            f"<td>{html.escape(item.product)}</td>"
            f"<td>{html.escape(item.size)}</td>"
            f"<td>{html.escape(item.kind)}</td>"
            f"<td class='preview' style='font-family:{html.escape(item.font)}'>{html.escape(item.text)}</td>"
            f"<td>{html.escape(item.font)}</td>"
            f"<td>{html.escape(item.color)}</td>"
            f"<td>{item.qty}</td>"
            "</tr>"
        )

    document = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Packing Slip Cut Review</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 32px; color: #222; }}
    h1 {{ font-size: 24px; margin: 0 0 16px; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border-bottom: 1px solid #ddd; padding: 8px 10px; text-align: left; vertical-align: top; }}
    th {{ background: #f5f5f5; font-size: 12px; text-transform: uppercase; letter-spacing: .04em; }}
    .preview {{ font-size: 24px; white-space: nowrap; }}
  </style>
</head>
<body>
  <h1>Packing Slip Cut Review</h1>
  <p>{len(items)} custom cut entries found. Quantities are duplicated inside each SVG.</p>
  <table>
    <thead>
      <tr>
        <th>Order</th><th>Ship To</th><th>Product</th><th>Size</th><th>Kind</th>
        <th>Text</th><th>Font</th><th>Cut Color</th><th>Qty</th>
      </tr>
    </thead>
    <tbody>
      {''.join(rows)}
    </tbody>
  </table>
</body>
</html>
"""
    out_path.write_text(document, encoding="utf-8")


def write_outputs(items: list[CutItem], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for old_file in output_dir.glob("*.svg"):
        old_file.unlink()
    write_manifest_csv(items, output_dir / "manifest.csv")
    write_review_html(items, output_dir / "review.html")

    grouped: dict[str, list[CutItem]] = {}
    display_names: dict[str, str] = {}
    for item in items:
        key = color_key(item)
        grouped.setdefault(key, []).append(item)
        display_names.setdefault(key, item.color)

    for key, group in sorted(grouped.items()):
        color = display_names[key]
        render_svg(color, group, output_dir / f"{safe_filename(color)}.svg")


def svg_file_count(output_dir: Path) -> int:
    return len(list(output_dir.glob("*.svg")))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Create per-color SVG cut files from packing slip PDFs."
    )
    parser.add_argument("pdf", type=Path, help="Packing slip PDF to parse")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output folder. Defaults to ./cut_batch_YYYYMMDD_HHMMSS",
    )
    args = parser.parse_args(argv)

    pdf_path = args.pdf.expanduser().resolve()
    if not pdf_path.exists():
        parser.error(f"PDF not found: {pdf_path}")

    output_dir = args.output
    if output_dir is None:
        output_dir = Path(f"cut_batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    output_dir = output_dir.resolve()

    text = run_pdftotext(pdf_path)
    items = parse_pdf_text(text)
    if not items:
        raise SystemExit("No custom text/number cut items were found.")

    write_outputs(items, output_dir)

    colors = sorted({item.color for item in items}, key=str.lower)
    print(f"Found {len(items)} custom cut entries.")
    print(f"Wrote {svg_file_count(output_dir)} SVG files plus manifest/review to: {output_dir}")
    print("Colors: " + ", ".join(colors))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
