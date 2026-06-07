#!/usr/bin/env python3
"""SwingStream live dashboard: receives Apple Watch sensor batches over HTTP and
records them as ML4SCS-compatible CSV files.

Run from the repository root:

    .venv_vr/bin/python tools/swingstream_dashboard.py

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

# Canonical Apple Watch CSV columns, kept identical to the files in uploads/ and
# Daten/ so recordings load directly via src/stroke_model.load_sensor_table().
CSV_COLUMNS = [
    "loggingTime(txt)",
    "motionTimestamp_sinceReboot(s)",
    "accelerometerTimestamp_sinceReboot(s)",
    "accelerometerAccelerationX(G)",
    "accelerometerAccelerationY(G)",
    "accelerometerAccelerationZ(G)",
    "motionUserAccelerationX(G)",
    "motionUserAccelerationY(G)",
    "motionUserAccelerationZ(G)",
    "motionRotationRateX(rad/s)",
    "motionRotationRateY(rad/s)",
    "motionRotationRateZ(rad/s)",
    "motionGravityX(G)",
    "motionGravityY(G)",
    "motionGravityZ(G)",
    "motionRoll(rad)",
    "motionPitch(rad)",
    "motionYaw(rad)",
    "motionQuaternionX(R)",
    "motionQuaternionY(R)",
    "motionQuaternionZ(R)",
    "motionQuaternionW(R)",
    "sequence",
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
    "sequence": ("sequence",),
}


def sample_to_csv_row(sample: dict) -> dict:
    """Translate a compact stream sample into a full canonical CSV row."""
    row = {column: "0.0" for column in CSV_COLUMNS}
    row["label"] = "0"
    unix_s = sample.get("timestamp_unix_s")
    if isinstance(unix_s, (int, float)):
        iso = datetime.fromtimestamp(float(unix_s), tz=timezone.utc).astimezone()
        row["loggingTime(txt)"] = iso.isoformat()
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
            }

    def start_recording(self) -> dict:
        with self.lock:
            if self._csv_writer is not None:
                return {"recording": True, "recording_path": str(self.recording_path.relative_to(REPO_ROOT))}
            RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.recording_path = RECORDINGS_DIR / f"swingstream_{stamp}.csv"
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


def app_html() -> str:
    return """<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SwingStream Live Dashboard</title>
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
  </style>
</head>
<body>
  <header>
    <h1>SwingStream Live Dashboard</h1>
    <div id="conn">…</div>
  </header>
  <main>
    <aside>
      <h2>Recording</h2>
      <button id="startBtn" class="rec" type="button">Recording starten</button>
      <button id="stopBtn" class="stop" type="button">Recording stoppen</button>
      <div id="recinfo" class="recinfo">Keine Aufnahme aktiv.</div>
    </aside>
    <section>
      <div class="stats" id="stats"></div>
      <canvas id="plot"></canvas>
      <div class="legend">
        <span style="color:#1769aa">User-Acceleration |a|</span>
        <span style="color:#b56b00">Rotation |ω|</span>
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
      draw();
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
        sys.stderr.write(f"[swingstream] {format % args}\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SwingStream live dashboard.")
    parser.add_argument("--host", default="0.0.0.0", help="Bind address (0.0.0.0 = LAN-reachable for the iPhone).")
    parser.add_argument("--port", type=int, default=8788)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    server = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    shown = "127.0.0.1" if args.host in ("0.0.0.0", "") else args.host
    print(f"SwingStream dashboard running at http://{shown}:{args.port}")
    print(f"iPhone bridge should POST batches to http://<mac-ip>:{args.port}/api/ingest")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping SwingStream dashboard.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
