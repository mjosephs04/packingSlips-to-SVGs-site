#!/usr/bin/env python3
"""
Local website for uploading packing slips and downloading per-color SVG files.

Run:
    python3 web_app.py

Then open:
    http://127.0.0.1:8765
"""

from __future__ import annotations

import html
import io
import json
import mimetypes
import re
import shutil
import sys
import traceback
import uuid
import zipfile
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

import packing_slip_to_svg as converter


ROOT = Path(__file__).resolve().parent
BATCH_ROOT = ROOT / "web_batches"
MAX_UPLOAD_BYTES = 40 * 1024 * 1024


INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Packing Slip SVG Builder</title>
  <style>
    :root {
      --ink: #161616;
      --muted: #666f78;
      --line: #d9dee4;
      --soft: #f4f6f8;
      --panel: #ffffff;
      --accent: #145c63;
      --accent-2: #d18a2f;
      --danger: #a3382c;
    }

    * { box-sizing: border-box; }

    body {
      margin: 0;
      min-height: 100vh;
      font-family: Arial, Helvetica, sans-serif;
      color: var(--ink);
      background: #eef1f4;
    }

    header {
      border-bottom: 1px solid var(--line);
      background: var(--panel);
    }

    .topbar {
      max-width: 1120px;
      margin: 0 auto;
      padding: 18px 24px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
    }

    .brand {
      display: flex;
      align-items: center;
      gap: 12px;
      font-weight: 700;
      font-size: 18px;
    }

    .mark {
      width: 34px;
      height: 34px;
      border-radius: 6px;
      background: linear-gradient(135deg, var(--accent), #4aa3a0);
      display: grid;
      place-items: center;
      color: white;
      font-weight: 800;
    }

    main {
      max-width: 1120px;
      margin: 0 auto;
      padding: 28px 24px 56px;
    }

    .workspace {
      display: grid;
      grid-template-columns: minmax(320px, 420px) 1fr;
      gap: 24px;
      align-items: start;
    }

    .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 20px;
    }

    h1 {
      font-size: 28px;
      margin: 0 0 8px;
      letter-spacing: 0;
    }

    h2 {
      font-size: 17px;
      margin: 0 0 14px;
      letter-spacing: 0;
    }

    p {
      margin: 0;
      color: var(--muted);
      line-height: 1.45;
    }

    .dropzone {
      margin-top: 18px;
      display: grid;
      gap: 14px;
      border: 1px dashed #aab4bf;
      border-radius: 8px;
      background: var(--soft);
      padding: 22px;
      min-height: 190px;
      align-content: center;
      transition: border-color .15s, background .15s;
    }

    .dropzone.dragging {
      border-color: var(--accent);
      background: #e7f4f3;
    }

    .file-row {
      display: flex;
      align-items: center;
      gap: 10px;
      color: var(--muted);
      min-width: 0;
    }

    .file-row span {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    input[type="file"] { display: none; }

    button, .button {
      appearance: none;
      border: 1px solid transparent;
      border-radius: 6px;
      background: var(--accent);
      color: white;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      font-size: 14px;
      font-weight: 700;
      min-height: 40px;
      padding: 0 14px;
      text-decoration: none;
      white-space: nowrap;
    }

    button.secondary, .button.secondary {
      background: white;
      border-color: var(--line);
      color: var(--ink);
    }

    button:disabled {
      opacity: .55;
      cursor: not-allowed;
    }

    .actions {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 16px;
    }

    .status {
      margin-top: 14px;
      min-height: 22px;
      font-size: 14px;
      color: var(--muted);
    }

    .status.error { color: var(--danger); }

    .summary {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 18px;
    }

    .metric {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      background: #fbfcfd;
    }

    .metric strong {
      display: block;
      font-size: 26px;
      line-height: 1;
      margin-bottom: 6px;
    }

    .metric span {
      color: var(--muted);
      font-size: 13px;
    }

    .empty {
      min-height: 360px;
      display: grid;
      align-content: center;
      justify-items: center;
      gap: 10px;
      text-align: center;
    }

    .downloads {
      display: grid;
      gap: 10px;
    }

    .download-row {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 12px;
      align-items: center;
      background: white;
    }

    .download-row small {
      color: var(--muted);
      display: block;
      margin-top: 4px;
    }

    table {
      border-collapse: collapse;
      width: 100%;
      margin-top: 16px;
      font-size: 13px;
    }

    th, td {
      border-bottom: 1px solid var(--line);
      padding: 9px 8px;
      text-align: left;
      vertical-align: top;
    }

    th {
      background: var(--soft);
      color: #4e5964;
      font-size: 11px;
      text-transform: uppercase;
    }

    .table-wrap {
      overflow-x: auto;
      border: 1px solid var(--line);
      border-radius: 8px;
    }

    .table-wrap table { margin: 0; min-width: 720px; }

    @media (max-width: 860px) {
      .workspace { grid-template-columns: 1fr; }
      .summary { grid-template-columns: 1fr; }
      .topbar { align-items: flex-start; flex-direction: column; }
    }
  </style>
</head>
<body>
  <header>
    <div class="topbar">
      <div class="brand"><div class="mark">SVG</div><span>Packing Slip SVG Builder</span></div>
      <p>Local PDF parser and per-color cut file generator</p>
    </div>
  </header>

  <main>
    <div class="workspace">
      <section class="panel">
        <h1>Upload Packing Slips</h1>
        <p>Select a packing slip PDF. The app will extract custom text and numbers, group them by cut color, and create SVG downloads.</p>

        <form id="upload-form" enctype="multipart/form-data">
          <label class="dropzone" id="dropzone">
            <input id="file-input" type="file" name="packing_slip" accept="application/pdf,.pdf">
            <div class="file-row">
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
                <path d="M12 3v12"></path><path d="m7 8 5-5 5 5"></path><path d="M5 21h14"></path>
              </svg>
              <span id="file-name">Drop a PDF here or click to browse</span>
            </div>
            <p>Maximum file size: 40 MB</p>
          </label>
          <div class="actions">
            <button id="submit-btn" type="submit" disabled>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><path d="m17 8-5-5-5 5"></path><path d="M12 3v12"></path>
              </svg>
              Generate SVGs
            </button>
            <button class="secondary" id="clear-btn" type="button">Clear</button>
          </div>
        </form>
        <div id="status" class="status"></div>
      </section>

      <section class="panel" id="results-panel">
        <div class="empty" id="empty-state">
          <h2>No Batch Yet</h2>
          <p>Generated SVG files and the review table will appear here after upload.</p>
        </div>
        <div id="results" hidden></div>
      </section>
    </div>
  </main>

  <script>
    const form = document.getElementById("upload-form");
    const fileInput = document.getElementById("file-input");
    const fileName = document.getElementById("file-name");
    const submitBtn = document.getElementById("submit-btn");
    const clearBtn = document.getElementById("clear-btn");
    const statusEl = document.getElementById("status");
    const dropzone = document.getElementById("dropzone");
    const emptyState = document.getElementById("empty-state");
    const results = document.getElementById("results");

    function setStatus(message, isError = false) {
      statusEl.textContent = message;
      statusEl.classList.toggle("error", isError);
    }

    function updateFileState() {
      const file = fileInput.files[0];
      fileName.textContent = file ? file.name : "Drop a PDF here or click to browse";
      submitBtn.disabled = !file;
    }

    function renderResults(data) {
      emptyState.hidden = true;
      results.hidden = false;

      const svgRows = data.svg_files.map(file => `
        <div class="download-row">
          <div><strong>${escapeHtml(file.name)}</strong><small>${file.count} parsed entries before quantity duplication</small></div>
          <a class="button secondary" href="${file.url}" download>Download</a>
        </div>
      `).join("");

      const previewRows = data.items.slice(0, 40).map(item => `
        <tr>
          <td>${escapeHtml(item.order)}</td>
          <td>${escapeHtml(item.ship_to)}</td>
          <td>${escapeHtml(item.text)}</td>
          <td>${escapeHtml(item.font)}</td>
          <td>${escapeHtml(item.color)}</td>
          <td>${escapeHtml(String(item.qty))}</td>
        </tr>
      `).join("");

      results.innerHTML = `
        <div class="summary">
          <div class="metric"><strong>${data.item_count}</strong><span>custom entries</span></div>
          <div class="metric"><strong>${data.color_count}</strong><span>SVG color files</span></div>
          <div class="metric"><strong>${data.piece_count}</strong><span>cut pieces with qty</span></div>
        </div>

        <div class="actions">
          <a class="button" href="${data.zip_url}" download>Download ZIP</a>
          <a class="button secondary" href="${data.manifest_url}" download>Manifest CSV</a>
          <a class="button secondary" href="${data.review_url}" target="_blank" rel="noopener">Open Review</a>
        </div>

        <h2 style="margin-top:22px;">SVG Files</h2>
        <div class="downloads">${svgRows}</div>

        <h2 style="margin-top:22px;">Parsed Items</h2>
        <div class="table-wrap">
          <table>
            <thead><tr><th>Order</th><th>Ship To</th><th>Text</th><th>Font</th><th>Color</th><th>Qty</th></tr></thead>
            <tbody>${previewRows}</tbody>
          </table>
        </div>
      `;
    }

    function escapeHtml(value) {
      return value.replace(/[&<>"']/g, char => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        "\\"": "&quot;",
        "'": "&#039;"
      }[char]));
    }

    fileInput.addEventListener("change", updateFileState);
    clearBtn.addEventListener("click", () => {
      fileInput.value = "";
      updateFileState();
      setStatus("");
    });

    for (const eventName of ["dragenter", "dragover"]) {
      dropzone.addEventListener(eventName, event => {
        event.preventDefault();
        dropzone.classList.add("dragging");
      });
    }

    for (const eventName of ["dragleave", "drop"]) {
      dropzone.addEventListener(eventName, event => {
        event.preventDefault();
        dropzone.classList.remove("dragging");
      });
    }

    dropzone.addEventListener("drop", event => {
      const file = event.dataTransfer.files[0];
      if (!file) return;
      const transfer = new DataTransfer();
      transfer.items.add(file);
      fileInput.files = transfer.files;
      updateFileState();
    });

    form.addEventListener("submit", async event => {
      event.preventDefault();
      const file = fileInput.files[0];
      if (!file) return;

      submitBtn.disabled = true;
      setStatus("Generating SVGs...");
      const formData = new FormData();
      formData.append("packing_slip", file);

      try {
        const response = await fetch("/upload", { method: "POST", body: formData });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "Upload failed");
        renderResults(data);
        setStatus(`Done. ${data.color_count} SVG files are ready.`);
      } catch (error) {
        setStatus(error.message, true);
      } finally {
        submitBtn.disabled = false;
      }
    });
  </script>
