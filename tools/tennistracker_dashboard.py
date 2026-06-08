#!/usr/bin/env python3
"""TennisTracker live dashboard: receives Apple Watch sensor batches over HTTP and
records them as ML4SCS-compatible CSV files.

Run from the repository root:

    .venv_vr/bin/python tools/tennistracker_dashboard.py

Then open http://127.0.0.1:8788 in a browser. The iPhone bridge POSTs sensor
batches to http://<mac-ip>:8788/api/ingest (same machine, LAN-reachable).

Pure standard library only, matching tools/prediction_dashboard.py. No websockets
or aiohttp dependency: the iPhone pushes via HTTP POST, the browser polls /api/live.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import threading
import time
from collections import deque
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parents[1]
RECORDINGS_DIR = REPO_ROOT / "recordings"

# Optional: das trainierte Schlagmodell für den Predict-Modus laden. Benötigt
# numpy/scikit-learn/joblib (.venv_vr). Ohne Modell läuft das Dashboard nur als
# Empfänger/Recorder.
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

try:
    import numpy as np
    from stroke_model import (
        DEFAULT_MODEL_PATH,
        SensorTable,
        detect_energy_peaks,
        load_model,
        predict_one,
    )

    _MODEL = load_model(DEFAULT_MODEL_PATH)
    _MODEL_ERROR = ""
except Exception as exc:  # noqa: BLE001 - model is optional
    _MODEL = None
    _MODEL_ERROR = str(exc)

# SensorLog Apple Watch CSV columns, kept identical to the 53-column files in
# Daten/fritz_*.csv so recordings load directly in the existing labeler/tools.
CSV_COLUMNS = [
    "loggingTime(txt)",
    "locationTimestamp_since1970(s)",
    "locationLatitude(WGS84)",
    "locationLongitude(WGS84)",
    "locationAltitude(m)",
    "locationSpeed(m/s)",
    "locationSpeedAccuracy(m/s)",
    "locationCourse(°)",
    "locationCourseAccuracy(°)",
    "locationVerticalAccuracy(m)",
    "locationHorizontalAccuracy(m)",
    "locationFloor(Z)",
    "accelerometerTimestamp_sinceReboot(s)",
    "accelerometerAccelerationX(G)",
    "accelerometerAccelerationY(G)",
    "accelerometerAccelerationZ(G)",
    "motionTimestamp_sinceReboot(s)",
    "motionYaw(rad)",
    "motionRoll(rad)",
    "motionPitch(rad)",
    "motionRotationRateX(rad/s)",
    "motionRotationRateY(rad/s)",
    "motionRotationRateZ(rad/s)",
    "motionUserAccelerationX(G)",
    "motionUserAccelerationY(G)",
    "motionUserAccelerationZ(G)",
    "motionAttitudeReferenceFrame(txt)",
    "motionQuaternionX(R)",
    "motionQuaternionY(R)",
    "motionQuaternionZ(R)",
    "motionQuaternionW(R)",
    "motionGravityX(G)",
    "motionGravityY(G)",
    "motionGravityZ(G)",
    "motionMagneticFieldX(µT)",
    "motionMagneticFieldY(µT)",
    "motionMagneticFieldZ(µT)",
    "motionHeading(°)",
    "motionMagneticFieldCalibrationAccuracy(Z)",
    "pedometerStartDate(txt)",
    "pedometerNumberofSteps(N)",
    "pedometerAverageActivePace(s/m)",
    "pedometerCurrentPace(s/m)",
    "pedometerCurrentCadence(steps/s)",
    "pedometerDistance(m)",
    "pedometerFloorAscended(N)",
    "pedometerFloorDescended(N)",
    "pedometerEndDate(txt)",
    "altimeterTimestamp_sinceReboot(s)",
    "altimeterReset(bool)",
    "altimeterRelativeAltitude(m)",
    "altimeterPressure(kPa)",
    "label",
]

# Mapping from the compact stream JSON keys to canonical CSV columns. watch_uptime_s
# fills both reboot-time columns; loggingTime is derived from timestamp_unix_s.
SAMPLE_TO_CSV = {
    "watch_uptime_s": ("motionTimestamp_sinceReboot(s)", "accelerometerTimestamp_sinceReboot(s)"),
    "acc_x_g": ("accelerometerAccelerationX(G)",),
    "acc_y_g": ("accelerometerAccelerationY(G)",),
    "acc_z_g": ("accelerometerAccelerationZ(G)",),
    "user_acc_x_g": ("motionUserAccelerationX(G)",),
    "user_acc_y_g": ("motionUserAccelerationY(G)",),
    "user_acc_z_g": ("motionUserAccelerationZ(G)",),
    "gyro_x_rad_s": ("motionRotationRateX(rad/s)",),
    "gyro_y_rad_s": ("motionRotationRateY(rad/s)",),
    "gyro_z_rad_s": ("motionRotationRateZ(rad/s)",),
    "gravity_x_g": ("motionGravityX(G)",),
    "gravity_y_g": ("motionGravityY(G)",),
    "gravity_z_g": ("motionGravityZ(G)",),
    "roll_rad": ("motionRoll(rad)",),
    "pitch_rad": ("motionPitch(rad)",),
    "yaw_rad": ("motionYaw(rad)",),
    "quat_x": ("motionQuaternionX(R)",),
    "quat_y": ("motionQuaternionY(R)",),
    "quat_z": ("motionQuaternionZ(R)",),
    "quat_w": ("motionQuaternionW(R)",),
}


def sample_to_csv_row(sample: dict) -> dict:
    """Translate a compact stream sample into a full canonical CSV row."""
    row = {column: "0" for column in CSV_COLUMNS}
    row.update(
        {
            "locationSpeed(m/s)": "-1",
            "locationSpeedAccuracy(m/s)": "-1",
            "locationCourse(°)": "-1",
            "locationCourseAccuracy(°)": "-1",
            "locationVerticalAccuracy(m)": "-1",
            "locationHorizontalAccuracy(m)": "-1",
            "locationFloor(Z)": "-9999",
            "motionAttitudeReferenceFrame(txt)": "XArbitraryZVertical",
            "motionHeading(°)": "-1",
            "motionMagneticFieldCalibrationAccuracy(Z)": "-1",
            "pedometerStartDate(txt)": "",
            "pedometerEndDate(txt)": "",
            "label": "0",
        }
    )
    unix_s = sample.get("timestamp_unix_s")
    if isinstance(unix_s, (int, float)):
        iso = datetime.fromtimestamp(float(unix_s), tz=timezone.utc).astimezone()
        row["loggingTime(txt)"] = iso.isoformat()
        row["locationTimestamp_since1970(s)"] = unix_s
    for key, columns in SAMPLE_TO_CSV.items():
        if key not in sample:
            continue
        value = sample[key]
        for column in columns:
            row[column] = value
    return row


class StreamState:
    """Thread-safe live buffer, statistics and optional CSV recorder."""

    def __init__(self, buffer_size: int = 4000) -> None:
        self.lock = threading.Lock()
        self.points: deque[dict] = deque(maxlen=buffer_size)
        self.total_samples = 0
        self.total_batches = 0
        self.gap_count = 0
        self.last_sequence: int | None = None
        self.last_batch_unix: float | None = None
        self.last_latency_ms: float | None = None
        self.session_id: str | None = None
        # recording
        self._csv_handle = None
        self._csv_writer: csv.DictWriter | None = None
        self.recording_path: Path | None = None
        self.recording_rows = 0

    def ingest(self, payload: dict) -> int:
        samples = payload.get("samples") or []
        now = time.time()
        bridge_unix = payload.get("bridge_received_unix_s")
        with self.lock:
            self.total_batches += 1
            self.last_batch_unix = now
            self.session_id = payload.get("session_id") or self.session_id
            if isinstance(bridge_unix, (int, float)):
                self.last_latency_ms = max(0.0, (now - float(bridge_unix)) * 1000.0)
            for sample in samples:
                self._ingest_sample(sample, now)
            if self._csv_writer is not None:
                for sample in samples:
                    self._csv_writer.writerow(sample_to_csv_row(sample))
                    self.recording_rows += 1
                self._csv_handle.flush()
        if ENGINE is not None:
            ENGINE.add(samples)
        return len(samples)

    def _ingest_sample(self, sample: dict, now: float) -> None:
        self.total_samples += 1
        seq = sample.get("sequence")
        if isinstance(seq, int):
            if self.last_sequence is not None and seq > self.last_sequence + 1:
                self.gap_count += seq - self.last_sequence - 1
            self.last_sequence = seq

        def num(key: str) -> float:
            value = sample.get(key, 0.0)
            try:
                return float(value)
            except (TypeError, ValueError):
                return 0.0

        acc = math.sqrt(num("user_acc_x_g") ** 2 + num("user_acc_y_g") ** 2 + num("user_acc_z_g") ** 2)
        gyro = math.sqrt(num("gyro_x_rad_s") ** 2 + num("gyro_y_rad_s") ** 2 + num("gyro_z_rad_s") ** 2)
        self.points.append(
            {
                "t": num("watch_uptime_s"),
                "recv": now,
                "seq": seq if isinstance(seq, int) else None,
                "acc": round(acc, 5),
                "gyro": round(gyro, 5),
                "score": round(acc + 0.12 * gyro, 5),
            }
        )

    def effective_rate(self, window_s: float = 2.0) -> float:
        now = time.time()
        recent = [p for p in self.points if now - p["recv"] <= window_s]
        if len(recent) < 2:
            return 0.0
        span = recent[-1]["recv"] - recent[0]["recv"]
        return (len(recent) - 1) / span if span > 0 else 0.0

    def snapshot(self, max_points: int = 1200) -> dict:
        with self.lock:
            points = list(self.points)[-max_points:]
            now = time.time()
            connected = self.last_batch_unix is not None and (now - self.last_batch_unix) < 2.0
            return {
                "connected": connected,
                "session_id": self.session_id,
                "total_samples": self.total_samples,
                "total_batches": self.total_batches,
                "gap_count": self.gap_count,
                "rate_hz": round(self.effective_rate(), 1),
                "latency_ms": round(self.last_latency_ms, 1) if self.last_latency_ms is not None else None,
                "seconds_since_batch": round(now - self.last_batch_unix, 2) if self.last_batch_unix else None,
                "recording": self._csv_writer is not None,
                "recording_path": str(self.recording_path.relative_to(REPO_ROOT)) if self.recording_path else None,
                "recording_rows": self.recording_rows,
                "points": [
                    {"t": round(p["t"], 4), "score": p["score"], "acc": p["acc"], "gyro": p["gyro"]}
                    for p in points
                ],
                "prediction": (
                    ENGINE.snapshot()
                    if ENGINE is not None
                    else {"available": False, "error": _MODEL_ERROR}
                ),
            }

    def start_recording(self) -> dict:
        with self.lock:
            if self._csv_writer is not None:
                return {"recording": True, "recording_path": str(self.recording_path.relative_to(REPO_ROOT))}
            RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.recording_path = RECORDINGS_DIR / f"tennistracker_{stamp}.csv"
            self._csv_handle = self.recording_path.open("w", newline="", encoding="utf-8")
            self._csv_writer = csv.DictWriter(self._csv_handle, fieldnames=CSV_COLUMNS)
            self._csv_writer.writeheader()
            self.recording_rows = 0
            return {"recording": True, "recording_path": str(self.recording_path.relative_to(REPO_ROOT))}

    def stop_recording(self) -> dict:
        with self.lock:
            path = self.recording_path
            rows = self.recording_rows
            if self._csv_handle is not None:
                self._csv_handle.flush()
                self._csv_handle.close()
            self._csv_handle = None
            self._csv_writer = None
            self.recording_path = None
            return {
                "recording": False,
                "saved_path": str(path.relative_to(REPO_ROOT)) if path else None,
                "rows": rows,
            }


STATE = StreamState()


def _fnum(sample: dict, key: str) -> float:
    try:
        return float(sample.get(key, 0.0))
    except (TypeError, ValueError):
        return 0.0


class PredictionEngine:
    """Live-Schlagerkennung: hält einen rollierenden Puffer der letzten Sekunden,
    erkennt Peaks und klassifiziert gesetzte Schläge mit dem trainierten Modell."""

    def __init__(self, model_payload: dict, buffer_samples: int = 800) -> None:
        self.model = model_payload
        self.window_after = float(model_payload["window_after_s"])
        self.lock = threading.Lock()
        self.buffer: deque[dict] = deque(maxlen=buffer_samples)
        self.predictions: deque[dict] = deque(maxlen=80)
        self.predicted_abs: list[float] = []

    def add(self, samples: list[dict]) -> None:
        with self.lock:
            for sample in samples:
                self.buffer.append(sample)

    def _build_table(self, samples: list[dict]) -> tuple[SensorTable, float]:
        t0 = _fnum(samples[0], "watch_uptime_s")
        times = np.array([_fnum(s, "watch_uptime_s") - t0 for s in samples], dtype=float)
        ua = np.array([[_fnum(s, "user_acc_x_g"), _fnum(s, "user_acc_y_g"), _fnum(s, "user_acc_z_g")] for s in samples])
        gy = np.array([[_fnum(s, "gyro_x_rad_s"), _fnum(s, "gyro_y_rad_s"), _fnum(s, "gyro_z_rad_s")] for s in samples])
        uam = np.sqrt((ua * ua).sum(axis=1))
        rm = np.sqrt((gy * gy).sum(axis=1))
        score = uam + 0.12 * rm
        values = {
            "accelerometerAccelerationX(G)": np.array([_fnum(s, "acc_x_g") for s in samples]),
            "accelerometerAccelerationY(G)": np.array([_fnum(s, "acc_y_g") for s in samples]),
            "accelerometerAccelerationZ(G)": np.array([_fnum(s, "acc_z_g") for s in samples]),
            "motionUserAccelerationX(G)": ua[:, 0],
            "motionUserAccelerationY(G)": ua[:, 1],
            "motionUserAccelerationZ(G)": ua[:, 2],
            "motionRotationRateX(rad/s)": gy[:, 0],
            "motionRotationRateY(rad/s)": gy[:, 1],
            "motionRotationRateZ(rad/s)": gy[:, 2],
            "motionRoll(rad)": np.array([_fnum(s, "roll_rad") for s in samples]),
            "motionPitch(rad)": np.array([_fnum(s, "pitch_rad") for s in samples]),
            "motionYaw(rad)": np.array([_fnum(s, "yaw_rad") for s in samples]),
            "user_acc_magnitude": uam,
            "rotation_magnitude": rm,
            "score": score,
        }
        peak_rows = [
            {
                "csv_time_s": round(float(times[i]), 4),
                "acc": round(float(uam[i]), 5),
                "gyro": round(float(rm[i]), 5),
                "score": round(float(score[i]), 5),
            }
            for i in range(len(samples))
        ]
        return SensorTable(times=times, values=values, peak_rows=peak_rows), t0

    def run_once(self) -> None:
        with self.lock:
            samples = list(self.buffer)
        if len(samples) < 40:
            return
        table, t0 = self._build_table(samples)
        latest = float(table.times[-1])
        settle = self.window_after + 0.15
        try:
            peaks = detect_energy_peaks(table)
        except Exception:  # noqa: BLE001
            return
        for peak in peaks:
            center = float(peak["csv_time_s"])
            if center > latest - settle:
                continue  # noch nicht genug Daten nach dem Schlag
            abs_t = t0 + center
            if any(abs(abs_t - done) < 0.4 for done in self.predicted_abs):
                continue
            try:
                row = predict_one(self.model, table, center)
            except Exception:  # noqa: BLE001
                continue
            self.predicted_abs.append(abs_t)
            self.predictions.append(
                {
                    "t": round(abs_t, 3),
                    "label": row["prediction"],
                    "confidence": row["confidence"],
                    "recv": time.time(),
                }
            )
        if len(self.predicted_abs) > 300:
            self.predicted_abs = self.predicted_abs[-300:]

    def snapshot(self, limit: int = 12) -> dict:
        with self.lock:
            recent = list(self.predictions)[-limit:]
        return {
            "available": True,
            "classes": list(self.model["classes"]),
            "predictions": list(reversed(recent)),
            "last": recent[-1] if recent else None,
            "total": len(self.predicted_abs),
        }


ENGINE = PredictionEngine(_MODEL) if _MODEL is not None else None


def app_html() -> str:
    return """<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>TennisTracker Live Dashboard</title>
  <style>
    :root { --bg:#f4f6f8; --panel:#fff; --line:#cfd6df; --text:#17202a; --muted:#607082;
      --accent:#1769aa; --green:#157f4f; --red:#b63d3d; }
    * { box-sizing:border-box; }
    body { margin:0; min-height:100vh; background:var(--bg); color:var(--text);
      font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; font-size:14px; }
    header { display:flex; align-items:center; justify-content:space-between; gap:16px;
      padding:12px 18px; background:#253244; color:#fff; }
    h1 { margin:0; font-size:18px; font-weight:650; }
    #conn { font-weight:650; }
    main { display:grid; grid-template-columns:300px minmax(0,1fr); gap:14px; padding:14px; }
    aside, section { background:var(--panel); border:1px solid var(--line); border-radius:8px; }
    aside { padding:14px; align-self:start; }
    section { min-width:0; overflow:hidden; padding:14px; }
    h2 { margin:0 0 12px; font-size:14px; font-weight:650; }
    button { border:1px solid var(--line); border-radius:6px; min-height:38px; width:100%;
      background:#eef2f6; color:var(--text); font:inherit; cursor:pointer; margin-top:8px; font-weight:650; }
    button.rec { background:var(--green); border-color:var(--green); color:#fff; }
    button.stop { background:var(--red); border-color:var(--red); color:#fff; }
    .stats { display:flex; flex-wrap:wrap; gap:8px; margin-bottom:12px; }
    .pill { border:1px solid var(--line); border-radius:999px; padding:5px 10px;
      background:#f9fafb; color:var(--muted); font-size:12px; }
    .pill b { color:var(--text); }
    #plot { display:block; width:100%; height:340px; border:1px solid var(--line);
      border-radius:6px; background:#fbfcfe; }
    .legend { display:flex; gap:14px; margin-top:8px; color:var(--muted); font-size:12px; }
    .legend span::before { content:""; display:inline-block; width:12px; height:3px;
      margin-right:5px; vertical-align:middle; background:currentColor; }
    .recinfo { margin-top:12px; color:var(--muted); font-size:12px; line-height:1.4; word-break:break-all; }
    .connect-guide { margin-top:14px; padding-top:12px; border-top:1px solid var(--line);
      color:var(--muted); font-size:12px; line-height:1.45; }
    .connect-guide h2 { margin:0 0 10px; color:var(--text); }
    .connect-guide ol { margin:0; padding-left:18px; }
    .connect-guide li + li { margin-top:6px; }
    .connect-guide code { display:inline-block; max-width:100%; padding:1px 4px;
      border:1px solid #dce2e8; border-radius:4px; background:#f7f9fb; color:#253244;
      overflow-wrap:anywhere; }
    .predict { margin-top:14px; }
    .last-predict { font-size:20px; font-weight:700; padding:12px 14px; border-radius:8px;
      background:#eef6f0; border:1px solid #cfe3d6; color:#157f4f; }
    .predict-list { display:flex; flex-wrap:wrap; gap:6px; margin-top:8px; }
    .predict-list .chip { border:1px solid var(--line); border-radius:999px; padding:4px 9px;
      background:#f9fafb; font-size:12px; color:var(--text); }
    .chip .vh { color:#157f4f; font-weight:700; }
    .chip .rh { color:#1769aa; font-weight:700; }
  </style>
</head>
<body>
  <header>
    <h1>TennisTracker Live Dashboard</h1>
    <div id="conn">…</div>
  </header>
  <main>
    <aside>
      <h2>Recording</h2>
      <button id="startBtn" class="rec" type="button">Recording starten</button>
      <button id="stopBtn" class="stop" type="button">Recording stoppen</button>
      <div id="recinfo" class="recinfo">Keine Aufnahme aktiv.</div>

      <div class="connect-guide">
        <h2>Verbinden</h2>
        <ol>
          <li>Dashboard starten: <code>.venv_vr/bin/python tools/tennistracker_dashboard.py</code></li>
          <li>Auf diesem Mac oeffnen: <code>http://127.0.0.1:8788</code></li>
          <li>iPhone und Mac ins gleiche WLAN bringen.</li>
          <li>In der TennisTracker-Bridge als Ziel setzen: <code>http://&lt;mac-ip&gt;:8788/api/ingest</code></li>
          <li>Die Mac-IP findest du in Systemeinstellungen &gt; Netzwerk. Das Terminal muss offen bleiben.</li>
        </ol>
      </div>
    </aside>
    <section>
      <div class="stats" id="stats"></div>
      <canvas id="plot"></canvas>
      <div class="legend">
        <span style="color:#1769aa">User-Acceleration |a|</span>
        <span style="color:#b56b00">Rotation |ω|</span>
        <span style="color:#157f4f">erkannte Schläge</span>
      </div>
      <div id="predictPanel" class="predict">
        <div id="lastPredict" class="last-predict">Predict-Modus: warte auf Schläge…</div>
        <div id="predictList" class="predict-list"></div>
      </div>
    </section>
  </main>
  <script>
    const plot = document.getElementById('plot');
    const ctx = plot.getContext('2d');
    const statsEl = document.getElementById('stats');
    const connEl = document.getElementById('conn');
    const recinfo = document.getElementById('recinfo');
    let data = null;

    function resize() {
      const r = plot.getBoundingClientRect();
      const s = window.devicePixelRatio || 1;
      plot.width = Math.floor(r.width * s);
      plot.height = Math.floor(r.height * s);
      ctx.setTransform(s, 0, 0, s, 0, 0);
      draw();
    }

    function pill(label, value) { return `<span class="pill">${label}: <b>${value}</b></span>`; }

    function render() {
      if (!data) return;
      connEl.textContent = data.connected ? '● verbunden' : '○ keine Daten';
      connEl.style.color = data.connected ? '#7CFC9B' : '#ffb3b3';
      statsEl.innerHTML = [
        pill('Rate', (data.rate_hz ?? 0) + ' Hz'),
        pill('Samples', data.total_samples),
        pill('Batches', data.total_batches),
        pill('Gaps', data.gap_count),
        pill('Latenz', data.latency_ms != null ? data.latency_ms + ' ms' : '–'),
        pill('Session', data.session_id || '–'),
      ].join('');
      if (data.recording) {
        recinfo.textContent = `Aufnahme läuft → ${data.recording_path} (${data.recording_rows} Zeilen)`;
      } else {
        recinfo.textContent = 'Keine Aufnahme aktiv.';
      }
      renderPredictions();
      draw();
    }

    function chipClass(label) { return label === 'Vorhand' ? 'vh' : 'rh'; }

    function renderPredictions() {
      const pred = (data && data.prediction) || { available: false };
      const lastEl = document.getElementById('lastPredict');
      const listEl = document.getElementById('predictList');
      if (!pred.available) {
        lastEl.textContent = 'Predict-Modus aus (Modell nicht geladen)';
        lastEl.style.color = '#b63d3d';
        listEl.innerHTML = '';
        return;
      }
      if (pred.last) {
        lastEl.style.color = '#157f4f';
        lastEl.innerHTML = `Letzter Schlag: <b>${pred.last.label}</b> · ${Math.round(pred.last.confidence * 100)}%`;
      } else {
        lastEl.style.color = '#157f4f';
        lastEl.textContent = 'Predict-Modus: warte auf Schläge…';
      }
      listEl.innerHTML = (pred.predictions || []).map(p =>
        `<span class="chip"><span class="${chipClass(p.label)}">${p.label}</span> ${Math.round(p.confidence * 100)}%</span>`
      ).join('');
    }

    function draw() {
      const w = plot.clientWidth, h = plot.clientHeight;
      ctx.clearRect(0, 0, w, h);
      ctx.fillStyle = '#fbfcfe'; ctx.fillRect(0, 0, w, h);
      const pts = data && data.points ? data.points : [];
      if (pts.length < 2) {
        ctx.fillStyle = '#607082';
        ctx.font = '13px -apple-system,sans-serif';
        ctx.fillText('Warte auf eingehende Samples…', 16, 28);
        return;
      }
      const pad = { l: 44, r: 16, t: 16, b: 26 };
      const pw = w - pad.l - pad.r, ph = h - pad.t - pad.b;
      const n = pts.length;
      const maxAcc = Math.max(0.2, ...pts.map(p => p.acc));
      const maxGyro = Math.max(0.5, ...pts.map(p => p.gyro));
      const xFor = i => pad.l + (i / (n - 1)) * pw;
      // axes
      ctx.strokeStyle = '#d7dce3'; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(pad.l, pad.t); ctx.lineTo(pad.l, pad.t + ph);
      ctx.lineTo(pad.l + pw, pad.t + ph); ctx.stroke();
      function line(key, max, color) {
        ctx.strokeStyle = color; ctx.lineWidth = 1.6; ctx.beginPath();
        pts.forEach((p, i) => {
          const x = xFor(i), y = pad.t + ph - (p[key] / max) * ph;
          if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        });
        ctx.stroke();
      }
      line('acc', maxAcc, '#1769aa');
      line('gyro', maxGyro, '#b56b00');

      // erkannte Schläge als Marker einzeichnen
      const pred = (data && data.prediction) || {};
      const preds = pred.predictions || [];
      const tmin = pts[0].t, tmax = pts[n - 1].t;
      if (tmax > tmin) {
        preds.forEach(pr => {
          if (pr.t < tmin || pr.t > tmax) return;
          const x = pad.l + ((pr.t - tmin) / (tmax - tmin)) * pw;
          ctx.strokeStyle = '#157f4f';
          ctx.lineWidth = 2;
          ctx.beginPath();
          ctx.moveTo(x, pad.t);
          ctx.lineTo(x, pad.t + ph);
          ctx.stroke();
          ctx.fillStyle = '#157f4f';
          ctx.font = '11px -apple-system, sans-serif';
          ctx.save();
          ctx.translate(x + 3, pad.t + 12);
          ctx.fillText(pr.label === 'Vorhand' ? 'VH' : 'RH', 0, 0);
          ctx.restore();
        });
      }
    }

    async function tick() {
      try {
        const res = await fetch('/api/live');
        data = await res.json();
        render();
      } catch (e) { /* keep last frame */ }
    }

    document.getElementById('startBtn').addEventListener('click', async () => {
      await fetch('/api/record/start', { method: 'POST' }); tick();
    });
    document.getElementById('stopBtn').addEventListener('click', async () => {
      const res = await fetch('/api/record/stop', { method: 'POST' });
      const r = await res.json();
      if (r.saved_path) recinfo.textContent = `Gespeichert: ${r.saved_path} (${r.rows} Zeilen)`;
      tick();
    });
    window.addEventListener('resize', resize);
    resize();
    setInterval(tick, 150);
    tick();
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
        elif route == "/api/live":
            self.send_json(STATE.snapshot())
        elif route == "/favicon.ico":
            self.send_response(HTTPStatus.NO_CONTENT)
            self.end_headers()
        else:
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self) -> None:
        route = urlparse(self.path).path
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length) if length else b""
            if route == "/api/ingest":
                payload = json.loads(body or b"{}")
                import sys as _sys
                _sys.stderr.write(f"[tennistracker] INGEST von {self.client_address[0]} source={payload.get('source')} samples={len(payload.get('samples') or [])}\n")
                received = STATE.ingest(payload)
                self.send_json({"ok": True, "received": received, "recording": STATE.snapshot()["recording"]})
            elif route == "/api/record/start":
                self.send_json(STATE.start_recording())
            elif route == "/api/record/stop":
                self.send_json(STATE.stop_recording())
            else:
                self.send_error(HTTPStatus.NOT_FOUND, "Not found")
        except Exception as exc:  # noqa: BLE001 - surface error to client
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def log_message(self, format: str, *args: object) -> None:
        # Quiet: ingest/poll would otherwise flood the console.
        if "/api/ingest" in (self.path or "") or "/api/live" in (self.path or ""):
            return
        import sys
        sys.stderr.write(f"[tennistracker] {format % args}\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="TennisTracker live dashboard.")
    parser.add_argument("--host", default="0.0.0.0", help="Bind address (0.0.0.0 = LAN-reachable for the iPhone).")
    parser.add_argument("--port", type=int, default=8788)
    return parser.parse_args()


def prediction_loop(interval: float = 0.35) -> None:
    while True:
        try:
            ENGINE.run_once()
        except Exception as exc:  # noqa: BLE001
            sys.stderr.write(f"[tennistracker] prediction error: {exc}\n")
        time.sleep(interval)


def main() -> None:
    args = parse_args()
    server = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    shown = "127.0.0.1" if args.host in ("0.0.0.0", "") else args.host
    print(f"TennisTracker dashboard running at http://{shown}:{args.port}")
    print(f"iPhone bridge should POST batches to http://<mac-ip>:{args.port}/api/ingest")
    if ENGINE is not None:
        print(f"Predict mode active (model: {Path(DEFAULT_MODEL_PATH).name}, classes: {ENGINE.model['classes']})")
        threading.Thread(target=prediction_loop, daemon=True).start()
    else:
        print(f"Predict mode OFF (model not loaded: {_MODEL_ERROR})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping TennisTracker dashboard.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
