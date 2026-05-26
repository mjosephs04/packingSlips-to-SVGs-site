# Packing Slip to SVG Cut Files

This tool parses Custom Sports Sleeves packing slip PDFs and creates one editable SVG file per text/vinyl color.

## Usage

```bash
python3 packing_slip_to_svg.py "/path/to/Packing Slips.pdf" -o ./cut_batch
```

The output folder contains:

- `manifest.csv`: every parsed custom text/number item
- `review.html`: quick visual review of orders, fonts, colors, and text
- one `.svg` file per cut color, such as `White.svg`, `Black.svg`, `Red.svg`
- SVGs are 8.5 inches wide by 12 inches tall and contain only production text/number objects, with no order labels or divider lines.
- Layout sizing is tuned to the provided Graphtec PDF examples so dense colors like White can fit on one sheet when possible.
- Packing slip font names are translated to production font names in the SVGs, and matching text/number pairs from the same order are packed onto the same row when they fit.

## Current Workflow

1. Export or download packing slips as a PDF.
2. Run the script.
3. Open `review.html` and check that the extracted text/font/color is correct.
4. Import each color SVG into Graphtec software.
5. In Graphtec, convert text to outlines/cut paths if needed before sending to the cutter.

## Notes

- The SVGs keep text as editable text and reference fonts by name. The matching fonts need to be installed on the local machine.
- Quantities are duplicated inside the SVG files.
- Combined text/number products are split into separate cut entries when the number and text have different colors.
- Graphtec `.gstudio` files are proprietary binary files, so this first version uses SVG as the reliable handoff format.

## Website

Run the local upload website:

```bash
python3 web_app.py
```

Then open:

```text
http://127.0.0.1:8765
```

Upload a packing slip PDF, review the parsed custom entries, then download the SVGs individually or as a ZIP.