</body>
</html>
"""


def parse_multipart_pdf(headers, body: bytes) -> tuple[str, bytes]:
    content_type = headers.get("Content-Type", "")
    match = re.search(r"boundary=(?P<boundary>[^;]+)", content_type)
    if not match:
        raise ValueError("Missing multipart boundary.")

    boundary = match.group("boundary").strip().strip('"').encode()
    delimiter = b"--" + boundary

    for part in body.split(delimiter):
        if b'name="packing_slip"' not in part:
            continue
        header_blob, _, content = part.partition(b"\r\n\r\n")
        if not content:
            continue
        content = content.rsplit(b"\r\n", 1)[0]
        filename_match = re.search(
            rb'filename="([^"]*)"', header_blob, flags=re.IGNORECASE
        )
        filename = (
            filename_match.group(1).decode("utf-8", errors="replace")
            if filename_match
            else "packing_slip.pdf"
        )
        if not content.startswith(b"%PDF"):
            raise ValueError("Uploaded file does not look like a PDF.")
        return filename, content

    raise ValueError("No PDF file field named packing_slip was found.")


def item_to_dict(item: converter.CutItem) -> dict[str, object]:
    return {
        "order": item.order,
        "ship_to": item.ship_to,
        "product": item.product,
        "product_color": item.product_color,
        "size": item.size,
        "kind": item.kind,
        "text": item.text,
        "font": item.font,
        "color": item.color,
        "qty": item.qty,
    }


def create_zip(batch_dir: Path) -> Path:
    zip_path = batch_dir / "svg_batch.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file_path in sorted(batch_dir.iterdir()):
            if file_path.name == zip_path.name or not file_path.is_file():
                continue
            if file_path.suffix.lower() == ".pdf":
                continue
            archive.write(file_path, arcname=file_path.name)
    return zip_path


def process_upload(filename: str, content: bytes) -> dict[str, object]:
    batch_id = uuid.uuid4().hex[:12]
    batch_dir = BATCH_ROOT / batch_id
    batch_dir.mkdir(parents=True, exist_ok=True)

    pdf_name = Path(filename).name or "packing_slip.pdf"
    pdf_path = batch_dir / pdf_name
    pdf_path.write_bytes(content)

    text = converter.run_pdftotext(pdf_path)
    items = converter.parse_pdf_text(text)
    if not items:
        shutil.rmtree(batch_dir, ignore_errors=True)
        raise ValueError("No custom text or number items were found in that PDF.")

    converter.write_outputs(items, batch_dir)
    zip_path = create_zip(batch_dir)

    grouped_counts: dict[str, int] = {}
    for item in items:
        grouped_counts[item.color] = grouped_counts.get(item.color, 0) + 1

    svg_files = []
    for svg_path in sorted(batch_dir.glob("*.svg")):
        content = svg_path.read_text(encoding="utf-8")
        svg_files.append(
            {
                "name": svg_path.name,
                "count": content.count("<text "),
                "url": f"/download/{batch_id}/{svg_path.name}",
            }
        )

    return {
        "batch_id": batch_id,
        "item_count": len(items),
        "piece_count": sum(item.qty for item in items),
        "color_count": len(svg_files),
        "items": [item_to_dict(item) for item in items],
        "svg_files": svg_files,
        "zip_url": f"/download/{batch_id}/{zip_path.name}",
        "manifest_url": f"/download/{batch_id}/manifest.csv",
        "review_url": f"/download/{batch_id}/review.html",
    }


class AppHandler(BaseHTTPRequestHandler):
    server_version = "PackingSlipSvgBuilder/1.0"

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def send_bytes(
        self,
        content: bytes,
        *,
        status: HTTPStatus = HTTPStatus.OK,
        content_type: str = "application/octet-stream",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        if headers:
            for key, value in headers.items():
                self.send_header(key, value)
        self.end_headers()
        self.wfile.write(content)

    def send_json(self, payload: dict[str, object], status: HTTPStatus = HTTPStatus.OK) -> None:
        self.send_bytes(
            json.dumps(payload).encode("utf-8"),
            status=status,
            content_type="application/json; charset=utf-8",
        )

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/":
            self.send_bytes(
                INDEX_HTML.encode("utf-8"),
                content_type="text/html; charset=utf-8",
            )
            return
        if path.startswith("/download/"):
            self.handle_download(path)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        if urlparse(self.path).path != "/upload":
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0:
                raise ValueError("No upload data received.")
            if length > MAX_UPLOAD_BYTES:
                raise ValueError("PDF is too large. Maximum upload size is 40 MB.")

            body = self.rfile.read(length)
            filename, content = parse_multipart_pdf(self.headers, body)
            payload = process_upload(filename, content)
            self.send_json(payload)
        except Exception as exc:
            traceback.print_exc()
            self.send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

    def handle_download(self, path: str) -> None:
        parts = [unquote(part) for part in path.split("/") if part]
        if len(parts) != 3:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        _, batch_id, filename = parts
        if not re.fullmatch(r"[a-f0-9]{12}", batch_id):
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if Path(filename).name != filename:
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        file_path = BATCH_ROOT / batch_id / filename
        if not file_path.exists() or not file_path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        content_type = mimetypes.guess_type(file_path.name)[0]
        if file_path.suffix == ".svg":
            content_type = "image/svg+xml"
        content_type = content_type or "application/octet-stream"
        disposition = "inline" if file_path.suffix == ".html" else "attachment"
        self.send_bytes(
            file_path.read_bytes(),
            content_type=content_type,
            headers={"Content-Disposition": f'{disposition}; filename="{file_path.name}"'},
        )


def main() -> int:
    BATCH_ROOT.mkdir(parents=True, exist_ok=True)
    port = 8765
    server = ThreadingHTTPServer(("127.0.0.1", port), AppHandler)
    print(f"Packing Slip SVG Builder running at http://127.0.0.1:{port}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
