#!/usr/bin/env python3
"""Offline video + Apple Watch labeler for the tennis dataset.

Run from the repository root:

    python3 tools/offline_label_tool.py

Then open http://127.0.0.1:8765 in a browser.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import mimetypes
from dataclasses import dataclass
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


DEFAULT_CSV = Path("/Volumes/KINGSTON/label test/H_2_050526.csv")
DEFAULT_VIDEO = Path("/Volumes/KINGSTON/label test/Hannes_2_050526.mp4")
DEFAULT_OFFSET_SECONDS = 14.078
DEFAULT_OUTPUT = Path("labels/H_2_050526_events.csv")

LABELS = {
    "1": "Vorhand",
    "2": "Rueckhand",
    "3": "Kein Schlag / Other",
}

IMU_COLUMNS = [
    "motionUserAccelerationX(G)",
    "motionUserAccelerationY(G)",
    "motionUserAccelerationZ(G)",
    "motionRotationRateX(rad/s)",
    "motionRotationRateY(rad/s)",
    "motionRotationRateZ(rad/s)",
]


@dataclass(frozen=True)
class AppConfig:
    csv_path: Path
    video_path: Path
    output_path: Path
    offset_seconds: float


def parse_float(value: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def read_sensor_rows(csv_path: Path, offset_seconds: float) -> tuple[list[dict], list[dict]]:
    rows: list[dict] = []
    with csv_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        first_time: datetime | None = None
        for row in reader:
            timestamp = datetime.fromisoformat(row["loggingTime(txt)"])
            if first_time is None:
                first_time = timestamp

            csv_sec = (timestamp - first_time).total_seconds()
            acc_x, acc_y, acc_z, gyro_x, gyro_y, gyro_z = [
                parse_float(row.get(column, "0")) for column in IMU_COLUMNS
            ]
            acc = math.sqrt(acc_x * acc_x + acc_y * acc_y + acc_z * acc_z)
            gyro = math.sqrt(gyro_x * gyro_x + gyro_y * gyro_y + gyro_z * gyro_z)
            rows.append(
                {
                    "csv_t": round(csv_sec, 4),
                    "video_t": round(csv_sec - offset_seconds, 4),
                    "acc": round(acc, 5),
                    "gyro": round(gyro, 5),
                    "score": round(acc + 0.12 * gyro, 5),
                }
            )

    points = downsample_rows(rows, target_points=16000)
    peaks = detect_peaks(rows)
    return points, peaks


def downsample_rows(rows: list[dict], target_points: int) -> list[dict]:
    if len(rows) <= target_points:
        return rows

    bucket_size = math.ceil(len(rows) / target_points)
    points: list[dict] = []
    for start in range(0, len(rows), bucket_size):
        bucket = rows[start : start + bucket_size]
        strongest = max(bucket, key=lambda item: item["score"])
        points.append(strongest)
    return points


def detect_peaks(rows: list[dict], limit: int = 220, min_spacing_s: float = 0.45) -> list[dict]:
    candidates = [row for row in rows if row["video_t"] >= 0]
    selected: list[dict] = []
    for row in sorted(candidates, key=lambda item: item["score"], reverse=True):
        if all(abs(row["video_t"] - peak["video_t"]) >= min_spacing_s for peak in selected):
            selected.append(row)
        if len(selected) >= limit:
            break
    return sorted(selected, key=lambda item: item["video_t"])


def read_events(output_path: Path) -> list[dict]:
    if not output_path.exists():
        return []

    with output_path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_events(output_path: Path, events: list[dict]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["video_time_s", "csv_time_s", "label", "label_name", "note"]
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for event in sorted(events, key=lambda item: float(item["video_time_s"])):
            writer.writerow({field: event.get(field, "") for field in fields})


def app_html(config: AppConfig) -> str:
    labels_json = json.dumps(LABELS, ensure_ascii=True)
    video_name = config.video_path.name
    csv_name = config.csv_path.name
    output_name = str(config.output_path)
    return f"""<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Tennis Labeler</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --line: #d7dce3;
      --text: #17202a;
      --muted: #657385;
      --accent: #1d74d8;
      --green: #157f4f;
      --red: #bf3a35;
      --dark: #253244;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      overflow: hidden;
    }}
    header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 8px 12px;
      background: var(--dark);
      color: white;
    }}
    header h1 {{
      margin: 0;
      font-size: 16px;
      font-weight: 650;
    }}
    header .meta {{
      color: #d6dde7;
      font-size: 11px;
      text-align: right;
      line-height: 1.25;
    }}
    main {{
      display: grid;
      grid-template-columns: minmax(420px, 1fr) 390px;
      gap: 8px;
      padding: 8px;
      height: calc(100vh - 44px);
      min-height: 0;
    }}
    .workspace {{
      display: grid;
      grid-template-rows: auto minmax(260px, 1fr) 150px;
      gap: 8px;
      min-width: 0;
      min-height: 0;
    }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
    }}
    .video-panel {{
      display: flex;
      min-height: 0;
      background: #000000;
    }}
    video {{
      display: block;
      width: 100%;
      height: 100%;
      max-height: none;
      object-fit: contain;
      background: black;
    }}
    .chart-wrap {{
      position: relative;
      height: 150px;
    }}
    canvas {{
      display: block;
      width: 100%;
      height: 100%;
      cursor: crosshair;
    }}
    .controls, .labels {{
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 6px;
      padding: 6px 8px;
    }}
    .controls {{
      border-bottom: 1px solid #edf0f4;
    }}
    button {{
      border: 1px solid #b9c2ce;
      border-radius: 6px;
      background: white;
      color: var(--text);
      padding: 6px 8px;
      font: inherit;
      font-size: 13px;
      cursor: pointer;
    }}
    button:hover {{ border-color: var(--accent); }}
    button.primary {{
      background: var(--accent);
      border-color: var(--accent);
      color: white;
    }}
    button.green {{
      background: var(--green);
      border-color: var(--green);
      color: white;
    }}
    button.red {{
      background: var(--red);
      border-color: var(--red);
      color: white;
    }}
    label {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      color: var(--muted);
      font-size: 13px;
    }}
    input {{
      border: 1px solid #b9c2ce;
      border-radius: 6px;
      padding: 5px 7px;
      font: inherit;
      font-size: 13px;
      width: 78px;
    }}
    aside {{
      display: grid;
      grid-template-rows: auto minmax(0, 1fr) minmax(0, 1fr);
      gap: 8px;
      height: 100%;
      min-height: 0;
      overflow: hidden;
    }}
    .side-section {{
      padding: 8px;
      min-height: 0;
    }}
    .side-section h2 {{
      margin: 0 0 6px;
      font-size: 14px;
    }}
    .list {{
      border-top: 1px solid var(--line);
      height: calc(100% - 24px);
      overflow: auto;
    }}
    .row {{
      display: grid;
      grid-template-columns: 72px 1fr auto;
      gap: 6px;
      align-items: center;
      padding: 5px 0;
      border-bottom: 1px solid #edf0f4;
      font-size: 12px;
    }}
    .row button {{
      padding: 4px 6px;
      font-size: 12px;
    }}
    .time {{
      color: var(--muted);
      font-variant-numeric: tabular-nums;
    }}
    .badge {{
      display: inline-block;
      min-width: 22px;
      padding: 2px 6px;
      border-radius: 999px;
      background: #e8f0fb;
      color: #145ea9;
      text-align: center;
      font-weight: 650;
    }}
    .hint {{
      color: var(--muted);
      font-size: 12px;
      line-height: 1.45;
      margin-top: 8px;
    }}
    .status {{
      margin-left: auto;
      color: var(--muted);
      font-size: 13px;
    }}
    @media (max-width: 980px) {{
      main {{
        grid-template-columns: 1fr;
        height: auto;
        overflow: auto;
      }}
      body {{ overflow: auto; }}
      aside {{
        grid-template-rows: auto auto auto;
      }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>Tennis Labeler</h1>
    <div class="meta">
      Video: {video_name}<br>
      CSV: {csv_name} -> {output_name}
    </div>
  </header>
  <main>
    <section class="workspace">
      <div class="panel">
        <div class="controls">
          <button id="prevPeak">Peak zurueck</button>
          <button id="nextPeak" class="primary">Naechster Peak</button>
          <button id="minusFrame">-1 Frame</button>
          <button id="plusFrame">+1 Frame</button>
          <label>Offset <input id="offset" type="number" step="0.001" value="{config.offset_seconds:.3f}"> s</label>
          <span id="position" class="status">--</span>
        </div>
        <div class="labels">
          <button class="green" data-label="1">1 Vorhand</button>
          <button class="green" data-label="2">2 Rueckhand</button>
          <button data-label="3">3 Kein Schlag / Other</button>
          <button id="deleteNearest" class="red">Naechstes Label loeschen</button>
        </div>
      </div>
      <div class="panel video-panel">
        <video id="video" src="/video" controls preload="metadata"></video>
      </div>
      <div class="panel chart-wrap">
        <canvas id="chart"></canvas>
      </div>
    </section>
    <aside>
      <div class="panel side-section">
        <h2>Bedienung</h2>
        <div class="hint">
          Space spielt/pausiert. Pfeil links/rechts springt 1 Frame. Tasten 1, 2, 3 speichern ein Label an der aktuellen Videoposition.
          Der Sensor-Zeitpunkt wird mit <code>CSV = Video + Offset</code> berechnet.
        </div>
      </div>
      <div class="panel side-section">
        <h2>Peak-Vorschlaege</h2>
        <div id="peaks" class="list"></div>
      </div>
      <div class="panel side-section">
        <h2>Gespeicherte Labels</h2>
        <div id="events" class="list"></div>
      </div>
    </aside>
  </main>
  <script>
    const labelNames = {labels_json};
    const video = document.getElementById('video');
    const canvas = document.getElementById('chart');
    const ctx = canvas.getContext('2d');
    const offsetInput = document.getElementById('offset');
    const position = document.getElementById('position');
    let sensor = [];
    let peaks = [];
    let events = [];
    let windowSeconds = 18;
    let maxAcc = 1;
    let maxGyro = 1;

    function offsetSeconds() {{
      return Number(offsetInput.value) || 0;
    }}

    function csvTime(videoTime) {{
      return videoTime + offsetSeconds();
    }}

    function resizeCanvas() {{
      const rect = canvas.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      canvas.width = Math.floor(rect.width * dpr);
      canvas.height = Math.floor(rect.height * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      drawChart();
    }}

    function timeToX(t, start, end, width) {{
      return ((t - start) / (end - start)) * width;
    }}

    function drawChart() {{
      const rect = canvas.getBoundingClientRect();
      const width = rect.width;
      const height = rect.height;
      ctx.clearRect(0, 0, width, height);
      ctx.fillStyle = '#ffffff';
      ctx.fillRect(0, 0, width, height);

      const current = video.currentTime || 0;
      const start = Math.max(0, current - windowSeconds / 2);
      const end = start + windowSeconds;
      const padTop = 18;
      const padBottom = 28;
      const plotH = height - padTop - padBottom;

      ctx.strokeStyle = '#edf0f4';
      ctx.lineWidth = 1;
      for (let i = 0; i <= 6; i++) {{
        const y = padTop + (plotH * i) / 6;
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(width, y);
        ctx.stroke();
      }}

      function drawLine(key, color, maxValue) {{
        ctx.strokeStyle = color;
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        let hasPoint = false;
        for (const point of sensor) {{
          const t = point.video_t;
          if (t < start || t > end) continue;
          const x = timeToX(t, start, end, width);
          const value = Math.min(point[key] / maxValue, 1);
          const y = padTop + plotH - value * plotH;
          if (!hasPoint) {{
            ctx.moveTo(x, y);
            hasPoint = true;
          }} else {{
            ctx.lineTo(x, y);
          }}
        }}
        ctx.stroke();
      }}

      drawLine('acc', '#1d74d8', maxAcc);
      drawLine('gyro', '#d97706', maxGyro);

      ctx.fillStyle = '#145ea9';
      for (const peak of peaks) {{
        if (peak.video_t < start || peak.video_t > end) continue;
        const x = timeToX(peak.video_t, start, end, width);
        ctx.fillRect(x - 1, padTop, 2, plotH);
      }}

      for (const event of events) {{
        const t = Number(event.video_time_s);
        if (t < start || t > end) continue;
        const x = timeToX(t, start, end, width);
        ctx.fillStyle = event.label === '3' ? '#657385' : '#157f4f';
        ctx.fillRect(x - 2, padTop, 4, plotH);
      }}

      const xNow = timeToX(current, start, end, width);
      ctx.strokeStyle = '#bf3a35';
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(xNow, padTop);
      ctx.lineTo(xNow, height - padBottom);
      ctx.stroke();

      ctx.fillStyle = '#657385';
      ctx.font = '12px -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif';
      ctx.fillText('acc', 10, 16);
      ctx.fillStyle = '#d97706';
      ctx.fillText('gyro', 45, 16);
      ctx.fillStyle = '#657385';
      ctx.fillText(`${{start.toFixed(1)}}s`, 8, height - 8);
      ctx.fillText(`${{end.toFixed(1)}}s`, width - 54, height - 8);
    }}

    async function loadData() {{
      const sensorRes = await fetch('/sensor.json');
      const data = await sensorRes.json();
      sensor = data.points;
      peaks = data.peaks;
      maxAcc = Math.max(...sensor.map(p => p.acc), 1);
      maxGyro = Math.max(...sensor.map(p => p.gyro), 1);

      const eventsRes = await fetch('/labels');
      events = await eventsRes.json();
      renderPeaks();
      renderEvents();
      resizeCanvas();
    }}

    function renderPeaks() {{
      const container = document.getElementById('peaks');
      container.innerHTML = '';
      for (const peak of peaks) {{
        const row = document.createElement('div');
        row.className = 'row';
        row.innerHTML = `<span class="time">${{peak.video_t.toFixed(2)}}s</span><span>Score ${{peak.score.toFixed(2)}}</span>`;
        const button = document.createElement('button');
        button.textContent = 'Go';
        button.addEventListener('click', () => seek(peak.video_t));
        row.appendChild(button);
        container.appendChild(row);
      }}
    }}

    function renderEvents() {{
      const container = document.getElementById('events');
      container.innerHTML = '';
      for (const event of events) {{
        const row = document.createElement('div');
        row.className = 'row';
        row.innerHTML = `<span class="time">${{Number(event.video_time_s).toFixed(2)}}s</span><span><span class="badge">${{event.label}}</span> ${{event.label_name}}</span>`;
        const button = document.createElement('button');
        button.textContent = 'Go';
        button.addEventListener('click', () => seek(Number(event.video_time_s)));
        row.appendChild(button);
        container.appendChild(row);
      }}
    }}

    function seek(t) {{
      video.currentTime = Math.max(0, t);
      drawChart();
    }}

    function nearestPeak(direction) {{
      const current = video.currentTime || 0;
      if (direction > 0) {{
        return peaks.find(p => p.video_t > current + 0.08) || peaks[peaks.length - 1];
      }}
      for (let i = peaks.length - 1; i >= 0; i--) {{
        if (peaks[i].video_t < current - 0.08) return peaks[i];
      }}
      return peaks[0];
    }}

    async function addLabel(label) {{
      const videoTime = video.currentTime || 0;
      const payload = {{
        video_time_s: videoTime.toFixed(3),
        csv_time_s: csvTime(videoTime).toFixed(3),
        label,
        label_name: labelNames[label],
        note: ''
      }};
      const res = await fetch('/labels', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify(payload)
      }});
      events = await res.json();
      renderEvents();
      drawChart();
    }}

    async function deleteNearest() {{
      if (!events.length) return;
      const current = video.currentTime || 0;
      const nearest = events.reduce((best, event) => {{
        const distance = Math.abs(Number(event.video_time_s) - current);
        return distance < best.distance ? {{event, distance}} : best;
      }}, {{event: events[0], distance: Infinity}});
      const res = await fetch('/labels/delete', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{video_time_s: nearest.event.video_time_s}})
      }});
      events = await res.json();
      renderEvents();
      drawChart();
    }}

    function updatePosition() {{
      const vt = video.currentTime || 0;
      position.textContent = `Video ${{vt.toFixed(3)}}s | CSV ${{csvTime(vt).toFixed(3)}}s`;
      drawChart();
    }}

    document.querySelectorAll('[data-label]').forEach(button => {{
      button.addEventListener('click', () => addLabel(button.dataset.label));
    }});
    document.getElementById('nextPeak').addEventListener('click', () => seek(nearestPeak(1).video_t));
    document.getElementById('prevPeak').addEventListener('click', () => seek(nearestPeak(-1).video_t));
    document.getElementById('plusFrame').addEventListener('click', () => seek((video.currentTime || 0) + 1 / 30));
    document.getElementById('minusFrame').addEventListener('click', () => seek((video.currentTime || 0) - 1 / 30));
    document.getElementById('deleteNearest').addEventListener('click', deleteNearest);
    offsetInput.addEventListener('input', updatePosition);
    video.addEventListener('timeupdate', updatePosition);
    video.addEventListener('seeked', updatePosition);
    window.addEventListener('resize', resizeCanvas);
    canvas.addEventListener('click', (event) => {{
      const rect = canvas.getBoundingClientRect();
      const current = video.currentTime || 0;
      const start = Math.max(0, current - windowSeconds / 2);
      const clicked = start + (event.clientX - rect.left) / rect.width * windowSeconds;
      seek(clicked);
    }});
    document.addEventListener('keydown', (event) => {{
      if (event.target.tagName === 'INPUT') return;
      if (event.key === ' ') {{
        event.preventDefault();
        video.paused ? video.play() : video.pause();
      }} else if (event.key === 'ArrowRight') {{
        seek((video.currentTime || 0) + 1 / 30);
      }} else if (event.key === 'ArrowLeft') {{
        seek((video.currentTime || 0) - 1 / 30);
      }} else if (['1', '2', '3'].includes(event.key)) {{
        addLabel(event.key);
      }} else if (event.key.toLowerCase() === 'n') {{
        seek(nearestPeak(1).video_t);
      }} else if (event.key.toLowerCase() === 'p') {{
        seek(nearestPeak(-1).video_t);
      }}
    }});

    loadData();
  </script>
