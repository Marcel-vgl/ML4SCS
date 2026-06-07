#!/usr/bin/env python3
"""Local dashboard for running tennis stroke predictions.

Run from the repository root:

    .venv_vr/bin/python tools/prediction_dashboard.py

Then open http://127.0.0.1:8770 in a browser.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import subprocess
import sys
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from stroke_model import load_sensor_table, offline_labeler_peaks

MODEL_DIR = REPO_ROOT / "models"
UPLOAD_DIR = REPO_ROOT / "uploads"
IMU_COLUMNS = [
    "motionUserAccelerationX(G)",
    "motionUserAccelerationY(G)",
    "motionUserAccelerationZ(G)",
    "motionRotationRateX(rad/s)",
    "motionRotationRateY(rad/s)",
    "motionRotationRateZ(rad/s)",
]


def parse_float(value: str | None) -> float:
    try:
        return float(value) if value not in (None, "") else 0.0
    except ValueError:
        return 0.0


def resolve_existing_csv(value: str) -> Path:
    if not value.strip():
        raise ValueError("No CSV file selected")
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = REPO_ROOT / path
    path = path.resolve()
    if not path.exists() or not path.is_file():
        raise ValueError(f"{path} does not exist")
    if path.suffix.lower() != ".csv":
        raise ValueError(f"{path} is not a CSV file")
    return path


def downsample_rows(rows: list[dict], target_points: int = 3000) -> list[dict]:
    if len(rows) <= target_points:
        return rows

    bucket_size = math.ceil(len(rows) / target_points)
    points: list[dict] = []
    for start in range(0, len(rows), bucket_size):
        bucket = rows[start : start + bucket_size]
        strongest = max(bucket, key=lambda item: item["score"])
        points.append(strongest)
    return points


def detect_peaks(rows: list[dict], limit: int = 180, min_spacing_s: float = 0.45) -> list[dict]:
    selected: list[dict] = []
    for row in sorted(rows, key=lambda item: item["score"], reverse=True):
        if all(abs(row["csv_time_s"] - peak["csv_time_s"]) >= min_spacing_s for peak in selected):
            selected.append(row)
        if len(selected) >= limit:
            break
    return sorted(selected, key=lambda item: item["csv_time_s"])


def sensor_payload(csv_path: Path) -> dict:
    rows: list[dict] = []
    with csv_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"{csv_path.name} has no CSV header")
        missing = [column for column in IMU_COLUMNS if column not in reader.fieldnames]
        if missing:
            raise ValueError(f"{csv_path.name} is missing sensor columns: {', '.join(missing)}")

        first_motion_time: float | None = None
        first_logging_time: datetime | None = None
        for row in reader:
            if "motionTimestamp_sinceReboot(s)" in row and row.get("motionTimestamp_sinceReboot(s)"):
                motion_time = parse_float(row.get("motionTimestamp_sinceReboot(s)"))
                if first_motion_time is None:
                    first_motion_time = motion_time
                csv_time = motion_time - first_motion_time
            elif row.get("loggingTime(txt)"):
                try:
                    logging_time = datetime.fromisoformat(str(row["loggingTime(txt)"]))
                except ValueError:
                    continue
                if first_logging_time is None:
                    first_logging_time = logging_time
                csv_time = (logging_time - first_logging_time).total_seconds()
            else:
                continue

            acc_x, acc_y, acc_z, gyro_x, gyro_y, gyro_z = [
                parse_float(row.get(column)) for column in IMU_COLUMNS
            ]
            acc = math.sqrt(acc_x * acc_x + acc_y * acc_y + acc_z * acc_z)
            gyro = math.sqrt(gyro_x * gyro_x + gyro_y * gyro_y + gyro_z * gyro_z)
            rows.append(
                {
                    "csv_time_s": round(csv_time, 4),
                    "acc": round(acc, 5),
                    "gyro": round(gyro, 5),
                    "score": round(acc + 0.12 * gyro, 5),
                }
            )

    if not rows:
        raise ValueError(f"{csv_path.name} contains no readable sensor rows")

    return {
        "csv_name": csv_path.name,
        "duration": round(rows[-1]["csv_time_s"], 3),
        "row_count": len(rows),
        "points": downsample_rows(rows),
        "peaks": offline_labeler_peaks(load_sensor_table(csv_path)),
    }


def format_cell(value: str) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return value
    return f"{number:.4f}".rstrip("0").rstrip(".")


def prediction_payload(output_path: Path) -> dict:
    with output_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        columns = reader.fieldnames or []
        rows = [
            {column: format_cell(row.get(column, "")) for column in columns}
            for row in reader
        ]

    prediction_counts: dict[str, int] = {}
    for row in rows:
        prediction = row.get("prediction", "")
        if prediction:
            prediction_counts[prediction] = prediction_counts.get(prediction, 0) + 1

    return {
        "rows": rows,
        "columns": columns,
        "count": len(rows),
        "output_path": str(output_path.relative_to(REPO_ROOT)),
        "prediction_counts": prediction_counts,
    }


def save_uploaded_csv(content_type: str, body: bytes) -> Path:
    match = re.search(r"boundary=([^;]+)", content_type)
    if not match:
        raise ValueError("Upload boundary missing")

    boundary = match.group(1).strip().strip('"').encode("utf-8")
    for part in body.split(b"--" + boundary):
        if b"filename=" not in part:
            continue
        header_bytes, separator, file_bytes = part.partition(b"\r\n\r\n")
        if not separator:
            continue
        headers = header_bytes.decode("utf-8", errors="replace")
        filename_match = re.search(r'filename="([^"]+)"', headers)
        if not filename_match:
            continue
        original_name = Path(filename_match.group(1)).name
        if not original_name.lower().endswith(".csv"):
            raise ValueError("Only CSV uploads are supported")
        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", original_name)
        target = UPLOAD_DIR / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{safe_name}"
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        target.write_bytes(file_bytes.rstrip(b"\r\n"))
        return target

    raise ValueError("No CSV file found in upload")


def run_prediction(payload: dict) -> dict:
    csv_path = resolve_existing_csv(str(payload.get("csv_path", "")))
    mode = str(payload.get("mode", "labels"))
    threshold = float(payload.get("threshold", 0.8))
    step = float(payload.get("step", 0.2))
    min_gap = float(payload.get("min_gap", 0.8))
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if mode == "labels":
        events_path = resolve_existing_csv(str(payload.get("events_csv", "")))
        mode_name = "labels"
        command = [
            sys.executable,
            str(SRC_DIR / "predict.py"),
            str(csv_path),
            "--events-csv",
            str(events_path),
        ]
    elif mode == "scan":
        mode_name = "scan"
        command = [
            sys.executable,
            str(SRC_DIR / "predict.py"),
            str(csv_path),
            "--scan",
            "--threshold",
            str(threshold),
            "--step",
            str(step),
            "--min-gap",
            str(min_gap),
        ]
    else:
        raise ValueError("mode must be labels or scan")

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    output_path = MODEL_DIR / f"{csv_path.stem}_{mode_name}_predictions_{timestamp}.csv"
    command.extend(["--out", str(output_path)])
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise ValueError(detail or "Prediction process failed")

    result = prediction_payload(output_path)
    result["mode"] = mode_name
    result["csv_name"] = csv_path.name
    return result


def app_html() -> str:
    return """<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Tennis Prediction Dashboard</title>
  <style>
    :root {
      --bg: #f4f6f8;
      --panel: #ffffff;
      --line: #cfd6df;
      --text: #17202a;
      --muted: #607082;
      --accent: #1769aa;
      --accent-strong: #0f4f83;
      --green: #157f4f;
      --red: #b63d3d;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      font-size: 14px;
    }
    header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 12px 18px;
      background: #253244;
      color: white;
      border-bottom: 1px solid #1b2634;
    }
    h1 {
      margin: 0;
      font-size: 18px;
      font-weight: 650;
    }
    main {
      display: grid;
      grid-template-columns: 360px minmax(0, 1fr);
      gap: 14px;
      padding: 14px;
    }
    aside, section {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
    }
    aside {
      padding: 14px;
      align-self: start;
    }
    section {
      min-width: 0;
      overflow: hidden;
    }
    h2 {
      margin: 0 0 12px;
      font-size: 14px;
      font-weight: 650;
    }
    label {
      display: block;
      margin: 12px 0 5px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 650;
    }
    select, input {
      width: 100%;
      min-height: 34px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: white;
      color: var(--text);
      padding: 6px 8px;
      font: inherit;
    }
    .path-row {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 8px;
      align-items: center;
      margin-top: 6px;
    }
    .pick {
      border: 1px solid var(--line);
      border-radius: 6px;
      min-height: 34px;
      padding: 0 10px;
      background: #eef2f6;
      color: var(--text);
      font: inherit;
      cursor: pointer;
      white-space: nowrap;
    }
    .mode {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
      margin: 6px 0 8px;
    }
    .mode button, .run {
      border: 1px solid var(--line);
      border-radius: 6px;
      min-height: 36px;
      background: #eef2f6;
      color: var(--text);
      font: inherit;
      cursor: pointer;
    }
    .mode button.active {
      background: var(--accent);
      border-color: var(--accent);
      color: white;
    }
    .run {
      width: 100%;
      margin-top: 14px;
      background: var(--green);
      border-color: var(--green);
      color: white;
      font-weight: 650;
    }
    .run:disabled {
      opacity: 0.55;
      cursor: default;
    }
    .scan-grid {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 8px;
    }
    .hidden { display: none; }
    .status {
      margin-top: 12px;
      min-height: 20px;
      color: var(--muted);
      line-height: 1.35;
    }
    .status.error { color: var(--red); }
    .summary {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      padding: 12px;
      border-bottom: 1px solid var(--line);
      background: #f9fafb;
    }
    .pill {
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 5px 9px;
      background: white;
      color: var(--muted);
      font-size: 12px;
    }
    .chart-panel {
      padding: 12px;
      border-bottom: 1px solid var(--line);
    }
    .chart-head {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 8px;
      color: var(--muted);
      font-size: 12px;
    }
    #sensorCanvas {
      display: block;
      width: 100%;
      height: 260px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fbfcfe;
    }
    .legend {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 8px;
      color: var(--muted);
      font-size: 12px;
    }
    .legend span::before {
      content: "";
      display: inline-block;
      width: 10px;
      height: 3px;
      margin-right: 5px;
      vertical-align: middle;
      background: currentColor;
    }
    .table-wrap {
      overflow: auto;
      max-height: calc(100vh - 125px);
    }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
      white-space: nowrap;
    }
    th, td {
      padding: 7px 9px;
      border-bottom: 1px solid #e5e9ee;
      text-align: left;
    }
    th {
      position: sticky;
      top: 0;
      background: #eef2f6;
      z-index: 1;
      font-size: 12px;
      color: #3d4b5c;
    }
    tr:hover td { background: #f8fbff; }
    .empty {
      padding: 24px;
      color: var(--muted);
    }
    @media (max-width: 900px) {
      main { grid-template-columns: 1fr; }
      .table-wrap { max-height: none; }
    }
  </style>
</head>
<body>
  <header>
    <h1>Tennis Prediction Dashboard</h1>
    <div id="modelState">Model: models/v_r_v1.pkl</div>
  </header>
  <main>
    <aside>
      <h2>Prediction</h2>
      <label for="csvUpload">CSV hochladen</label>
      <input id="csvUpload" type="file" accept=".csv,text/csv">

      <div id="scanControls">
        <div class="scan-grid">
          <div>
            <label for="thresholdInput">Threshold</label>
            <input id="thresholdInput" type="number" min="0" max="1" step="0.05" value="0.60">
          </div>
          <div>
            <label for="stepInput">Step s</label>
            <input id="stepInput" type="number" min="0.05" step="0.05" value="0.20">
          </div>
          <div>
            <label for="gapInput">Gap s</label>
            <input id="gapInput" type="number" min="0" step="0.10" value="0.80">
          </div>
        </div>
      </div>

      <button id="runButton" class="run" type="button">Prediction starten</button>
      <div id="status" class="status"></div>
    </aside>

    <section>
      <div id="summary" class="summary">
        <span class="pill">Noch keine Prediction</span>
      </div>
      <div class="chart-panel">
        <div class="chart-head">
          <span id="chartTitle">Keine Sensor-CSV geladen</span>
          <span id="chartMeta"></span>
        </div>
        <canvas id="sensorCanvas"></canvas>
        <div class="legend">
          <span style="color:#1769aa">Score</span>
          <span style="color:#9aa7b5">Peaks</span>
          <span style="color:#157f4f">Predictions</span>
        </div>
      </div>
      <div class="table-wrap">
        <div id="empty" class="empty">Lade eine CSV hoch und starte eine Prediction.</div>
        <table id="resultTable" class="hidden">
          <thead></thead>
          <tbody></tbody>
        </table>
      </div>
    </section>
  </main>

  <script>
    const csvUpload = document.getElementById('csvUpload');
    const runButton = document.getElementById('runButton');
    const statusEl = document.getElementById('status');
    const summaryEl = document.getElementById('summary');
    const table = document.getElementById('resultTable');
    const empty = document.getElementById('empty');
    const canvas = document.getElementById('sensorCanvas');
    const chartTitle = document.getElementById('chartTitle');
    const chartMeta = document.getElementById('chartMeta');
    const ctx = canvas.getContext('2d');
    let uploadedCsvPath = '';
    let sensorData = null;
    let predictionRows = [];

    function setStatus(text, isError = false) {
      statusEl.textContent = text;
      statusEl.classList.toggle('error', isError);
    }

    function resizeCanvas() {
      const rect = canvas.getBoundingClientRect();
      const scale = window.devicePixelRatio || 1;
      canvas.width = Math.max(1, Math.floor(rect.width * scale));
      canvas.height = Math.max(1, Math.floor(rect.height * scale));
      ctx.setTransform(scale, 0, 0, scale, 0, 0);
      drawChart();
    }

    async function uploadCsv() {
      if (!csvUpload.files || !csvUpload.files.length) return;
      setStatus('CSV wird hochgeladen...');
      const form = new FormData();
      form.append('file', csvUpload.files[0]);
      try {
        const res = await fetch('/api/upload-csv', { method: 'POST', body: form });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Upload fehlgeschlagen');
        uploadedCsvPath = data.path;
        setStatus(`Hochgeladen: ${data.name}`);
        await loadSensor();
        await runPrediction();
      } catch (error) {
        setStatus(error.message, true);
      }
    }

    async function loadSensor() {
      if (!uploadedCsvPath) return;
      setStatus('Sensor-Peaks werden geladen...');
      predictionRows = [];
      try {
        const res = await fetch('/api/sensor', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ csv_path: uploadedCsvPath }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Sensor-CSV konnte nicht geladen werden');
        sensorData = data;
        chartTitle.textContent = data.csv_name;
        chartMeta.textContent = `${data.row_count} rows, ${data.duration}s, ${data.peaks.length} peaks`;
        drawChart();
        setStatus('Sensor-Peaks geladen.');
      } catch (error) {
        sensorData = null;
        chartTitle.textContent = 'Keine Sensor-CSV geladen';
        chartMeta.textContent = '';
        drawChart();
        setStatus(error.message, true);
      }
    }

    function predictionColor(label) {
      if (label === 'Vorhand') return '#157f4f';
      if (label === 'Rueckhand') return '#1769aa';
      if (label === 'Slice Vorhand') return '#b56b00';
      if (label === 'Slice Rueckhand') return '#7f4bb2';
      return '#253244';
    }

    function drawChart() {
      const width = canvas.clientWidth;
      const height = canvas.clientHeight;
      ctx.clearRect(0, 0, width, height);
      ctx.fillStyle = '#fbfcfe';
      ctx.fillRect(0, 0, width, height);
      if (!sensorData || !sensorData.points.length) {
        ctx.fillStyle = '#607082';
        ctx.font = '13px -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif';
        ctx.fillText('Lade eine Apple-Watch-CSV hoch.', 14, 28);
        return;
      }

      const pad = { left: 42, right: 18, top: 18, bottom: 30 };
      const plotW = width - pad.left - pad.right;
      const plotH = height - pad.top - pad.bottom;
      const duration = Math.max(0.001, Number(sensorData.duration));
      const maxScore = Math.max(...sensorData.points.map(p => Number(p.score)), 0.001);
      const xForTime = time => pad.left + (Number(time) / duration) * plotW;
      const yForScore = score => pad.top + plotH - (Number(score) / maxScore) * plotH;

      ctx.strokeStyle = '#d7dce3';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(pad.left, pad.top);
      ctx.lineTo(pad.left, pad.top + plotH);
      ctx.lineTo(pad.left + plotW, pad.top + plotH);
      ctx.stroke();

      ctx.strokeStyle = '#e7ebf0';
      ctx.fillStyle = '#607082';
      ctx.font = '11px -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif';
      for (let i = 0; i <= 4; i += 1) {
        const x = pad.left + plotW * i / 4;
        const t = duration * i / 4;
        ctx.beginPath();
        ctx.moveTo(x, pad.top);
        ctx.lineTo(x, pad.top + plotH);
        ctx.stroke();
        ctx.fillText(`${t.toFixed(1)}s`, x - 10, height - 10);
      }

      ctx.strokeStyle = '#1769aa';
      ctx.lineWidth = 1.6;
      ctx.beginPath();
      sensorData.points.forEach((point, index) => {
        const x = xForTime(point.csv_time_s);
        const y = yForScore(point.score);
        if (index === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.stroke();

      ctx.strokeStyle = 'rgba(96,112,130,0.28)';
      ctx.lineWidth = 1;
      sensorData.peaks.forEach(peak => {
        const x = xForTime(peak.csv_time_s);
        ctx.beginPath();
        ctx.moveTo(x, pad.top);
        ctx.lineTo(x, pad.top + plotH);
        ctx.stroke();
      });

      let lastLabelX = -1000;
      predictionRows.forEach(row => {
        const time = Number(row.csv_time_s);
        if (!Number.isFinite(time)) return;
        const x = xForTime(time);
        const color = predictionColor(row.prediction);
        ctx.strokeStyle = color;
        ctx.fillStyle = color;
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(x, pad.top);
        ctx.lineTo(x, pad.top + plotH);
        ctx.stroke();
        ctx.beginPath();
        ctx.arc(x, pad.top + 12, 4, 0, Math.PI * 2);
        ctx.fill();
        if (x - lastLabelX >= 44) {
          ctx.save();
          ctx.translate(x + 5, pad.top + 15);
          ctx.rotate(-Math.PI / 5);
          ctx.font = '11px -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif';
          ctx.fillText(`${row.prediction || '?'} ${row.confidence || ''}`, 0, 0);
          ctx.restore();
          lastLabelX = x;
        }
      });
    }

    function renderSummary(data) {
      summaryEl.innerHTML = '';
      const items = [
        `${data.count} Predictions`,
        `Modus: ${data.mode}`,
        `CSV: ${data.csv_name}`,
        `Output: ${data.output_path}`,
      ];
      Object.entries(data.prediction_counts || {}).forEach(([name, count]) => {
        items.push(`${name}: ${count}`);
      });
      items.forEach(text => {
        const span = document.createElement('span');
        span.className = 'pill';
        span.textContent = text;
        summaryEl.appendChild(span);
      });
    }

    function renderTable(data) {
      const thead = table.querySelector('thead');
      const tbody = table.querySelector('tbody');
      thead.innerHTML = '';
      tbody.innerHTML = '';
      if (!data.rows.length) {
        table.classList.add('hidden');
        empty.classList.remove('hidden');
        empty.textContent = 'Keine Predictions fuer diese Einstellungen.';
        return;
      }
      empty.classList.add('hidden');
      table.classList.remove('hidden');

      const headRow = document.createElement('tr');
      data.columns.forEach(column => {
        const th = document.createElement('th');
        th.textContent = column;
        headRow.appendChild(th);
      });
      thead.appendChild(headRow);

      data.rows.forEach(row => {
        const tr = document.createElement('tr');
        data.columns.forEach(column => {
          const td = document.createElement('td');
          td.textContent = row[column] ?? '';
          tr.appendChild(td);
        });
        tbody.appendChild(tr);
      });
    }

    async function runPrediction() {
      if (!uploadedCsvPath) {
        setStatus('Bitte zuerst eine CSV hochladen.', true);
        return;
      }
      runButton.disabled = true;
      setStatus('Prediction laeuft...');
      try {
        const payload = {
          csv_path: uploadedCsvPath,
          mode: 'scan',
          threshold: Number(document.getElementById('thresholdInput').value),
          step: Number(document.getElementById('stepInput').value),
          min_gap: Number(document.getElementById('gapInput').value),
        };
        const res = await fetch('/api/predict', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Prediction fehlgeschlagen');
        predictionRows = data.rows || [];
        renderSummary(data);
        renderTable(data);
        drawChart();
        setStatus(`Fertig. Ergebnis gespeichert: ${data.output_path}`);
      } catch (error) {
        setStatus(error.message, true);
      } finally {
        runButton.disabled = false;
      }
    }

    csvUpload.addEventListener('change', uploadCsv);
    runButton.addEventListener('click', runPrediction);
    window.addEventListener('resize', resizeCanvas);
    resizeCanvas();
  </script>
</body>
</html>
"""


class DashboardHandler(BaseHTTPRequestHandler):
    def send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self) -> None:
        route = urlparse(self.path).path
        if route == "/":
            encoded = app_html().encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
        elif route == "/favicon.ico":
            self.send_response(HTTPStatus.NO_CONTENT)
            self.end_headers()
        else:
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self) -> None:
        route = urlparse(self.path).path
        if route not in {"/api/predict", "/api/sensor", "/api/upload-csv"}:
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            if route == "/api/upload-csv":
                uploaded = save_uploaded_csv(self.headers.get("Content-Type", ""), body)
                self.send_json({"name": uploaded.name, "path": str(uploaded)})
                return

            payload = json.loads(body or b"{}")
            if route == "/api/predict":
                self.send_json(run_prediction(payload))
            else:
                csv_path = resolve_existing_csv(str(payload.get("csv_path", "")))
                self.send_json(sensor_payload(csv_path))
        except Exception as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def log_message(self, format: str, *args: object) -> None:
        sys.stderr.write(f"[dashboard] {format % args}\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Local prediction dashboard.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8770)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    server = HTTPServer((args.host, args.port), DashboardHandler)
    print(f"Prediction dashboard running at http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping prediction dashboard.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
