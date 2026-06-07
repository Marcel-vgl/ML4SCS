#!/usr/bin/env python3
"""Stream simulator for the SwingStream dashboard.

Generates synthetic 50 Hz Apple Watch motion samples (idle baseline plus periodic
"strokes") and POSTs them in small batches to the dashboard's /api/ingest endpoint,
exactly like the iPhone bridge would. Lets the whole Mac side be tested end-to-end
without Xcode, an iPhone, or an Apple Watch.

Run the dashboard in one terminal, then:

    .venv_vr/bin/python tools/swingstream_sim.py --duration 60 --rate 50
"""

from __future__ import annotations

import argparse
import json
import math
import random
import time
import urllib.request
from datetime import datetime


def make_sample(seq: int, t0_uptime: float, elapsed: float, rate: float) -> dict:
    """One synthetic sample. A short burst every ~2 s mimics a tennis stroke."""
    phase = elapsed % 2.0
    stroke = math.exp(-((phase - 0.1) ** 2) / 0.002) if phase < 0.4 else 0.0
    jitter = lambda scale: random.gauss(0.0, scale)  # noqa: E731
    user_acc = stroke * 2.5
    gyro = stroke * 12.0
    return {
        "sequence": seq,
        "timestamp_unix_s": time.time(),
        "watch_uptime_s": round(t0_uptime + elapsed, 5),
        "user_acc_x_g": round(user_acc * 0.6 + jitter(0.02), 6),
        "user_acc_y_g": round(user_acc * 0.3 + jitter(0.02), 6),
        "user_acc_z_g": round(-user_acc * 0.5 + jitter(0.02), 6),
        "gyro_x_rad_s": round(gyro * 0.7 + jitter(0.03), 6),
        "gyro_y_rad_s": round(-gyro * 0.4 + jitter(0.03), 6),
        "gyro_z_rad_s": round(gyro * 0.2 + jitter(0.03), 6),
        "acc_x_g": round(user_acc * 0.6 + jitter(0.02), 6),
        "acc_y_g": round(user_acc * 0.3 + jitter(0.02) - 0.0, 6),
        "acc_z_g": round(-1.0 - user_acc * 0.5 + jitter(0.02), 6),
        "gravity_x_g": round(0.0 + jitter(0.01), 6),
        "gravity_y_g": round(-1.0 + jitter(0.01), 6),
        "gravity_z_g": round(0.0 + jitter(0.01), 6),
        "roll_rad": round(jitter(0.05), 6),
        "pitch_rad": round(jitter(0.05), 6),
        "yaw_rad": round(jitter(0.05), 6),
        "quat_x": 0.0, "quat_y": 0.0, "quat_z": 0.0, "quat_w": 1.0,
    }


def post_batch(url: str, batch: dict) -> None:
    data = json.dumps(batch).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        resp.read()


def replay_csv(url: str, path: str, batch_size: int, speed: float) -> None:
    """Streamt eine vorhandene kanonische Apple-Watch-CSV in Echtzeit ans Dashboard
    (zum Testen der Live-Erkennung mit echten Aufnahmen)."""
    import csv

    colmap = {
        "watch_uptime_s": "motionTimestamp_sinceReboot(s)",
        "user_acc_x_g": "motionUserAccelerationX(G)", "user_acc_y_g": "motionUserAccelerationY(G)", "user_acc_z_g": "motionUserAccelerationZ(G)",
        "gyro_x_rad_s": "motionRotationRateX(rad/s)", "gyro_y_rad_s": "motionRotationRateY(rad/s)", "gyro_z_rad_s": "motionRotationRateZ(rad/s)",
        "acc_x_g": "accelerometerAccelerationX(G)", "acc_y_g": "accelerometerAccelerationY(G)", "acc_z_g": "accelerometerAccelerationZ(G)",
        "gravity_x_g": "motionGravityX(G)", "gravity_y_g": "motionGravityY(G)", "gravity_z_g": "motionGravityZ(G)",
        "roll_rad": "motionRoll(rad)", "pitch_rad": "motionPitch(rad)", "yaw_rad": "motionYaw(rad)",
        "quat_x": "motionQuaternionX(R)", "quat_y": "motionQuaternionY(R)", "quat_z": "motionQuaternionZ(R)", "quat_w": "motionQuaternionW(R)",
    }
    rows = list(csv.DictReader(open(path, encoding="utf-8-sig")))
    session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    print(f"Replaying {len(rows)} rows from {path} -> {url}")

    def num(row, key):
        try:
            return float(row.get(key, 0.0) or 0.0)
        except ValueError:
            return 0.0

    batch: list[dict] = []
    prev_t = None
    sent = 0
    for i, row in enumerate(rows):
        sample = {key: num(row, col) for key, col in colmap.items()}
        try:
            sample["sequence"] = int(float(row.get("sequence", i)))
        except ValueError:
            sample["sequence"] = i
        sample["timestamp_unix_s"] = time.time()
        t = sample["watch_uptime_s"]
        if prev_t is not None and speed > 0:
            dt = (t - prev_t) / speed
            if 0 < dt < 1:
                time.sleep(dt)
        prev_t = t
        batch.append(sample)
        if len(batch) >= batch_size:
            post_batch(url, {"type": "sensor_batch", "source": "replay", "session_id": session_id,
                             "bridge_received_unix_s": time.time(), "samples": batch})
            sent += len(batch)
            batch = []
    if batch:
        post_batch(url, {"type": "sensor_batch", "source": "replay", "session_id": session_id,
                         "bridge_received_unix_s": time.time(), "samples": batch})
        sent += len(batch)
    print(f"Done. Replayed {sent} samples.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Simulate an Apple Watch stream to the SwingStream dashboard.")
    parser.add_argument("--url", default="http://127.0.0.1:8788/api/ingest")
    parser.add_argument("--duration", type=float, default=60.0, help="Seconds to stream.")
    parser.add_argument("--rate", type=float, default=50.0, help="Samples per second.")
    parser.add_argument("--batch", type=int, default=5, help="Samples per batch.")
    parser.add_argument("--replay", type=str, default="", help="Replay an existing canonical CSV in real time.")
    parser.add_argument("--speed", type=float, default=1.0, help="Replay speed factor.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.replay:
        replay_csv(args.url, args.replay, args.batch, args.speed)
        return
    session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    period = 1.0 / args.rate
    t0_uptime = round(random.uniform(1000.0, 5000.0), 3)
    start = time.time()
    seq = 0
    batch: list[dict] = []
    sent_samples = 0

    print(f"Streaming {args.rate:g} Hz for {args.duration:g}s to {args.url} (session {session_id})")
    try:
        while True:
            elapsed = time.time() - start
            if elapsed >= args.duration:
                break
            batch.append(make_sample(seq, t0_uptime, elapsed, args.rate))
            seq += 1
            if len(batch) >= args.batch:
                payload = {
                    "type": "sensor_batch",
                    "source": "simulator",
                    "session_id": session_id,
                    "bridge_received_unix_s": time.time(),
                    "samples": batch,
                }
                try:
                    post_batch(args.url, payload)
                    sent_samples += len(batch)
                except Exception as exc:  # noqa: BLE001
                    print(f"  POST failed: {exc}")
                batch = []
            # pace to the target sample rate
            target = start + (seq * period)
            sleep_s = target - time.time()
            if sleep_s > 0:
                time.sleep(sleep_s)
    except KeyboardInterrupt:
        print("\nInterrupted.")

    print(f"Done. Sent {sent_samples} samples in {seq} generated ({time.time() - start:.1f}s).")


if __name__ == "__main__":
    main()