</body>
</html>"""


class LabelHandler(BaseHTTPRequestHandler):
    config: AppConfig
    points: list[dict]
    peaks: list[dict]

    def do_HEAD(self) -> None:
        route = urlparse(self.path).path
        if route == "/video":
            self.send_file(self.config.video_path, head_only=True)
        elif route in {"/", "/sensor.json", "/labels"}:
            self.send_response(HTTPStatus.OK)
            self.end_headers()
        else:
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_GET(self) -> None:
        route = urlparse(self.path).path
        if route == "/":
            self.send_text(app_html(self.config), "text/html; charset=utf-8")
        elif route == "/sensor.json":
            self.send_json({"points": self.points, "peaks": self.peaks})
        elif route == "/labels":
            self.send_json(read_events(self.config.output_path))
        elif route == "/video":
            self.send_file(self.config.video_path)
        elif route == "/favicon.ico":
            self.send_response(HTTPStatus.NO_CONTENT)
            self.end_headers()
        else:
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self) -> None:
        route = urlparse(self.path).path
        body = self.read_json_body()
        events = read_events(self.config.output_path)

        if route == "/labels":
            label = str(body.get("label", ""))
            if label not in LABELS:
                self.send_error(HTTPStatus.BAD_REQUEST, "Unknown label")
                return
            event = {
                "video_time_s": f"{parse_float(str(body.get('video_time_s', '0'))):.3f}",
                "csv_time_s": f"{parse_float(str(body.get('csv_time_s', '0'))):.3f}",
                "label": label,
                "label_name": LABELS[label],
                "note": str(body.get("note", "")),
            }
            events = [item for item in events if abs(parse_float(item["video_time_s"]) - parse_float(event["video_time_s"])) > 0.08]
            events.append(event)
            write_events(self.config.output_path, events)
            self.send_json(read_events(self.config.output_path))
        elif route == "/labels/delete":
            target = parse_float(str(body.get("video_time_s", "0")))
            events = [item for item in events if abs(parse_float(item["video_time_s"]) - target) > 0.001]
            write_events(self.config.output_path, events)
            self.send_json(read_events(self.config.output_path))
        else:
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def send_text(self, text: str, content_type: str) -> None:
        body = text.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, payload: object) -> None:
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path: Path, head_only: bool = False) -> None:
        file_size = path.stat().st_size
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        range_header = self.headers.get("Range")

        start = 0
        end = file_size - 1
        status = HTTPStatus.OK

        if range_header:
            units, _, value = range_header.partition("=")
            if units == "bytes":
                start_s, _, end_s = value.partition("-")
                start = int(start_s) if start_s else 0
                end = int(end_s) if end_s else file_size - 1
                end = min(end, file_size - 1)
                status = HTTPStatus.PARTIAL_CONTENT

        length = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if status == HTTPStatus.PARTIAL_CONTENT:
            self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
        self.end_headers()

        if not head_only:
            with path.open("rb") as handle:
                handle.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = handle.read(min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    try:
                        self.wfile.write(chunk)
                    except (BrokenPipeError, ConnectionResetError):
                        break
                    remaining -= len(chunk)

    def log_message(self, format: str, *args: object) -> None:
        print(f"{self.address_string()} - {format % args}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Offline video/sensor labeler for tennis strokes.")
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV, help="Apple Watch SensorLog CSV path.")
    parser.add_argument("--video", type=Path, default=DEFAULT_VIDEO, help="Video file path.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Event label CSV output path.")
    parser.add_argument("--offset", type=float, default=DEFAULT_OFFSET_SECONDS, help="Seconds: csv_time = video_time + offset.")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind.")
    parser.add_argument("--port", type=int, default=8765, help="Port to bind.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = AppConfig(
        csv_path=args.csv.expanduser().resolve(),
        video_path=args.video.expanduser().resolve(),
        output_path=args.output.expanduser(),
        offset_seconds=args.offset,
    )

    if not config.csv_path.exists():
        raise SystemExit(f"CSV not found: {config.csv_path}")
    if not config.video_path.exists():
        raise SystemExit(f"Video not found: {config.video_path}")

    print(f"Loading sensor data from {config.csv_path}")
    points, peaks = read_sensor_rows(config.csv_path, config.offset_seconds)
    print(f"Loaded {len(points)} chart points and {len(peaks)} peak candidates")

    handler = LabelHandler
    handler.config = config
    handler.points = points
    handler.peaks = peaks

    server = ThreadingHTTPServer((args.host, args.port), handler)
    url = f"http://{args.host}:{args.port}"
    print(f"Open {url}")
    print(f"Labels will be written to {config.output_path}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
