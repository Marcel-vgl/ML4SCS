#!/usr/bin/env python3
"""Offline video + Apple Watch labeler for the tennis dataset.

Run from the repository root:

    python3 tools/offline_label_tool.py

Then open http://127.0.0.1:8765 in a browser.
"""

from __future__ import annotations

import argparse
from array import array
from bisect import bisect_left
import csv
import json
import math
import mimetypes
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs


DEFAULT_CSV = Path("/Users/florianschneider/ML4SCS/Daten/fritz_1.csv")
DEFAULT_VIDEO = Path("/Users/florianschneider/ML4SCS/Daten/fritz_1.mp4")
DEFAULT_OFFSET_SECONDS = 14.610
DEFAULT_OUTPUT = Path("labels") / f"{DEFAULT_CSV.stem}_events.csv"

# Merkt sich das zuletzt geladene Datenset, damit es beim naechsten Start als Default dient.
STATE_FILE = Path.home() / ".cache" / "ml4scs-labeler" / "last_dataset.json"


def load_last_dataset() -> dict:
    try:
        with STATE_FILE.open(encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_last_dataset(video_path: Path, csv_path: Path, output_path: Path, offset_seconds: float) -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with STATE_FILE.open("w", encoding="utf-8") as handle:
            json.dump(
                {
                    "video_path": str(video_path),
                    "csv_path": str(csv_path),
                    "output_path": str(output_path),
                    "offset_seconds": offset_seconds,
                },
                handle,
            )
    except OSError as exc:
        print(f"Warning: could not save last dataset state: {exc}")

LABELS = {
    "1": "Vorhand",
    "2": "Rueckhand",
    "3": "Slice Vorhand",
    "4": "Slice Rueckhand",
    "5": "Aufschlag",
    "6": "Aufschlag von unten",
    "7": "Kein Schlag / Other",
    "8": "Schlaeger drehen",
    "9": "Schwung ohne Ball",
    "10": "Unsicher",
}

IMU_COLUMNS = [
    "motionUserAccelerationX(G)",
    "motionUserAccelerationY(G)",
    "motionUserAccelerationZ(G)",
    "motionRotationRateX(rad/s)",
    "motionRotationRateY(rad/s)",
    "motionRotationRateZ(rad/s)",
]

AUDIO_SAMPLE_RATE = 8000
AUDIO_BUCKET_SECONDS = 0.01


@dataclass(frozen=True)
class AppConfig:
    csv_path: Path
    video_path: Path
    output_path: Path
    offset_seconds: float


EVENT_FIELDS = ["video_time_s", "csv_time_s", "label", "label_name", "note"]


# Labels werden immer im labels/-Verzeichnis des Repos abgelegt (unabhaengig davon,
# wo die CSV liegt, z. B. in Daten/). Aus der Script-Position abgeleitet, damit es
# unabhaengig vom aktuellen Arbeitsverzeichnis funktioniert.
LABELS_DIR = Path(__file__).resolve().parent.parent / "labels"


def matching_events_path(csv_path: Path) -> Path:
    return LABELS_DIR / f"{csv_path.stem}_events.csv"


def resolve_events_output_path(csv_path: Path, requested_path: Path | None = None) -> Path:
    # Nur der Dateiname eines gewuenschten Pfads wird beruecksichtigt; das Verzeichnis
    # ist immer LABELS_DIR, damit Labels nie in Daten/labels o. ae. landen.
    name = requested_path.name if (requested_path and requested_path.name) else f"{csv_path.stem}_events.csv"
    return LABELS_DIR / name


def ensure_events_file(output_path: Path) -> None:
    if output_path.exists():
        return
    write_events(output_path, [])


def parse_float(value: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def read_sensor_rows(
    csv_path: Path,
    offset_seconds: float,
    timeline_start_unix_s: float | None = None,
) -> tuple[list[dict], list[dict], list[dict]]:
    rows = apply_offset_to_rows(read_raw_sensor_rows(csv_path, timeline_start_unix_s), offset_seconds)
    points = smooth_rows(downsample_rows(rows, target_points=16000))
    peaks = detect_peaks(rows)
    return points, peaks, rows


def read_raw_sensor_rows(csv_path: Path, timeline_start_unix_s: float | None = None) -> list[dict]:
    rows: list[dict] = []
    with csv_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        first_time: datetime | None = None
        first_motion_time: float | None = None
        for row in reader:
            unix_time = row.get("locationTimestamp_since1970(s)")
            motion_time = row.get("motionTimestamp_sinceReboot(s)")
            if timeline_start_unix_s is not None and unix_time:
                csv_sec = parse_float(unix_time) - timeline_start_unix_s
            elif motion_time:
                motion_seconds = parse_float(motion_time)
                if first_motion_time is None:
                    first_motion_time = motion_seconds
                csv_sec = motion_seconds - first_motion_time
            else:
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
                    "acc": round(acc, 5),
                    "gyro": round(gyro, 5),
                    "score": round(acc + 0.12 * gyro, 5),
                }
            )
    return rows


def metadata_candidates(csv_path: Path, video_path: Path) -> list[Path]:
    candidates = [
        video_path.with_name(f"{video_path.stem}_video_metadata.json"),
        csv_path.with_name(f"{csv_path.stem}_video_metadata.json"),
        video_path.with_suffix(".json"),
        csv_path.with_suffix(".json"),
    ]
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in candidates:
        resolved = path.expanduser().resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(resolved)
    return unique


def load_sync_metadata(csv_path: Path, video_path: Path) -> dict | None:
    for path in metadata_candidates(csv_path, video_path):
        if not path.exists() or not path.is_file():
            continue
        try:
            with path.open(encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            continue

        video_start = parse_float(str(data.get("video_start_unix_s", "")))
        if video_start <= 0:
            continue

        anchor_value = data.get("session_anchor_unix_s")
        anchor = parse_float(str(anchor_value)) if anchor_value is not None else None
        return {
            "source": "metadata_anchor" if anchor else "metadata_video_start",
            "metadata_path": str(path),
            "video_start_unix_s": video_start,
            "session_anchor_unix_s": anchor,
            "video_anchor_time_s": parse_float(str(data.get("video_anchor_time_s", "0"))),
            "confidence": 1.0,
            "matches": 0,
        }
    return None


def apply_offset_to_rows(rows: list[dict], offset_seconds: float) -> list[dict]:
    return [
        {
            **row,
            "video_t": round(float(row["csv_t"]) - offset_seconds, 4),
        }
        for row in rows
    ]


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


# Fenstergroesse fuer die Glaettung der angezeigten Sensorkurven (gleitender Mittelwert).
# Groesser = glatter. Nur fuer die Anzeige; die Peak-Erkennung nutzt die Rohdaten.
SMOOTH_WINDOW = 7


def smooth_rows(
    rows: list[dict],
    window: int = SMOOTH_WINDOW,
    keys: tuple[str, ...] = ("acc", "gyro", "score"),
) -> list[dict]:
    if window < 2 or len(rows) < window:
        return rows
    half = window // 2
    count = len(rows)
    smoothed: list[dict] = []
    for index in range(count):
        lo = max(0, index - half)
        hi = min(count, index + half + 1)
        span = hi - lo
        out = dict(rows[index])
        for key in keys:
            total = 0.0
            for j in range(lo, hi):
                total += float(rows[j].get(key, 0.0) or 0.0)
            out[key] = round(total / span, 5)
        smoothed.append(out)
    return smoothed


def detect_peaks(
    rows: list[dict],
    limit: int = 220,
    min_spacing_s: float = 0.45,
    time_key: str = "video_t",
    min_time: float = 0,
) -> list[dict]:
    candidates = [row for row in rows if row[time_key] >= min_time]
    selected: list[dict] = []
    for row in sorted(candidates, key=lambda item: item["score"], reverse=True):
        if all(abs(row[time_key] - peak[time_key]) >= min_spacing_s for peak in selected):
            selected.append(row)
        if len(selected) >= limit:
            break
    return sorted(selected, key=lambda item: item[time_key])


def extract_audio_envelope(video_path: Path) -> list[dict]:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg or not video_path.exists():
        return []

    cmd = [
        ffmpeg,
        "-v",
        "error",
        "-i",
        str(video_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(AUDIO_SAMPLE_RATE),
        "-f",
        "s16le",
        "-",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        print(f"Warning: could not extract audio envelope: {exc}")
        return []

    samples = array("h")
    usable_bytes = len(result.stdout) - (len(result.stdout) % samples.itemsize)
    samples.frombytes(result.stdout[:usable_bytes])
    if not samples:
        return []

    if samples.itemsize != 2:
        return []

    bucket_size = max(1, int(AUDIO_SAMPLE_RATE * AUDIO_BUCKET_SECONDS))
    points: list[dict] = []
    max_rms = 1.0
    for start in range(0, len(samples), bucket_size):
        bucket = samples[start : start + bucket_size]
        if not bucket:
            continue
        mean_square = sum(sample * sample for sample in bucket) / len(bucket)
        rms = math.sqrt(mean_square)
        max_rms = max(max_rms, rms)
        points.append(
            {
                "video_t": round(start / AUDIO_SAMPLE_RATE, 4),
                "amp_raw": rms,
            }
        )

    for point in points:
        point["amp"] = round(float(point.pop("amp_raw")) / max_rms, 5)

    return downsample_audio_points(points, target_points=18000)


def downsample_audio_points(points: list[dict], target_points: int) -> list[dict]:
    if len(points) <= target_points:
        return points

    bucket_size = math.ceil(len(points) / target_points)
    downsampled: list[dict] = []
    for start in range(0, len(points), bucket_size):
        bucket = points[start : start + bucket_size]
        strongest = max(bucket, key=lambda item: item["amp"])
        downsampled.append(strongest)
    return downsampled


def detect_audio_peaks(points: list[dict], limit: int = 260, min_spacing_s: float = 0.28) -> list[dict]:
    if len(points) < 3:
        return []

    amplitudes = sorted(point["amp"] for point in points)
    p70 = amplitudes[int(len(amplitudes) * 0.70)]
    p95 = amplitudes[int(len(amplitudes) * 0.95)]
    threshold = max(0.08, p70 + (p95 - p70) * 0.30)

    candidates: list[dict] = []
    for index in range(1, len(points) - 1):
        point = points[index]
        if point["amp"] < threshold:
            continue
        if point["amp"] >= points[index - 1]["amp"] and point["amp"] >= points[index + 1]["amp"]:
            candidates.append(
                {
                    "video_t": point["video_t"],
                    "amp": point["amp"],
                    "score": point["amp"],
                }
            )

    selected: list[dict] = []
    for peak in sorted(candidates, key=lambda item: item["amp"], reverse=True):
        if all(abs(peak["video_t"] - item["video_t"]) >= min_spacing_s for item in selected):
            selected.append(peak)
        if len(selected) >= limit:
            break
    return sorted(selected, key=lambda item: item["video_t"])


def estimate_offset_from_audio(
    raw_sensor_rows: list[dict],
    audio_peaks: list[dict],
    fallback_offset: float,
) -> tuple[float, dict]:
    sensor_peaks = detect_peaks(
        raw_sensor_rows,
        limit=180,
        min_spacing_s=0.45,
        time_key="csv_t",
        min_time=0,
    )
    if len(sensor_peaks) < 2 or len(audio_peaks) < 2:
        return fallback_offset, {"source": "fallback", "matches": 0, "confidence": 0.0}

    top_sensor = sorted(sensor_peaks, key=lambda item: item["score"], reverse=True)[:80]
    top_audio = sorted(audio_peaks, key=lambda item: item["amp"], reverse=True)[:80]
    csv_duration = raw_sensor_rows[-1]["csv_t"] if raw_sensor_rows else 0
    audio_duration = audio_peaks[-1]["video_t"] if audio_peaks else 0
    min_offset = -audio_duration
    max_offset = csv_duration

    candidates = {round(fallback_offset, 3)}
    for sensor_peak in top_sensor:
        for audio_peak in top_audio:
            offset = sensor_peak["csv_t"] - audio_peak["video_t"]
            if min_offset <= offset <= max_offset:
                candidates.add(round(offset, 3))

    audio_times = [peak["video_t"] for peak in audio_peaks]
    audio_by_time = {peak["video_t"]: peak for peak in audio_peaks}
    max_sensor_score = max((peak["score"] for peak in top_sensor), default=1.0)
    tolerance = 0.35

    def nearest_audio(video_t: float) -> tuple[dict | None, float]:
        index = bisect_left(audio_times, video_t)
        nearest: tuple[dict | None, float] = (None, float("inf"))
        for candidate_index in (index - 1, index):
            if 0 <= candidate_index < len(audio_times):
                candidate_time = audio_times[candidate_index]
                distance = abs(candidate_time - video_t)
                if distance < nearest[1]:
                    nearest = (audio_by_time[candidate_time], distance)
        return nearest

    def evaluate(offset: float) -> dict:
        score = 0.0
        matches = 0
        total = 0
        for sensor_peak in top_sensor:
            video_t = sensor_peak["csv_t"] - offset
            if video_t < 0 or video_t > audio_duration:
                continue
            total += 1
            audio_peak, distance = nearest_audio(video_t)
            if audio_peak is None or distance > tolerance:
                continue
            sensor_weight = sensor_peak["score"] / max_sensor_score
            audio_weight = audio_peak["amp"]
            score += sensor_weight * audio_weight * (1 - distance / tolerance)
            matches += 1
        confidence = score / max(total, 1)
        return {"offset": offset, "score": score, "matches": matches, "confidence": confidence}

    best = max((evaluate(offset) for offset in candidates), key=lambda item: item["score"])
    for step in (0.05, 0.01, 0.002):
        center = best["offset"]
        local_candidates = [center + step * i for i in range(-10, 11)]
        local_best = max((evaluate(offset) for offset in local_candidates), key=lambda item: item["score"])
        if local_best["score"] >= best["score"]:
            best = local_best

    fallback = evaluate(fallback_offset)
    if best["matches"] < 2 or best["score"] < fallback["score"] * 1.08:
        fallback["source"] = "fallback"
        return fallback_offset, fallback

    best["source"] = "audio"
    return round(best["offset"], 3), best


def find_triple_clap(
    points: list[dict],
    time_key: str,
    val_key: str,
    search_start: float,
    search_end: float,
) -> list[float] | None:
    range_points = [p for p in points if search_start <= p[time_key] <= search_end]
    if len(range_points) < 5:
        return None

    vals = [p[val_key] for p in range_points]
    max_val = max(vals)
    min_val = min(vals)
    span = max_val - min_val
    if span <= 0.001:
        return None

    threshold = min_val + 0.25 * span

    local_peaks = []
    for i in range(1, len(range_points) - 1):
        prev_p = range_points[i - 1]
        curr_p = range_points[i]
        next_p = range_points[i + 1]
        if (
            curr_p[val_key] > prev_p[val_key]
            and curr_p[val_key] > next_p[val_key]
        ):
            if curr_p[val_key] >= threshold:
                local_peaks.append(curr_p)

    if len(local_peaks) < 3:
        threshold = min_val + 0.10 * span
        local_peaks = []
        for i in range(1, len(range_points) - 1):
            curr_p = range_points[i]
            if (
                curr_p[val_key] > range_points[i - 1][val_key]
                and curr_p[val_key] > range_points[i + 1][val_key]
            ):
                if curr_p[val_key] >= threshold:
                    local_peaks.append(curr_p)

    if len(local_peaks) < 3:
        return None

    local_peaks = sorted(local_peaks, key=lambda x: x[val_key], reverse=True)[:15]
    local_peaks = sorted(local_peaks, key=lambda x: x[time_key])

    best_triplet = None
    best_score = -1.0

    n = len(local_peaks)
    for i in range(n):
        for j in range(i + 1, n):
            for k in range(j + 1, n):
                t1 = local_peaks[i][time_key]
                t2 = local_peaks[j][time_key]
                t3 = local_peaks[k][time_key]

                v1 = local_peaks[i][val_key]
                v2 = local_peaks[j][val_key]
                v3 = local_peaks[k][val_key]

                d1 = t2 - t1
                d2 = t3 - t2

                if not (0.2 <= d1 <= 1.5 and 0.2 <= d2 <= 1.5):
                    continue

                ratio = d2 / d1 if d1 > 0 else 0
                if not (0.5 <= ratio <= 2.0):
                    continue

                amplitude_score = v1 + v2 + v3
                tempo_diff = abs(d2 - d1)
                max_d = max(d1, d2)
                tempo_score = 1.0 - (tempo_diff / max_d if max_d > 0 else 0)

                score = amplitude_score * (0.6 + 0.4 * tempo_score)
                if score > best_score:
                    best_score = score
                    best_triplet = [t1, t2, t3]

    return best_triplet


def build_audio_based_suggestions(
    sensor_peaks: list[dict],
    audio_peaks: list[dict],
    limit: int = 260,
) -> list[dict]:
    if not audio_peaks:
        return sensor_peaks[:limit]

    sensor_times = [peak["video_t"] for peak in sensor_peaks]
    max_sensor_score = max((peak["score"] for peak in sensor_peaks), default=1.0)
    suggestions: list[dict] = []

    for audio_peak in audio_peaks:
        index = bisect_left(sensor_times, audio_peak["video_t"])
        nearest_sensor = None
        nearest_distance = float("inf")
        for candidate_index in (index - 1, index):
            if 0 <= candidate_index < len(sensor_peaks):
                candidate = sensor_peaks[candidate_index]
                distance = abs(candidate["video_t"] - audio_peak["video_t"])
                if distance < nearest_distance:
                    nearest_sensor = candidate
                    nearest_distance = distance

        sensor_score = 0.0
        csv_t = None
        if nearest_sensor is not None and nearest_distance <= 0.45:
            sensor_score = nearest_sensor["score"] / max_sensor_score
            csv_t = nearest_sensor["csv_t"]

        score = audio_peak["amp"] * 1.4 + sensor_score * max(0.0, 1 - nearest_distance / 0.45)
        suggestions.append(
            {
                "video_t": round(audio_peak["video_t"], 4),
                "csv_t": round(csv_t, 4) if csv_t is not None else "",
                "amp": audio_peak["amp"],
                "score": round(score, 5),
                "source": "audio",
            }
        )

    for sensor_peak in sensor_peaks:
        sensor_score = sensor_peak["score"] / max_sensor_score if max_sensor_score else 0.0
        suggestions.append(
            {
                "video_t": round(sensor_peak["video_t"], 4),
                "csv_t": round(sensor_peak["csv_t"], 4),
                "amp": "",
                "score": round(sensor_score, 5),
                "source": "sensor",
            }
        )

    merged: list[dict] = []
    for suggestion in sorted(suggestions, key=lambda item: item["video_t"]):
        if merged and suggestion["video_t"] - merged[-1]["video_t"] < 0.45:
            if suggestion["score"] > merged[-1]["score"]:
                merged[-1] = suggestion
            elif suggestion.get("source") != merged[-1].get("source"):
                merged[-1]["source"] = "combined"
            continue
        merged.append(suggestion)

    selected: list[dict] = []
    for suggestion in sorted(merged, key=lambda item: item["score"], reverse=True):
        if all(abs(suggestion["video_t"] - item["video_t"]) >= 0.45 for item in selected):
            selected.append(suggestion)
        if len(selected) >= limit:
            break
    return sorted(selected, key=lambda item: item["video_t"])


def analyze_media(csv_path: Path, video_path: Path, fallback_offset: float) -> tuple[list[dict], list[dict], list[dict], list[dict], float, dict]:
    audio_points = extract_audio_envelope(video_path)
    audio_peaks = detect_audio_peaks(audio_points)

    sync_metadata = load_sync_metadata(csv_path, video_path)
    if sync_metadata:
        raw_sensor_rows = read_raw_sensor_rows(
            csv_path,
            timeline_start_unix_s=sync_metadata["video_start_unix_s"],
        )
        sensor_rows = apply_offset_to_rows(raw_sensor_rows, 0.0)
        points = downsample_rows(sensor_rows, target_points=16000)
        sensor_peaks = detect_peaks(sensor_rows)
        suggestions = build_audio_based_suggestions(sensor_peaks, audio_peaks)
        return points, suggestions, audio_points, audio_peaks, 0.0, sync_metadata

    raw_sensor_rows = read_raw_sensor_rows(csv_path)
    estimated_offset, offset_info = estimate_offset_from_audio(raw_sensor_rows, audio_peaks, fallback_offset)
    sensor_rows = apply_offset_to_rows(raw_sensor_rows, estimated_offset)
    points = downsample_rows(sensor_rows, target_points=16000)
    sensor_peaks = detect_peaks(sensor_rows)
    suggestions = build_audio_based_suggestions(sensor_peaks, audio_peaks)
    return points, suggestions, audio_points, audio_peaks, estimated_offset, offset_info


def read_events(output_path: Path) -> list[dict]:
    if not output_path.exists():
        return []

    with output_path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_events(output_path: Path, events: list[dict]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=EVENT_FIELDS)
        writer.writeheader()
        for event in sorted(events, key=lambda item: float(item["video_time_s"])):
            writer.writerow({field: event.get(field, "") for field in EVENT_FIELDS})


def app_html(config: AppConfig) -> str:
    labels_json = json.dumps(LABELS, ensure_ascii=True)
    default_dataset_json = json.dumps(
        {
            "video_path": str(config.video_path),
            "csv_path": str(config.csv_path),
            "output_path": str(config.output_path),
            "offset_seconds": config.offset_seconds,
        },
        ensure_ascii=True,
    )

    has_video = config.video_path and config.video_path.exists() and config.video_path.is_file()
    has_csv = config.csv_path and config.csv_path.exists() and config.csv_path.is_file()

    video_name = config.video_path.name if has_video else "Keine Video-Datei geladen"
    csv_name = config.csv_path.name if has_csv else "Keine CSV-Datei geladen"
    output_name = str(config.output_path) if config.output_path else "Kein Ausgabepfad"

    video_path_str = str(config.video_path.absolute()) if config.video_path else ""
    csv_path_str = str(config.csv_path.absolute()) if config.csv_path else ""
    output_path_str = str(config.output_path.absolute()) if config.output_path else ""

    welcome_display = "" if not (has_video and has_csv) else "none"

    return f"""<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Tennis Labeler</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700&display=swap" rel="stylesheet">
  <style>
    :root {{
      --bg: #070913;
      --panel-bg: rgba(20, 24, 38, 0.6);
      --panel-border: rgba(255, 255, 255, 0.08);
      --text: #f3f4f6;
      --text-muted: #9ca3af;
      --accent: #38bdf8;
      --accent-glow: rgba(56, 189, 248, 0.15);
      --green: #10b981;
      --green-glow: rgba(16, 185, 129, 0.15);
      --red: #f43f5e;
      --red-glow: rgba(244, 63, 94, 0.15);
      --orange: #f59e0b;
      --indigo: #6366f1;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: radial-gradient(circle at 50% 0%, rgba(99, 102, 241, 0.1) 0%, rgba(7, 9, 19, 0) 70%), #070913;
      color: var(--text);
      font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      overflow-x: hidden;
    }}
    header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 12px 24px;
      background: rgba(15, 18, 28, 0.85);
      backdrop-filter: blur(12px);
      border-bottom: 1px solid var(--panel-border);
      position: sticky;
      top: 0;
      z-index: 10;
    }}
    header h1 {{
      margin: 0;
      font-size: 18px;
      font-weight: 700;
      background: linear-gradient(135deg, #fff 0%, #a5b4fc 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      letter-spacing: -0.5px;
    }}
    header .meta {{
      color: var(--text-muted);
      font-size: 12px;
      line-height: 1.4;
    }}
    main {{
      flex: 1;
      display: flex;
      flex-direction: column;
      gap: 10px;
      padding: 10px 18px;
      max-width: 1800px;
      margin: 0 auto;
      width: 100%;
      min-height: 0;
      --video-aspect: 1.777;
    }}
    .panel {{
      background: var(--panel-bg);
      border: 1px solid var(--panel-border);
      border-radius: 12px;
      overflow: hidden;
      backdrop-filter: blur(16px);
      box-shadow: 0 10px 30px rgba(0, 0, 0, 0.3);
    }}
    .video-panel {{
      display: flex;
      flex-direction: column;
      width: 100%;
      height: clamp(400px, 60vh, 78vh);
      background: #000000;
      position: relative;
      border-radius: 12px;
      box-shadow: 0 20px 40px rgba(0, 0, 0, 0.5), 0 0 30px rgba(99, 102, 241, 0.03);
    }}
    video {{
      display: block;
      width: 100%;
      flex: 1 1 auto;
      min-height: 0;
      height: auto;
      object-fit: contain;
      background: black;
    }}
    /* Eigene Steuerleiste UNTER dem Video. Die nativen Controls werden nicht benutzt,
       weil Safari sie im pausierten Zustand mit dunklen Verlaeufen ueber das Bild legt
       (wirkt wie Abdunkeln). So bleibt der Frame beim Pausieren/Stepping gleich hell. */
    .video-controls {{
      flex: 0 0 auto;
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 6px 12px;
      background: rgba(15, 18, 28, 0.92);
      border-top: 1px solid var(--panel-border);
    }}
    .vc-btn {{
      width: 36px;
      height: 28px;
      padding: 0;
      font-size: 13px;
      flex: 0 0 auto;
    }}
    .vc-time {{
      font-size: 12px;
      color: var(--text-muted);
      font-variant-numeric: tabular-nums;
      white-space: nowrap;
      flex: 0 0 auto;
    }}
    .vc-seek {{
      flex: 1 1 auto;
      min-width: 0;
      cursor: pointer;
      accent-color: var(--accent);
    }}
    .dashboard-grid {{
      display: grid;
      grid-template-columns: 1fr;
      grid-template-rows: auto 1fr;
      grid-template-areas:
        "chart"
        "dock";
      gap: 10px;
      min-height: 0;
      flex: 1;
    }}
    .label-dock {{
      grid-area: dock;
      display: grid;
      grid-template-columns: minmax(220px, 270px) minmax(380px, 0.85fr) minmax(360px, 1.3fr);
      grid-template-areas: "controls labels events";
      gap: 10px;
      align-items: start;
      padding: 8px;
      min-height: 0;
      height: 100%;
    }}
    .column-left {{
      display: contents;
    }}
    .column-left .card:first-child {{
      grid-area: controls;
    }}
    .column-left .card:last-child {{
      grid-area: labels;
    }}
    .peak-actions {{
      display: grid;
      grid-template-columns: 1fr;
      gap: 6px;
      margin-bottom: 2px;
    }}
    .peak-actions button {{
      width: 100%;
      min-height: 30px;
    }}
    .card {{
      background: var(--panel-bg);
      border: 1px solid var(--panel-border);
      border-radius: 12px;
      padding: 10px;
      display: flex;
      flex-direction: column;
      gap: 8px;
      backdrop-filter: blur(16px);
      box-shadow: 0 8px 24px rgba(0, 0, 0, 0.2);
    }}
    .label-dock .card,
    .label-dock .side-section {{
      background: transparent;
      border: 0;
      border-radius: 0;
      box-shadow: none;
      backdrop-filter: none;
      padding: 0;
    }}
    .label-dock .card {{
      gap: 6px;
    }}
    .label-dock .card h3,
    .label-dock .side-section h2 {{
      display: none;
    }}
    .label-dock .column-left .card:first-child {{
      display: grid;
      grid-template-columns: repeat(2, minmax(120px, 1fr));
      align-items: start;
    }}
    .label-dock .column-left .card:first-child .status-position {{
      grid-column: span 2;
    }}
    .label-dock .offset-row {{
      padding: 5px 8px;
    }}
    main.layout-side {{
      display: grid;
      grid-template-columns: minmax(560px, min(86vw, calc(100vw - 212px))) minmax(170px, 192px);
      grid-template-areas:
        "video dock"
        "chart dock";
      grid-template-rows: auto 1fr;
      align-items: start;
      max-width: none;
      min-height: calc(100vh - 80px);
    }}
    main.layout-side .video-panel {{
      grid-area: video;
      height: min(64vh, calc((100vw - 212px) / var(--video-aspect)));
      min-height: 380px;
    }}
    main.layout-side .dashboard-grid {{
      display: contents;
    }}
    main.layout-side .chart-panel {{
      grid-area: chart;
      height: 280px;
      min-height: 280px;
    }}
    main.audio-hidden.layout-side .video-panel {{
      height: min(74vh, calc((100vw - 212px) / var(--video-aspect)));
    }}
    main.audio-hidden .chart-panel {{
      height: 201px;
      min-height: 201px;
    }}
    main.audio-hidden.layout-side .chart-panel {{
      height: 201px;
      min-height: 201px;
    }}
    main.layout-side .label-dock {{
      grid-area: dock;
      align-self: stretch;
      grid-template-columns: 1fr;
      grid-template-rows: auto auto 1fr;
      grid-template-areas:
        "controls"
        "labels"
        "events";
    }}
    main.layout-side .label-dock .column-left .card:first-child {{
      grid-template-columns: 1fr;
    }}
    main.layout-side .label-dock .column-left .card:first-child .status-position {{
      grid-column: auto;
    }}
    main.layout-side .labels-grid {{
      grid-template-columns: 1fr;
    }}
    main.layout-side .label-key {{
      min-height: 30px;
      padding: 6px 8px;
      gap: 8px;
      font-size: 12px;
      line-height: 1.15;
    }}
    main.layout-side .label-key .badge {{
      min-width: 20px;
      height: 20px;
      line-height: 18px;
      padding: 0 6px;
      font-size: 11px;
    }}
    main.layout-side button.btn-delete {{
      width: 32px;
      height: 28px;
      font-size: 14px;
    }}
    main.layout-side .peak-actions button {{
      min-height: 28px;
      padding-top: 5px;
      padding-bottom: 5px;
      font-size: 11px;
    }}
    main.layout-side button {{
      padding-left: 7px;
      padding-right: 7px;
    }}
    main.layout-side .side-section {{
      max-height: none;
      min-height: 0;
      align-self: stretch;
    }}
    main.layout-side .events-list {{
      flex: 1 1 auto;
      max-height: clamp(180px, 55vh, 600px);
      min-height: 0;
      overflow-y: auto;
    }}
    main.layout-side .row {{
      grid-template-columns: auto 1fr;
      gap: 8px;
      padding: 5px 6px;
      font-size: 11px;
    }}
    main.layout-side .row .btn-row-go {{
      display: none;
    }}
    .card h3 {{
      margin: 0;
      font-size: 12px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      color: var(--text-muted);
    }}
    .control-row {{
      display: flex;
      align-items: center;
      gap: 8px;
    }}
    .control-row.grid-2 {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
    }}
    .offset-row {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      background: rgba(255, 255, 255, 0.03);
      padding: 8px 12px;
      border-radius: 8px;
      border: 1px solid var(--panel-border);
    }}
    .offset-row label {{
      font-size: 13px;
      color: var(--text-muted);
      font-weight: 500;
    }}
    .offset-row input {{
      border: 1px solid rgba(255, 255, 255, 0.1);
      border-radius: 6px;
      padding: 5px 8px;
      font: inherit;
      font-size: 13px;
      width: 90px;
      background: rgba(0, 0, 0, 0.3);
      color: var(--text);
      text-align: right;
      transition: border-color 0.2s;
    }}
    .offset-row input:focus {{
      outline: none;
      border-color: var(--accent);
    }}
    button.btn-mini-toggle {{
      padding: 6px 12px;
      font-size: 12px;
      border-radius: 6px;
    }}
    button.btn-mini-toggle.btn-inactive {{
      background: rgba(56, 189, 248, 0.08);
      border-color: rgba(56, 189, 248, 0.3);
      color: var(--accent);
    }}
    .header-offset {{
      display: flex;
      align-items: center;
      gap: 6px;
      padding: 6px 8px;
      border: 1px solid var(--panel-border);
      border-radius: 8px;
      background: rgba(255, 255, 255, 0.03);
    }}
    .header-offset label {{
      color: var(--text-muted);
      font-size: 12px;
      font-weight: 600;
      white-space: nowrap;
    }}
    .header-offset input {{
      border: 1px solid rgba(255, 255, 255, 0.1);
      border-radius: 6px;
      padding: 4px 7px;
      width: 78px;
      background: rgba(0, 0, 0, 0.3);
      color: var(--text);
      font: inherit;
      font-size: 12px;
      text-align: right;
    }}
    .header-offset input:focus {{
      outline: none;
      border-color: var(--accent);
    }}
    
    /* Buttons styling */
    button {{
      border: 1px solid rgba(255, 255, 255, 0.1);
      border-radius: 8px;
      background: rgba(255, 255, 255, 0.04);
      color: var(--text);
      padding: 7px 10px;
      font: inherit;
      font-size: 13px;
      font-weight: 500;
      cursor: pointer;
      transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      user-select: none;
    }}
    button:hover {{
      background: rgba(255, 255, 255, 0.08);
      border-color: rgba(255, 255, 255, 0.2);
    }}
    button.btn-primary {{
      background: var(--accent);
      border-color: var(--accent);
      color: #000;
      font-weight: 600;
      box-shadow: 0 4px 12px var(--accent-glow);
    }}
    button.btn-primary:hover {{
      background: #7dd3fc;
      border-color: #7dd3fc;
      box-shadow: 0 4px 16px rgba(56, 189, 248, 0.3);
    }}
    button.btn-next-peak {{
      width: 100%;
      min-height: 0;
      padding: 6px 8px;
      border-radius: 8px;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0;
      background: #38bdf8;
      border-color: #7dd3fc;
      box-shadow: 0 6px 18px rgba(56, 189, 248, 0.2);
    }}
    button.btn-next-peak:hover {{
      transform: translateY(-1px);
      box-shadow: 0 8px 22px rgba(56, 189, 248, 0.28);
    }}
    
    button.btn-sync {{
      background: rgba(99, 102, 241, 0.15);
      border-color: rgba(99, 102, 241, 0.3);
      color: #c7d2fe;
      width: 100%;
    }}
    button.btn-sync:hover {{
      background: rgba(99, 102, 241, 0.25);
      border-color: rgba(99, 102, 241, 0.5);
      box-shadow: 0 0 10px rgba(99, 102, 241, 0.15);
    }}
    
    button.btn-toggle {{
      width: 100%;
      background: rgba(255, 255, 255, 0.03);
      border-color: var(--panel-border);
      color: var(--text-muted);
    }}
    button.btn-toggle:hover {{
      color: var(--text);
      border-color: rgba(255, 255, 255, 0.15);
    }}
    button.btn-toggle.btn-inactive {{
      background: rgba(56, 189, 248, 0.05);
      border-color: rgba(56, 189, 248, 0.2);
      color: var(--accent);
    }}
    button.btn-settings {{
      width: 100%;
      background: rgba(99, 102, 241, 0.08);
      border-color: rgba(99, 102, 241, 0.24);
      color: #c7d2fe;
    }}
    button.btn-settings:hover {{
      background: rgba(99, 102, 241, 0.16);
      border-color: rgba(99, 102, 241, 0.42);
    }}
    
    /* Labels grid styling */
    .labels-grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 6px;
    }}
    .label-btn,
    .label-key {{
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 6px 7px;
      border-radius: 8px;
      border: 1px solid var(--panel-border);
      background: rgba(255, 255, 255, 0.02);
      color: var(--text);
      font-size: 12px;
      font-weight: 500;
      transition: all 0.2s ease;
      text-align: left;
      justify-content: flex-start;
      user-select: none;
    }}
    .label-btn {{
      cursor: pointer;
    }}
    .label-key {{
      cursor: pointer;
      min-height: 30px;
    }}
    .label-key:focus-visible {{
      outline: 2px solid var(--accent);
      outline-offset: 2px;
    }}
    .label-btn .badge,
    .label-key .badge {{
      flex-shrink: 0;
    }}
    .label-btn:hover {{
      transform: translateY(-1px);
    }}
    .btn-vorhand {{
      border-color: rgba(16, 185, 129, 0.25);
    }}
    .btn-vorhand:hover {{
      background: rgba(16, 185, 129, 0.08);
      border-color: rgba(16, 185, 129, 0.5);
      box-shadow: 0 0 12px rgba(16, 185, 129, 0.15);
    }}
    .btn-rueckhand {{
      border-color: rgba(59, 130, 246, 0.25);
    }}
    .btn-rueckhand:hover {{
      background: rgba(59, 130, 246, 0.08);
      border-color: rgba(59, 130, 246, 0.5);
      box-shadow: 0 0 12px rgba(59, 130, 246, 0.15);
    }}
    .btn-slice-vh {{
      border-color: rgba(139, 92, 246, 0.25);
    }}
    .btn-slice-vh:hover {{
      background: rgba(139, 92, 246, 0.08);
      border-color: rgba(139, 92, 246, 0.5);
      box-shadow: 0 0 12px rgba(139, 92, 246, 0.15);
    }}
    .btn-slice-rh {{
      border-color: rgba(236, 72, 153, 0.25);
    }}
    .btn-slice-rh:hover {{
      background: rgba(236, 72, 153, 0.08);
      border-color: rgba(236, 72, 153, 0.5);
      box-shadow: 0 0 12px rgba(236, 72, 153, 0.15);
    }}
    .btn-aufschlag {{
      border-color: rgba(245, 158, 11, 0.25);
    }}
    .btn-aufschlag:hover {{
      background: rgba(245, 158, 11, 0.08);
      border-color: rgba(245, 158, 11, 0.5);
      box-shadow: 0 0 12px rgba(245, 158, 11, 0.15);
    }}
    .btn-aufschlag-unten {{
      border-color: rgba(251, 146, 60, 0.25);
    }}
    .btn-aufschlag-unten:hover {{
      background: rgba(251, 146, 60, 0.08);
      border-color: rgba(251, 146, 60, 0.5);
      box-shadow: 0 0 12px rgba(251, 146, 60, 0.15);
    }}
    .btn-other {{
      border-color: rgba(156, 163, 175, 0.25);
    }}
    .btn-other:hover {{
      background: rgba(156, 163, 175, 0.08);
      border-color: rgba(156, 163, 175, 0.5);
    }}
    .btn-drehen {{
      border-color: rgba(99, 102, 241, 0.25);
    }}
    .btn-drehen:hover {{
      background: rgba(99, 102, 241, 0.08);
      border-color: rgba(99, 102, 241, 0.5);
      box-shadow: 0 0 12px rgba(99, 102, 241, 0.15);
    }}
    .btn-schwung {{
      border-color: rgba(20, 184, 166, 0.25);
    }}
    .btn-schwung:hover {{
      background: rgba(20, 184, 166, 0.08);
      border-color: rgba(20, 184, 166, 0.5);
      box-shadow: 0 0 12px rgba(20, 184, 166, 0.15);
    }}
    .btn-unsicher {{
      border-color: rgba(248, 113, 113, 0.25);
    }}
    .btn-unsicher:hover {{
      background: rgba(248, 113, 113, 0.08);
      border-color: rgba(248, 113, 113, 0.5);
      box-shadow: 0 0 12px rgba(248, 113, 113, 0.15);
    }}
    
    button.btn-delete {{
      background: rgba(244, 63, 94, 0.08);
      border-color: rgba(244, 63, 94, 0.2);
      color: #fb7185;
      font-weight: 500;
      width: 36px;
      height: 32px;
      padding: 0;
      align-self: flex-end;
      font-size: 16px;
    }}
    button.btn-delete:hover {{
      background: rgba(244, 63, 94, 0.18);
      border-color: rgba(244, 63, 94, 0.4);
      box-shadow: 0 0 12px rgba(244, 63, 94, 0.15);
    }}
    button.btn-delete-current {{
      width: 100%;
      min-height: 32px;
      padding: 6px 8px;
      border-color: rgba(244, 63, 94, 0.34);
      background: rgba(244, 63, 94, 0.12);
      color: #fecdd3;
      font-size: 12px;
      font-weight: 700;
    }}
    button.btn-delete-current:hover {{
      background: rgba(244, 63, 94, 0.22);
      border-color: rgba(244, 63, 94, 0.5);
    }}
    button.btn-delete-current[hidden] {{
      display: none;
    }}
    
    /* Chart container */
    .chart-panel {{
      grid-area: chart;
      display: flex;
      flex-direction: column;
      height: 280px;
      min-height: 280px;
    }}
    .chart-wrap {{
      flex: 1;
      position: relative;
      height: 100%;
      min-height: 0;
      overflow: hidden;
    }}
    canvas {{
      display: block;
      width: 100%;
      height: 100%;
      max-height: 100%;
      cursor: crosshair;
    }}
    
    /* Lists column on the right */
    .column-right {{
      display: contents;
    }}
    .column-right .side-section {{
      grid-area: events;
    }}
    .side-section {{
      display: flex;
      flex-direction: column;
      min-height: 0;
      max-height: none;
      flex: 1;
      align-self: stretch;
      padding: 10px;
      background: var(--panel-bg);
      border: 1px solid var(--panel-border);
      border-radius: 12px;
    }}
    .side-section h2 {{
      margin: 0 0 8px;
      font-size: 12px;
      font-weight: 600;
      color: var(--text);
    }}
    .events-toggle {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      width: 100%;
      min-height: 38px;
      padding: 8px 10px;
      font-size: 13px;
      font-weight: 700;
      color: var(--text);
      background: rgba(255, 255, 255, 0.04);
      border: 1px solid var(--panel-border);
      border-radius: 8px;
      cursor: pointer;
    }}
    .events-toggle:hover {{
      background: rgba(255, 255, 255, 0.07);
    }}
    .events-toggle::after {{
      content: "anzeigen";
      color: var(--accent);
      font-size: 12px;
      font-weight: 700;
    }}
    .events-toggle[aria-expanded="true"]::after {{
      content: "ausblenden";
    }}
    .events-count {{
      min-width: 24px;
      height: 22px;
      padding: 0 7px;
      border-radius: 999px;
      background: rgba(56, 189, 248, 0.16);
      border: 1px solid rgba(56, 189, 248, 0.32);
      color: var(--accent);
      font-size: 12px;
      line-height: 20px;
      text-align: center;
      font-variant-numeric: tabular-nums;
    }}
    .side-section.labels-open {{
      min-height: 140px;
    }}
    
    /* Scrollable lists */
    .list {{
      border-top: 1px solid var(--panel-border);
      flex: 1;
      overflow-y: auto;
      padding-right: 4px;
      --scrollbar-thumb: rgba(255, 255, 255, 0.12);
      --scrollbar-track: rgba(0, 0, 0, 0);
      scrollbar-color: var(--scrollbar-thumb) var(--scrollbar-track);
      scrollbar-width: thin;
    }}
    .events-list {{
      flex: none;
      max-height: clamp(150px, 30vh, 300px);
      margin-top: 8px;
    }}
    .events-list[hidden] {{
      display: none;
    }}
    @supports not (scrollbar-color: auto) {{
      .list::-webkit-scrollbar {{
        width: 5px;
      }}
      .list::-webkit-scrollbar-thumb {{
        background: var(--scrollbar-thumb);
        border-radius: 10px;
      }}
      .list::-webkit-scrollbar-track {{
        background: var(--scrollbar-track);
      }}
    }}
    .row {{
      display: grid;
      grid-template-columns: 76px 1fr auto;
      gap: 6px;
      align-items: center;
      padding: 6px 8px;
      border-bottom: 1px solid rgba(255, 255, 255, 0.04);
      font-size: 13px;
      transition: background 0.15s;
    }}
    .row:hover {{
      background: rgba(255, 255, 255, 0.02);
    }}
    .row button.btn-row-go {{
      padding: 4px 8px;
      font-size: 12px;
      border-radius: 6px;
    }}
    .label-cell {{
      display: flex;
      align-items: center;
      gap: 6px;
      min-width: 0;
    }}
    .label-name {{
      font-weight: 500;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    .time {{
      color: var(--accent);
      font-variant-numeric: tabular-nums;
      font-weight: 600;
    }}
    .badge {{
      display: inline-block;
      min-width: 20px;
      height: 20px;
      line-height: 18px;
      padding: 0 6px;
      border-radius: 5px;
      text-align: center;
      font-size: 11px;
      font-weight: 700;
    }}
    .badge-1 {{ background: rgba(16, 185, 129, 0.15); border: 1px solid rgba(16, 185, 129, 0.3); color: #34d399; }}
    .badge-2 {{ background: rgba(59, 130, 246, 0.15); border: 1px solid rgba(59, 130, 246, 0.3); color: #60a5fa; }}
    .badge-3 {{ background: rgba(139, 92, 246, 0.15); border: 1px solid rgba(139, 92, 246, 0.3); color: #a78bfa; }}
    .badge-4 {{ background: rgba(236, 72, 153, 0.15); border: 1px solid rgba(236, 72, 153, 0.3); color: #f472b6; }}
    .badge-5 {{ background: rgba(245, 158, 11, 0.15); border: 1px solid rgba(245, 158, 11, 0.3); color: #fbbf24; }}
    .badge-6 {{ background: rgba(251, 146, 60, 0.15); border: 1px solid rgba(251, 146, 60, 0.3); color: #fb923c; }}
    .badge-7 {{ background: rgba(156, 163, 175, 0.15); border: 1px solid rgba(156, 163, 175, 0.3); color: #9ca3af; }}
    .badge-8 {{ background: rgba(99, 102, 241, 0.15); border: 1px solid rgba(99, 102, 241, 0.3); color: #818cf8; }}
    .badge-9 {{ background: rgba(20, 184, 166, 0.15); border: 1px solid rgba(20, 184, 166, 0.3); color: #2dd4bf; }}
    .badge-10 {{ background: rgba(248, 113, 113, 0.15); border: 1px solid rgba(248, 113, 113, 0.3); color: #f87171; }}
    
    .status-position {{
      text-align: center;
      font-size: 12px;
      color: var(--text-muted);
      font-variant-numeric: tabular-nums;
      font-weight: 500;
      padding-top: 0;
    }}

    /* Toast overlay */
    .toast {{
      position: fixed;
      bottom: 24px;
      left: 50%;
      transform: translateX(-50%) translateY(100px);
      background: rgba(15, 23, 42, 0.9);
      border: 1px solid var(--panel-border);
      border-radius: 8px;
      padding: 12px 24px;
      color: #fff;
      font-size: 14px;
      font-weight: 500;
      z-index: 2000;
      box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.5), 0 0 15px rgba(99, 102, 241, 0.1);
      transition: transform 0.3s cubic-bezier(0.16, 1, 0.3, 1), opacity 0.3s ease;
      opacity: 0;
      pointer-events: none;
      display: flex;
      align-items: center;
      gap: 8px;
      backdrop-filter: blur(8px);
    }}
    .toast.visible {{
      transform: translateX(-50%) translateY(0);
      opacity: 1;
    }}
    .toast-success {{
      border-color: rgba(16, 185, 129, 0.4);
      background: rgba(6, 78, 59, 0.9);
      box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.5), 0 0 15px rgba(16, 185, 129, 0.2);
    }}
    .toast-error {{
      border-color: rgba(239, 68, 68, 0.4);
      background: rgba(127, 29, 29, 0.9);
      box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.5), 0 0 15px rgba(239, 68, 68, 0.2);
    }}
    .toast-info {{
      border-color: rgba(56, 189, 248, 0.4);
      background: rgba(12, 74, 96, 0.9);
      box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.5), 0 0 15px rgba(56, 189, 248, 0.2);
    }}

    /* Dialogs */
    dialog {{
      border: 1px solid var(--panel-border);
      background: rgba(15, 18, 28, 0.95);
      backdrop-filter: blur(20px);
      border-radius: 12px;
      padding: 24px;
      color: var(--text);
      box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.7), 0 0 40px rgba(99, 102, 241, 0.1);
      width: 500px;
      max-width: 95vw;
      max-height: 85vh;
      display: flex;
      flex-direction: column;
      gap: 16px;
      position: fixed;
      top: 50%;
      left: 50%;
      transform: translate(-50%, -50%);
      margin: 0;
      z-index: 1000;
    }}
    dialog::backdrop {{
      background: rgba(0, 0, 0, 0.6);
      backdrop-filter: blur(4px);
    }}
    dialog:not([open]) {{
      display: none;
    }}

    .form-group {{
      display: flex;
      flex-direction: column;
      gap: 6px;
    }}
    .form-group label {{
      font-size: 13px;
      font-weight: 600;
      color: var(--text-muted);
    }}
    .input-with-btn {{
      display: flex;
      gap: 8px;
    }}
    .input-with-btn input {{
      flex: 1;
      width: 100%;
    }}
    .form-group input[type="text"],
    .form-group input[type="number"] {{
      border: 1px solid rgba(255, 255, 255, 0.1);
      border-radius: 8px;
      padding: 8px 12px;
      font-size: 13px;
      background: rgba(0, 0, 0, 0.3);
      color: var(--text);
      width: 100%;
      transition: border-color 0.2s;
    }}
    .form-group input:focus {{
      outline: none;
      border-color: var(--accent);
    }}
    .modal-actions {{
      display: flex;
      justify-content: flex-end;
      gap: 8px;
      margin-top: 12px;
    }}
    .graph-mode-list {{
      display: grid;
      gap: 8px;
      overflow-y: auto;
      padding-right: 2px;
    }}
    .graph-mode-option {{
      display: grid;
      grid-template-columns: auto 1fr;
      gap: 10px;
      align-items: start;
      padding: 10px;
      border: 1px solid var(--panel-border);
      border-radius: 8px;
      background: rgba(255, 255, 255, 0.03);
      cursor: pointer;
    }}
    .graph-mode-option:hover {{
      border-color: rgba(56, 189, 248, 0.32);
      background: rgba(56, 189, 248, 0.06);
    }}
    .graph-mode-option input {{
      margin-top: 3px;
      accent-color: var(--accent);
    }}
    .graph-mode-title {{
      display: block;
      color: var(--text);
      font-size: 13px;
      font-weight: 700;
      line-height: 1.25;
    }}
    .graph-mode-desc {{
      display: block;
      color: var(--text-muted);
      font-size: 12px;
      line-height: 1.35;
      margin-top: 3px;
    }}
    .error-msg {{
      background: rgba(239, 68, 68, 0.1);
      border: 1px solid rgba(239, 68, 68, 0.3);
      color: #f87171;
      padding: 10px 14px;
      border-radius: 8px;
      font-size: 13px;
      line-height: 1.4;
    }}

    /* File browser style */
    #browseDialog {{
      width: 600px;
    }}
    .browse-header {{
      display: flex;
      align-items: center;
      gap: 10px;
      padding-bottom: 8px;
      border-bottom: 1px solid var(--panel-border);
    }}
    .path-display {{
      font-family: monospace;
      font-size: 12px;
      background: rgba(0, 0, 0, 0.3);
      padding: 6px 12px;
      border-radius: 6px;
      color: var(--text-muted);
      overflow-x: auto;
      white-space: nowrap;
      flex: 1;
      border: 1px solid var(--panel-border);
    }}
    .browse-list {{
      flex: 1;
      overflow-y: auto;
      height: 250px;
      max-height: 45vh;
      border: 1px solid var(--panel-border);
      background: rgba(0, 0, 0, 0.2);
      border-radius: 8px;
      display: flex;
      flex-direction: column;
    }}
    .browse-item {{
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 10px 14px;
      border-bottom: 1px solid rgba(255, 255, 255, 0.04);
      cursor: pointer;
      font-size: 13px;
      transition: background 0.15s, color 0.15s;
      user-select: none;
    }}
    .browse-item:hover {{
      background: rgba(255, 255, 255, 0.04);
    }}
    .browse-item .icon {{
      flex-shrink: 0;
      font-size: 14px;
    }}
    .browse-item.dir .name {{
      color: var(--accent);
      font-weight: 600;
    }}
    .browse-item.file.match .name {{
      color: var(--green);
      font-weight: 600;
    }}
    .browse-item.file:not(.match) {{
      color: var(--text-muted);
    }}
    .browse-item .name {{
      flex: 1;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}
    .browse-item .size {{
      font-size: 11px;
      color: var(--text-muted);
      font-variant-numeric: tabular-nums;
    }}

    /* Welcome overlay style */
    .welcome-overlay {{
      position: absolute;
      top: 0;
      left: 0;
      width: 100%;
      height: 100%;
      background: rgba(7, 9, 19, 0.95);
      z-index: 100;
      display: flex;
      align-items: center;
      justify-content: center;
    }}
    .welcome-box {{
      text-align: center;
      padding: 40px;
      background: rgba(20, 24, 38, 0.85);
      border: 1px solid var(--panel-border);
      border-radius: 16px;
      box-shadow: 0 20px 50px rgba(0,0,0,0.6);
      max-width: 480px;
      backdrop-filter: blur(12px);
    }}
    .welcome-box h2 {{
      margin-top: 0;
      margin-bottom: 12px;
      font-size: 22px;
      font-weight: 700;
      background: linear-gradient(135deg, #fff 0%, #a5b4fc 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
    }}
    .welcome-box p {{
      color: var(--text-muted);
      margin-bottom: 24px;
      font-size: 14px;
      line-height: 1.5;
    }}
    button.large {{
      padding: 12px 24px;
      font-size: 14px;
      font-weight: 600;
    }}

    @media (max-width: 980px) {{
      main.layout-side {{
        display: flex;
        max-width: 1800px;
      }}
      main.layout-side .video-panel {{
        height: clamp(350px, 55vh, 70vh);
        min-height: 0;
      }}
      .dashboard-grid {{
        grid-template-columns: 1fr;
        grid-template-areas:
          "chart"
          "dock";
      }}
      .label-dock {{
        grid-template-columns: 1fr;
        grid-template-rows: auto auto 1fr;
        grid-template-areas:
          "controls"
          "labels"
          "events";
      }}
    }}

    @media (max-height: 820px) {{
      header {{
        padding: 8px 18px;
      }}
      main {{
        gap: 8px;
        padding: 8px 16px;
      }}
      .video-panel {{
        height: clamp(280px, 50vh, 70vh);
      }}
      main.layout-side .video-panel {{
        height: min(60vh, calc((100vw - 212px) / var(--video-aspect)));
        min-height: 320px;
      }}
      main.audio-hidden.layout-side .video-panel {{
        height: min(72vh, calc((100vw - 212px) / var(--video-aspect)));
      }}
      .chart-panel {{
        height: 220px;
        min-height: 220px;
      }}
      main.audio-hidden .chart-panel {{
        height: 154px;
        min-height: 154px;
      }}
      .card {{
        padding: 8px;
      }}
      .label-btn,
      .label-key {{
        padding: 7px 8px;
      }}
      .side-section {{
        max-height: none;
        min-height: 120px;
      }}
      footer {{
        margin-top: 0 !important;
        padding-top: 4px !important;
      }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>Tennis Labeler</h1>
    <div class="meta" style="display: flex; align-items: center; gap: 20px;">
      <div style="text-align: right;">
        Video: <span id="headerVideoName" style="color: var(--accent); font-weight: 500;">{video_name}</span><br>
        CSV: <span id="headerCsvName" style="color: var(--accent); font-weight: 500;">{csv_name}</span> &rarr; <span id="headerOutputName" style="color: var(--text-muted);">{output_name}</span>
      </div>
      <button id="loadDefaultDatasetBtn" class="btn-primary" style="padding: 6px 12px; font-size: 12px; border-radius: 6px;">Datensatz laden</button>
      <button id="openConfigBtn" class="btn-primary" style="padding: 6px 12px; font-size: 12px; border-radius: 6px;">Pfade ändern</button>
      <button id="togglePeaksBtn" class="btn-mini-toggle">Peaks ausblenden</button>
      <div class="header-offset">
        <label for="offset">Sensor-Offset</label>
        <input id="offset" type="number" step="0.001" value="{config.offset_seconds:.3f}">
        <span style="font-size: 12px; color: var(--text-muted);">s</span>
      </div>
    </div>
  </header>

  <main>
    <!-- Video element spanning near-full screen width -->
    <div class="panel video-panel">
      <video id="video" src="/video" preload="metadata" tabindex="-1"></video>
      <div class="video-controls">
        <button id="playPauseBtn" class="vc-btn" type="button" aria-label="Abspielen / Pause" tabindex="-1">▶</button>
        <span id="timeLabel" class="vc-time">0:00 / 0:00</span>
        <input id="seekBar" class="vc-seek" type="range" min="0" max="0" step="0.01" value="0" tabindex="-1" aria-label="Videoposition">
      </div>
      <div id="welcomeOverlay" class="welcome-overlay" style="display: {welcome_display};">
        <div class="welcome-box">
          <h2>Dateipfade einrichten</h2>
          <p>Es wurden noch keine gültigen Video- und CSV-Dateien geladen. Bitte konfigurieren Sie die Pfade, um zu beginnen.</p>
          <button id="welcomeConfigBtn" class="btn-primary large">Pfade konfigurieren</button>
        </div>
      </div>
    </div>

    <!-- 3-column Dashboard layout -->
    <div class="dashboard-grid">
      <!-- Column 2: Timeline Canvas chart -->
      <div class="panel chart-panel">
        <div class="chart-wrap">
          <canvas id="chart"></canvas>
        </div>
      </div>


      <div class="panel label-dock">
      <!-- Column 1: Controls & Stroke buttons -->
      <div class="column-left">
        <div class="card">
          <h3>Steuerung</h3>
          
          <div class="control-row">
            <button id="toggleAudioBtn" class="btn-toggle">Tonspur ausblenden</button>
          </div>
          <div class="control-row">
            <button id="openGraphSettingsBtn" class="btn-settings" type="button">Graph einstellen</button>
          </div>
          
          <div id="position" class="status-position">--</div>
          <button id="deleteCurrentLabel" class="btn-delete-current" type="button" hidden>Label hier löschen</button>
        </div>

        <div class="card">
          <h3>Schlag-Labels</h3>
          <div class="peak-actions">
            <button id="nextPeak" class="btn-primary btn-next-peak">Nächster Peak ▶</button>
            <button id="prevPeak">◀ Peak zurück</button>
          </div>
          <div class="labels-grid">
            <div class="label-key btn-vorhand" role="button" tabindex="0" data-label="1"><span class="badge badge-1">1</span> Vorhand</div>
            <div class="label-key btn-rueckhand" role="button" tabindex="0" data-label="2"><span class="badge badge-2">2</span> Rückhand</div>
            <div class="label-key btn-slice-vh" role="button" tabindex="0" data-label="3"><span class="badge badge-3">3</span> Slice Vorhand</div>
            <div class="label-key btn-slice-rh" role="button" tabindex="0" data-label="4"><span class="badge badge-4">4</span> Slice Rückhand</div>
            <div class="label-key btn-aufschlag" role="button" tabindex="0" data-label="5"><span class="badge badge-5">5</span> Aufschlag</div>
            <div class="label-key btn-aufschlag-unten" role="button" tabindex="0" data-label="6"><span class="badge badge-6">6</span> Aufschlag von unten</div>
            <div class="label-key btn-other" role="button" tabindex="0" data-label="7"><span class="badge badge-7">7</span> Kein Schlag / Other</div>
            <div class="label-key btn-drehen" role="button" tabindex="0" data-label="8"><span class="badge badge-8">8</span> Schläger drehen</div>
            <div class="label-key btn-schwung" role="button" tabindex="0" data-label="9"><span class="badge badge-9">9</span> Schwung ohne Ball</div>
            <div class="label-key btn-unsicher" role="button" tabindex="0" data-label="10"><span class="badge badge-10">10</span> Unsicher</div>
          </div>
        </div>
      </div>

      <!-- Saved labels -->
      <div class="column-right">
        <div id="eventsSection" class="side-section">
          <button id="toggleEventsBtn" class="events-toggle" type="button" aria-expanded="false" aria-controls="events">
            <span>Labels</span>
            <span id="eventsCount" class="events-count">0</span>
          </button>
          <div id="events" class="list events-list" hidden></div>
        </div>
      </div>
      </div>
    </div>
    
    <footer style="text-align: center; font-size: 11px; color: var(--text-muted); margin-top: 8px; padding-top: 8px; border-top: 1px solid var(--panel-border);">
      Tastenkombinationen: <strong>Leertaste</strong> spielt/pausiert | <strong>Pfeiltasten Links/Rechts</strong> springen je 1 Frame | <strong>Shift + Pfeil</strong> springt 8 Frames |
      <strong>Pfeil hoch/runter</strong> Peak vor/zurück | Ziffern <strong>1 bis 9</strong> + <strong>0</strong> (Unsicher) speichern Labels | <strong>N</strong> Nächster Peak | <strong>P</strong> Peak zurück | <strong>Backspace/Delete</strong> löscht das letzte Label
    </footer>
  </main>

  <!-- Configuration Modal -->
  <dialog id="configDialog" aria-labelledby="configTitle">
    <h2 id="configTitle" style="margin-top:0; font-size: 18px; font-weight:700; color: #fff;">Dateipfade konfigurieren</h2>

    <div class="form-group">
      <label for="videoPath">Video-Datei (.mp4, .mov)</label>
      <div class="input-with-btn">
        <input type="text" id="videoPath" placeholder="z.B. /path/to/video.mp4" value="{video_path_str}">
        <button type="button" class="btn-browse" data-target="videoPath" data-type="video">Durchsuchen</button>
      </div>
    </div>

    <div class="form-group">
      <label for="csvPath">Apple Watch Sensor CSV (.csv)</label>
      <div class="input-with-btn">
        <input type="text" id="csvPath" placeholder="z.B. /path/to/sensor.csv" value="{csv_path_str}">
        <button type="button" class="btn-browse" data-target="csvPath" data-type="csv">Durchsuchen</button>
      </div>
    </div>

    <div class="form-group">
      <label for="outputPath">Ausgabe CSV (Labels)</label>
      <input type="text" id="outputPath" placeholder="Auto-generiert aus CSV-Name" value="{output_path_str}">
    </div>

    <div class="form-group">
      <label for="offsetInputVal">Sensor-Offset (Sekunden)</label>
      <input type="number" step="0.001" id="offsetInputVal" value="{config.offset_seconds:.3f}">
    </div>

    <div id="configError" class="error-msg" style="display: none;"></div>

    <div class="modal-actions">
      <button type="button" id="closeConfigBtn">Abbrechen</button>
      <button type="button" id="saveConfigBtn" class="btn-primary">Daten laden</button>
    </div>
  </dialog>

  <dialog id="graphSettingsDialog" aria-labelledby="graphSettingsTitle">
    <h2 id="graphSettingsTitle" style="margin-top:0; font-size: 18px; font-weight:700; color: #fff;">CSV-Graph einstellen</h2>
    <div class="graph-mode-list" role="radiogroup" aria-label="CSV-Darstellung">
      <label class="graph-mode-option">
        <input type="radio" name="csvGraphMode" value="raw">
        <span>
          <span class="graph-mode-title">1. Rohlinien</span>
          <span class="graph-mode-desc">Acc und Gyro ungefiltert mit stabiler globaler Skalierung.</span>
        </span>
      </label>
      <label class="graph-mode-option">
        <input type="radio" name="csvGraphMode" value="smooth">
        <span>
          <span class="graph-mode-title">2. Geglättet</span>
          <span class="graph-mode-desc">Gleitender Mittelwert reduziert Zittern, größere Bewegungen bleiben sichtbar.</span>
        </span>
      </label>
      <label class="graph-mode-option">
        <input type="radio" name="csvGraphMode" value="contrast" checked>
        <span>
          <span class="graph-mode-title">3. Kontrast</span>
          <span class="graph-mode-desc">Lokale Grundbewegung wird abgezogen, schnelle Ausschläge treten stärker hervor.</span>
        </span>
      </label>
      <label class="graph-mode-option">
        <input type="radio" name="csvGraphMode" value="energy">
        <span>
          <span class="graph-mode-title">4. Schlagenergie</span>
          <span class="graph-mode-desc">Kombinierte Acc/Gyro-Energie als Fläche plus Linienkontur.</span>
        </span>
      </label>
      <label class="graph-mode-option">
        <input type="radio" name="csvGraphMode" value="impulse">
        <span>
          <span class="graph-mode-title">5. Impulswechsel</span>
          <span class="graph-mode-desc">Differenzfilter zeigt abrupte Richtungs- und Tempoänderungen.</span>
        </span>
      </label>
    </div>
    <div class="modal-actions">
      <button type="button" id="closeGraphSettingsBtn" class="btn-primary">Fertig</button>
    </div>
  </dialog>

  <script>
    const labelNames = {labels_json};
    const defaultDataset = {default_dataset_json};
    const video = document.getElementById('video');
    const canvas = document.getElementById('chart');
    const ctx = canvas.getContext('2d');
    const offsetInput = document.getElementById('offset');
    const position = document.getElementById('position');
    const playPauseBtn = document.getElementById('playPauseBtn');
    const seekBar = document.getElementById('seekBar');
    const timeLabel = document.getElementById('timeLabel');
    let seekDragging = false;
    let sensor = [];
    let audio = [];
    let audioPeaks = [];
    let peaks = [];
    let events = [];
    let windowSeconds = 18;
    let maxAcc = 1;
    let maxGyro = 1;
    let maxScore = 1;
    let maxAudio = 1;
    const AUDIO_GAIN = 2.2; // Verstaerkung der Tonspur: leisere Geraeusche schlagen hoeher aus
    let showAudioTrack = true;
    let showPeaks = true;
    let csvGraphMode = 'contrast';
    let graphSeriesCache = new Map();
    let lastSavedLabelTime = null;

    function offsetSeconds() {{
      return Number(offsetInput.value) || 0;
    }}

    function csvTime(videoTime) {{
      return videoTime + offsetSeconds();
    }}

    function updateAdaptiveLayout() {{
      if (!video.videoWidth || !video.videoHeight) {{
        document.querySelector('main').classList.remove('layout-side');
        return;
      }}

      const aspect = video.videoWidth / video.videoHeight;
      const main = document.querySelector('main');
      main.style.setProperty('--video-aspect', aspect.toFixed(4));

      const canUseSideDock = window.innerWidth >= 980;
      const isNarrowVideo = aspect < 1.55;
      const plannedVideoWidth = Math.min(window.innerWidth * 0.86, window.innerWidth - 212);
      const hasUsefulSideSpace = window.innerWidth - plannedVideoWidth >= 170;

      main.classList.toggle('layout-side', canUseSideDock && isNarrowVideo && hasUsefulSideSpace);
      main.classList.toggle('audio-hidden', !showAudioTrack);
      resizeCanvas();
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

    function robustMax(points, key, fallback) {{
      const values = points
        .map(point => Number(point[key]) || 0)
        .filter(value => value > 0)
        .sort((a, b) => a - b);
      if (!values.length) return fallback;
      return Math.max(values[Math.floor(values.length * 0.98)] || fallback, fallback);
    }}

    function robustMaxValues(values, fallback = 1) {{
      const sorted = values
        .map(value => Number(value) || 0)
        .filter(value => value > 0)
        .sort((a, b) => a - b);
      if (!sorted.length) return fallback;
      return Math.max(sorted[Math.floor(sorted.length * 0.98)] || fallback, fallback);
    }}

    function averageWindow(rows, index, key, radius) {{
      const start = Math.max(0, index - radius);
      const end = Math.min(rows.length - 1, index + radius);
      let total = 0;
      let count = 0;
      for (let i = start; i <= end; i++) {{
        total += Number(rows[i][key]) || 0;
        count += 1;
      }}
      return count ? total / count : 0;
    }}

    function buildGraphSeries(mode) {{
      const rows = sensor || [];
      const series = [];
      for (let i = 0; i < rows.length; i++) {{
        const point = rows[i];
        const prev = rows[Math.max(0, i - 1)];
        const acc = Number(point.acc) || 0;
        const gyro = Number(point.gyro) || 0;
        let accValue = acc;
        let gyroValue = gyro;
        let energyValue = Number(point.score) || 0;

        if (mode === 'smooth') {{
          accValue = averageWindow(rows, i, 'acc', 4);
          gyroValue = averageWindow(rows, i, 'gyro', 4);
          energyValue = accValue + 0.12 * gyroValue;
        }} else if (mode === 'contrast') {{
          const accBase = averageWindow(rows, i, 'acc', 18);
          const gyroBase = averageWindow(rows, i, 'gyro', 18);
          accValue = Math.max(0, acc - accBase);
          gyroValue = Math.max(0, gyro - gyroBase);
          energyValue = accValue + 0.16 * gyroValue;
        }} else if (mode === 'energy') {{
          const smoothAcc = averageWindow(rows, i, 'acc', 3);
          const smoothGyro = averageWindow(rows, i, 'gyro', 3);
          accValue = smoothAcc;
          gyroValue = smoothGyro;
          energyValue = smoothAcc + 0.18 * smoothGyro;
        }} else if (mode === 'impulse') {{
          accValue = Math.abs(acc - (Number(prev.acc) || 0));
          gyroValue = Math.abs(gyro - (Number(prev.gyro) || 0));
          energyValue = accValue + 0.22 * gyroValue;
        }}

        series.push({{
          csv_t: point.csv_t,
          acc: accValue,
          gyro: gyroValue,
          energy: energyValue,
        }});
      }}

      return {{
        points: series,
        maxAcc: robustMaxValues(series.map(point => point.acc), 1),
        maxGyro: robustMaxValues(series.map(point => point.gyro), 1),
        maxEnergy: robustMaxValues(series.map(point => point.energy), 1),
      }};
    }}

    function getGraphSeries() {{
      if (!graphSeriesCache.has(csvGraphMode)) {{
        graphSeriesCache.set(csvGraphMode, buildGraphSeries(csvGraphMode));
      }}
      return graphSeriesCache.get(csvGraphMode);
    }}

    // Peak-Vorschlaege direkt aus den Energie-Balken ableiten:
    // zusammenhaengende Balken ueber dem Schwellwert werden zu EINEM Vorschlag gebuendelt.
    function computeEnergyPeaks() {{
      const series = getGraphSeries();
      const points = series.points || [];
      const maxEnergy = series.maxEnergy || 1;
      if (!points.length) return [];
      // Schwellwert identisch zu drawSensorEnergy() (sonst passen Balken und Vorschlaege nicht zusammen).
      const threshold = csvGraphMode === 'impulse' ? 0.36 : 0.48;
      const clusterGapS = 0.18; // kurze Einbrueche innerhalb eines Schlags ueberbruecken
      const minPeakGapS = 0.40; // Mindestabstand zwischen finalen Vorschlaegen
      const offset = offsetSeconds();

      // 1. Aufeinanderfolgende Balken (mit kleiner Luecken-Toleranz) zu Clustern buendeln.
      const clusters = [];
      let current = null;
      let lastActiveT = null;
      for (const p of points) {{
        const value = Math.min((Number(p.energy) || 0) / maxEnergy, 1);
        if (value < threshold) continue;
        const t = p.csv_t;
        if (current && lastActiveT !== null && (t - lastActiveT) <= clusterGapS) {{
          if (value > current.score) {{ current.score = value; current.csv_t = t; }}
        }} else {{
          current = {{ csv_t: t, score: value }};
          clusters.push(current);
        }}
        lastActiveT = t;
      }}

      // 2. Sehr nahe Cluster zusammenfassen und jeweils den staerksten behalten.
      clusters.sort((a, b) => a.csv_t - b.csv_t);
      const merged = [];
      for (const c of clusters) {{
        const last = merged[merged.length - 1];
        if (last && (c.csv_t - last.csv_t) < minPeakGapS) {{
          if (c.score > last.score) {{ last.csv_t = c.csv_t; last.score = c.score; }}
        }} else {{
          merged.push({{ csv_t: c.csv_t, score: c.score }});
        }}
      }}

      return merged.map(c => ({{ csv_t: c.csv_t, video_t: c.csv_t - offset, score: c.score }}));
    }}

    function drawChart() {{
      const rect = canvas.getBoundingClientRect();
      const width = rect.width;
      const height = rect.height;
      ctx.clearRect(0, 0, width, height);
      
      // Premium dark background for chart
      ctx.fillStyle = '#0b0c16';
      ctx.fillRect(0, 0, width, height);

      if (!sensor || sensor.length === 0) {{
        ctx.fillStyle = '#657385';
        ctx.font = '13px "Plus Jakarta Sans", -apple-system, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('Keine Sensordaten geladen', width / 2, height / 2);
        return;
      }}

      const current = video.currentTime || 0;
      const start = Math.max(0, current - windowSeconds / 2);
      const end = start + windowSeconds;
      const padTop = 20;
      const markerBandH = 34;
      const padBottom = 28 + markerBandH;
      const gap = showAudioTrack ? 18 : 0;
      const audioH = showAudioTrack ? Math.max(48, Math.floor((height - padTop - padBottom - gap) * 0.34)) : 0;
      const sensorTop = padTop + audioH + gap;
      const sensorH = height - sensorTop - padBottom;
      const peakMarkerY = sensorTop + sensorH + 10;
      const labelMarkerY = sensorTop + sensorH + 23;

      if (showAudioTrack) {{
        ctx.fillStyle = '#101421';
        ctx.fillRect(0, padTop, width, audioH);
      }}
      ctx.fillStyle = '#0f172a';
      ctx.fillRect(0, sensorTop, width, sensorH);

      // Draw plot grid
      ctx.strokeStyle = 'rgba(148, 163, 184, 0.16)';
      ctx.lineWidth = 1;
      for (const ratio of [0, 0.25, 0.5, 0.75, 1]) {{
        const y = sensorTop + sensorH * ratio;
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(width, y);
        ctx.stroke();
      }}
      if (showAudioTrack) {{
        ctx.strokeStyle = 'rgba(148, 163, 184, 0.22)';
        ctx.beginPath();
        ctx.moveTo(0, padTop + audioH);
        ctx.lineTo(width, padTop + audioH);
        ctx.stroke();
      }}

      // 1. Draw Audio track if visible
      if (showAudioTrack) {{
        ctx.strokeStyle = '#10b981'; // emerald green
        ctx.lineWidth = 1.2;
        ctx.beginPath();
        let hasAudioPoint = false;
        for (const point of audio) {{
          const t = point.video_t;
          if (t < start || t > end) continue;
          const x = timeToX(t, start, end, width);
          const value = Math.min((point.amp / maxAudio) * AUDIO_GAIN, 1);
          const y = padTop + audioH - value * audioH;
          if (!hasAudioPoint) {{
            ctx.moveTo(x, y);
            hasAudioPoint = true;
          }} else {{
            ctx.lineTo(x, y);
          }}
        }}
        ctx.stroke();

        ctx.fillStyle = 'rgba(16, 185, 129, 0.15)';
        for (const peak of audioPeaks) {{
          if (peak.video_t < start || peak.video_t > end) continue;
          const x = timeToX(peak.video_t, start, end, width);
          ctx.fillRect(x - 1, padTop, 2, audioH);
        }}
      }}

      const graphSeries = getGraphSeries();
      const visibleSensor = graphSeries.points.filter(point => {{
        const t = point.csv_t - offsetSeconds();
        return t >= start && t <= end;
      }});

      const stableMaxAcc = graphSeries.maxAcc || maxAcc || 1;
      const stableMaxGyro = graphSeries.maxGyro || maxGyro || 1;
      const stableMaxEnergy = graphSeries.maxEnergy || maxScore || 1;
      const strokeThreshold = csvGraphMode === 'impulse' ? 0.36 : 0.48;

      function drawSensorEnergy() {{
        if (!visibleSensor.length) return;

        for (const point of visibleSensor) {{
          const t = point.csv_t - offsetSeconds();
          const x = timeToX(t, start, end, width);
          const value = Math.min((Number(point.energy) || 0) / stableMaxEnergy, 1);
          if (value < strokeThreshold) continue;
          const bandH = Math.max(14, Math.pow(value, 1.2) * sensorH);
          const alpha = Math.min(0.36, 0.08 + value * 0.24);
          ctx.fillStyle = `rgba(56, 189, 248, ${{alpha.toFixed(3)}})`;
          ctx.fillRect(x - 1.5, sensorTop + sensorH - bandH, 3, bandH);
        }}

        const thresholdY = sensorTop + sensorH - strokeThreshold * sensorH;
        ctx.setLineDash([5, 5]);
        ctx.strokeStyle = 'rgba(37, 99, 235, 0.35)';
        ctx.beginPath();
        ctx.moveTo(0, thresholdY);
        ctx.lineTo(width, thresholdY);
        ctx.stroke();
        ctx.setLineDash([]);
      }}

      // Helper function to draw sensor channels (acc, gyro)
      function drawLine(key, color, maxValue, lineWidth = 1.5) {{
        ctx.strokeStyle = color;
        ctx.lineWidth = lineWidth;
        ctx.lineJoin = 'round';
        ctx.lineCap = 'round';
        ctx.beginPath();
        let hasPoint = false;
        for (const point of visibleSensor) {{
          const t = point.csv_t - offsetSeconds();
          const x = timeToX(t, start, end, width);
          const value = Math.min(point[key] / maxValue, 1);
          const y = sensorTop + sensorH - value * sensorH;
          if (!hasPoint) {{
            ctx.moveTo(x, y);
            hasPoint = true;
          }} else {{
            ctx.lineTo(x, y);
          }}
        }}
        ctx.stroke();
      }}

      function drawEnergyArea(color, maxValue) {{
        if (!visibleSensor.length) return;
        ctx.fillStyle = color;
        ctx.beginPath();
        let hasPoint = false;
        for (const point of visibleSensor) {{
          const t = point.csv_t - offsetSeconds();
          const x = timeToX(t, start, end, width);
          const value = Math.min((Number(point.energy) || 0) / maxValue, 1);
          const y = sensorTop + sensorH - Math.pow(value, 1.1) * sensorH;
          if (!hasPoint) {{
            ctx.moveTo(x, sensorTop + sensorH);
            ctx.lineTo(x, y);
            hasPoint = true;
          }} else {{
            ctx.lineTo(x, y);
          }}
        }}
        ctx.lineTo(timeToX(end, start, end, width), sensorTop + sensorH);
        ctx.closePath();
        ctx.fill();
      }}

      // 2. Draw sensor channels with the selected CSV graph mode.
      drawSensorEnergy();
      if (csvGraphMode === 'energy') {{
        drawEnergyArea('rgba(56, 189, 248, 0.28)', stableMaxEnergy);
        drawLine('energy', '#e0f2fe', stableMaxEnergy, 1.5);
        drawLine('acc', 'rgba(125, 211, 252, 0.78)', stableMaxAcc, 1.15);
        drawLine('gyro', 'rgba(251, 191, 36, 0.78)', stableMaxGyro, 1.15);
      }} else if (csvGraphMode === 'contrast') {{
        drawLine('acc', '#67e8f9', stableMaxAcc, 1.75);
        drawLine('gyro', '#fbbf24', stableMaxGyro, 1.75);
      }} else if (csvGraphMode === 'impulse') {{
        drawEnergyArea('rgba(14, 165, 233, 0.18)', stableMaxEnergy);
        drawLine('acc', '#38bdf8', stableMaxAcc, 1.55);
        drawLine('gyro', '#fb923c', stableMaxGyro, 1.55);
      }} else if (csvGraphMode === 'smooth') {{
        drawLine('acc', '#7dd3fc', stableMaxAcc, 1.9);
        drawLine('gyro', '#facc15', stableMaxGyro, 1.9);
      }} else {{
        drawLine('acc', '#38bdf8', stableMaxAcc, 1.65);
        drawLine('gyro', '#f59e0b', stableMaxGyro, 1.65);
      }}

      // 3. Draw peak suggestions and saved labels as marker dots below the graph.
      let currentFrameHasPeak = false;
      const currentFrame = Math.round(current * 30);
      if (showPeaks) {{
        for (const peak of peaks) {{
          if (peak.video_t < start || peak.video_t > end) continue;
          const x = timeToX(peak.video_t, start, end, width);
          const peakFrame = Math.round(Number(peak.video_t) * 30);
          const isCurrentFrame = peakFrame === currentFrame;
          currentFrameHasPeak = currentFrameHasPeak || isCurrentFrame;
          ctx.fillStyle = isCurrentFrame ? '#f43f5e' : '#3b82f6';
          ctx.strokeStyle = isCurrentFrame ? 'rgba(244, 63, 94, 0.95)' : 'rgba(191, 219, 254, 0.75)';
          ctx.lineWidth = isCurrentFrame ? 2 : 1;
          ctx.beginPath();
          ctx.arc(x, peakMarkerY, isCurrentFrame ? 5 : 3.5, 0, Math.PI * 2);
          ctx.fill();
          ctx.stroke();
        }}
      }}

      // 4. Draw saved labels as green dots on a separate marker row below the graph.
      for (const event of events) {{
        const t = Number(event.video_time_s);
        if (t < start || t > end) continue;
        const x = timeToX(t, start, end, width);
        ctx.fillStyle = (event.label === '7' || event.label === '8' || event.label === '9' || event.label === '10') ? '#94a3b8' : '#22c55e';
        ctx.strokeStyle = 'rgba(240, 253, 244, 0.75)';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.arc(x, labelMarkerY, 4, 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();
      }}

      // 5. Draw playback head cursor
      const xNow = timeToX(current, start, end, width);
      ctx.strokeStyle = currentFrameHasPeak ? '#fb7185' : '#f43f5e'; // rose/red
      ctx.lineWidth = currentFrameHasPeak ? 3 : 2;
      if (currentFrameHasPeak) {{
        ctx.fillStyle = 'rgba(244, 63, 94, 0.16)';
        ctx.fillRect(xNow - 7, sensorTop, 14, sensorH + markerBandH);
      }}
      ctx.beginPath();
      ctx.moveTo(xNow, padTop);
      ctx.lineTo(xNow, labelMarkerY + 8);
      ctx.stroke();
      if (currentFrameHasPeak) {{
        ctx.fillStyle = '#fb7185';
        ctx.font = '11px "Plus Jakarta Sans", sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('Peak', Math.min(width - 18, Math.max(18, xNow)), sensorTop + 13);
      }}

      // Legend and texts
      ctx.textAlign = 'left';
      ctx.font = '11px "Plus Jakarta Sans", sans-serif';
      if (showAudioTrack) {{
        ctx.fillStyle = '#10b981';
        ctx.fillText('audio', 12, 15);
        ctx.fillStyle = '#1f77b4';
        ctx.fillText('acc', 60, 15);
        ctx.fillStyle = '#d97706';
        ctx.fillText('gyro', 94, 15);
        ctx.fillStyle = '#94a3b8';
        ctx.fillText(`${{start.toFixed(1)}}s - ${{end.toFixed(1)}}s`, 138, 15);
      }} else {{
        ctx.fillStyle = '#1f77b4';
        ctx.fillText('acc', 12, 15);
        ctx.fillStyle = '#d97706';
        ctx.fillText('gyro', 48, 15);
        ctx.fillStyle = '#94a3b8';
        ctx.fillText(`${{start.toFixed(1)}}s - ${{end.toFixed(1)}}s`, 86, 15);
      }}
    }}

    async function loadData() {{
      try {{
        const sensorRes = await fetch('/sensor.json');
        const data = await sensorRes.json();
        sensor = data.points || [];
        audio = data.audio_points || [];
        audioPeaks = data.audio_peaks || [];
        graphSeriesCache.clear();
        if (typeof data.estimated_offset === 'number') {{
          offsetInput.value = data.estimated_offset.toFixed(3);
          document.getElementById('offsetInputVal').value = data.estimated_offset.toFixed(3);
        }}
        if (sensor.length > 0) {{
          maxAcc = robustMax(sensor, 'acc', 1);
          maxGyro = robustMax(sensor, 'gyro', 1);
          maxScore = robustMax(sensor, 'score', 1);
        }} else {{
          maxAcc = 1;
          maxGyro = 1;
          maxScore = 1;
        }}
        maxAudio = audio.length > 0 ? Math.max(...audio.map(p => p.amp), 1) : 1;

        const eventsRes = await fetch('/labels');
      events = await eventsRes.json();
      peaks = computeEnergyPeaks();
      renderPeaks();
      renderEvents();
      updateCurrentLabelDeleteControl();
      resizeCanvas();
      }} catch (err) {{
        showToast('Fehler beim Laden der Spuren: ' + err.message, 'error');
      }}
    }}

    function renderPeaks() {{
      const container = document.getElementById('peaks');
      if (!container) return;
      container.innerHTML = '';
      if (!peaks || peaks.length === 0) {{
        container.innerHTML = '<div style="color:var(--text-muted); padding:16px; font-size:12px; text-align:center;">Keine Peaks vorhanden</div>';
        return;
      }}
      for (const peak of peaks) {{
        const row = document.createElement('div');
        row.className = 'row';
        const amp = typeof peak.amp === 'number' ? ` | Audio ${{peak.amp.toFixed(2)}}` : '';
        row.innerHTML = `<span class="time">${{peak.video_t.toFixed(2)}}s</span><span class="score">Score ${{peak.score.toFixed(2)}}${{amp}}</span>`;
        const button = document.createElement('button');
        button.textContent = 'Go';
        button.className = 'btn-row-go btn-primary';
        button.addEventListener('click', () => seek(peak.video_t));
        row.appendChild(button);
        container.appendChild(row);
      }}
    }}

    function renderEvents() {{
      const container = document.getElementById('events');
      const count = events ? events.length : 0;
      document.getElementById('eventsCount').textContent = count;
      container.innerHTML = '';
      if (count === 0) {{
        container.innerHTML = '<div style="color:var(--text-muted); padding:16px; font-size:12px; text-align:center;">Keine gespeicherten Labels</div>';
        return;
      }}
      for (const event of events) {{
        const row = document.createElement('div');
        row.className = 'row';
        row.style.cursor = 'pointer';
        const badgeClass = `badge-${{event.label}}`;
        row.innerHTML = `<span class="time">${{Number(event.video_time_s).toFixed(2)}}s</span><span class="label-cell"><span class="badge ${{badgeClass}}">${{event.label}}</span><span class="label-name">${{event.label_name}}</span></span>`;
        const button = document.createElement('button');
        button.textContent = 'Go';
        button.className = 'btn-row-go btn-primary';
        button.addEventListener('click', (e) => {{ e.stopPropagation(); seek(Number(event.video_time_s)); }});
        row.appendChild(button);
        row.addEventListener('click', () => seek(Number(event.video_time_s)));
        container.appendChild(row);
      }}
    }}

    function seek(t) {{
      video.currentTime = Math.max(0, t);
      updateCurrentLabelDeleteControl();
      drawChart();
    }}

    function labelAtCurrentFrame() {{
      if (!events || !events.length) return null;
      const currentFrame = Math.round((video.currentTime || 0) * 30);
      return events.find(event => Math.round(Number(event.video_time_s) * 30) === currentFrame) || null;
    }}

    function updateCurrentLabelDeleteControl() {{
      const btn = document.getElementById('deleteCurrentLabel');
      if (!btn) return;
      const event = labelAtCurrentFrame();
      if (!event) {{
        btn.hidden = true;
        btn.removeAttribute('data-video-time');
        btn.textContent = 'Label hier löschen';
        return;
      }}
      btn.hidden = false;
      btn.dataset.videoTime = event.video_time_s;
      btn.textContent = `${{event.label_name}} bei ${{Number(event.video_time_s).toFixed(2)}}s löschen`;
    }}

    function nearestPeak(direction) {{
      const current = video.currentTime || 0;
      if (!peaks || peaks.length === 0) return {{ video_t: 0 }};
      if (direction > 0) {{
        return peaks.find(p => p.video_t > current + 0.08) || peaks[peaks.length - 1];
      }}
      for (let i = peaks.length - 1; i >= 0; i--) {{
        if (peaks[i].video_t < current - 0.08) return peaks[i];
      }}
      return peaks[0];
    }}

    async function addLabel(label) {{
      if (!sensor || sensor.length === 0) return;
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
      lastSavedLabelTime = payload.video_time_s;
      renderEvents();
      updateCurrentLabelDeleteControl();
      drawChart();
    }}

    async function deleteLastLabel() {{
      if (!events || !events.length) return;
      const fallback = events[events.length - 1];
      const target = lastSavedLabelTime
        ? (events.find(event => String(event.video_time_s) === String(lastSavedLabelTime)) || fallback)
        : fallback;
      const res = await fetch('/labels/delete', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{video_time_s: target.video_time_s}})
      }});
      events = await res.json();
      lastSavedLabelTime = null;
      renderEvents();
      updateCurrentLabelDeleteControl();
      drawChart();
      showToast('Letztes Label gelöscht.', 'info');
    }}

    async function deleteCurrentFrameLabel() {{
      const target = labelAtCurrentFrame();
      if (!target) return;
      const res = await fetch('/labels/delete', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{video_time_s: target.video_time_s}})
      }});
      events = await res.json();
      if (String(lastSavedLabelTime) === String(target.video_time_s)) {{
        lastSavedLabelTime = null;
      }}
      renderEvents();
      updateCurrentLabelDeleteControl();
      drawChart();
    }}

    function updatePosition() {{
      const vt = video.currentTime || 0;
      position.textContent = `Video ${{vt.toFixed(3)}}s | CSV ${{csvTime(vt).toFixed(3)}}s`;
      updateCurrentLabelDeleteControl();
      updateVideoControls();
      drawChart();
    }}

    function formatTime(sec) {{
      sec = Math.max(0, Math.floor(Number(sec) || 0));
      const m = Math.floor(sec / 60);
      const s = sec % 60;
      return m + ':' + String(s).padStart(2, '0');
    }}

    function updateVideoControls() {{
      const dur = video.duration;
      const cur = video.currentTime || 0;
      if (dur && Number.isFinite(dur)) seekBar.max = dur;
      if (!seekDragging) seekBar.value = cur;
      timeLabel.textContent = formatTime(cur) + ' / ' + formatTime(Number.isFinite(dur) ? dur : 0);
      playPauseBtn.textContent = video.paused ? '▶' : '❚❚';
    }}

    function togglePlay() {{
      video.blur();
      if (video.paused) video.play(); else video.pause();
    }}

    function showToast(message, type = 'info') {{
      const existing = document.querySelectorAll('.toast');
      existing.forEach(t => t.remove());

      const toast = document.createElement('div');
      toast.className = `toast toast-${{type}}`;
      toast.textContent = message;
      document.body.appendChild(toast);

      setTimeout(() => toast.classList.add('visible'), 50);

      setTimeout(() => {{
        toast.classList.remove('visible');
        setTimeout(() => toast.remove(), 300);
      }}, 3500);
    }}

    // Toggle Audio Track Visibility
    const toggleAudioBtn = document.getElementById('toggleAudioBtn');
    toggleAudioBtn.addEventListener('click', () => {{
      showAudioTrack = !showAudioTrack;
      if (showAudioTrack) {{
        toggleAudioBtn.textContent = 'Tonspur ausblenden';
        toggleAudioBtn.classList.remove('btn-inactive');
        showToast('Tonspur eingeblendet.', 'info');
      }} else {{
        toggleAudioBtn.textContent = 'Tonspur einblenden';
        toggleAudioBtn.classList.add('btn-inactive');
        showToast('Tonspur ausgeblendet.', 'info');
      }}
      document.querySelector('main').classList.toggle('audio-hidden', !showAudioTrack);
      resizeCanvas();
      drawChart();
    }});

    // Toggle Peak Suggestions Visibility
    const togglePeaksBtn = document.getElementById('togglePeaksBtn');
    togglePeaksBtn.addEventListener('click', () => {{
      showPeaks = !showPeaks;
      if (showPeaks) {{
        togglePeaksBtn.textContent = 'Peaks ausblenden';
        togglePeaksBtn.classList.remove('btn-inactive');
        showToast('Peak-Vorschläge eingeblendet.', 'info');
      }} else {{
        togglePeaksBtn.textContent = 'Peaks einblenden';
        togglePeaksBtn.classList.add('btn-inactive');
        showToast('Peak-Vorschläge ausgeblendet.', 'info');
      }}
      drawChart();
    }});

    const graphSettingsDialog = document.getElementById('graphSettingsDialog');
    document.getElementById('openGraphSettingsBtn').addEventListener('click', () => graphSettingsDialog.showModal());
    document.getElementById('closeGraphSettingsBtn').addEventListener('click', () => graphSettingsDialog.close());
    document.querySelectorAll('input[name="csvGraphMode"]').forEach(input => {{
      input.addEventListener('change', () => {{
        csvGraphMode = input.value;
        peaks = computeEnergyPeaks();
        renderPeaks();
        drawChart();
      }});
    }});
    document.querySelectorAll('[data-label]').forEach(button => {{
      button.addEventListener('click', () => addLabel(button.dataset.label));
      button.addEventListener('keydown', (event) => {{
        if (event.key !== 'Enter' && event.key !== ' ') return;
        event.preventDefault();
        addLabel(button.dataset.label);
      }});
    }});

    document.getElementById('nextPeak').addEventListener('click', () => seek(nearestPeak(1).video_t));
    document.getElementById('prevPeak').addEventListener('click', () => seek(nearestPeak(-1).video_t));
    document.getElementById('deleteCurrentLabel').addEventListener('click', deleteCurrentFrameLabel);
    document.getElementById('toggleEventsBtn').addEventListener('click', () => {{
      const section = document.getElementById('eventsSection');
      const list = document.getElementById('events');
      const btn = document.getElementById('toggleEventsBtn');
      const isOpen = btn.getAttribute('aria-expanded') === 'true';
      btn.setAttribute('aria-expanded', String(!isOpen));
      list.hidden = isOpen;
      section.classList.toggle('labels-open', !isOpen);
    }});
    offsetInput.addEventListener('input', () => {{ peaks = computeEnergyPeaks(); renderPeaks(); updatePosition(); }});
    video.addEventListener('loadedmetadata', () => {{ updateAdaptiveLayout(); updateVideoControls(); }});
    video.addEventListener('timeupdate', updatePosition);
    video.addEventListener('seeked', updatePosition);
    video.addEventListener('play', updateVideoControls);
    video.addEventListener('pause', updateVideoControls);
    video.addEventListener('durationchange', updateVideoControls);
    playPauseBtn.addEventListener('click', togglePlay);
    seekBar.addEventListener('input', () => {{
      seekDragging = true;
      seek(Number(seekBar.value));
    }});
    seekBar.addEventListener('change', () => {{
      seekDragging = false;
      seekBar.blur();
    }});
    window.addEventListener('resize', updateAdaptiveLayout);
    canvas.addEventListener('click', (event) => {{
      const rect = canvas.getBoundingClientRect();
      const current = video.currentTime || 0;
      const start = Math.max(0, current - windowSeconds / 2);
      const clicked = start + (event.clientX - rect.left) / rect.width * windowSeconds;
      seek(clicked);
    }});
    document.addEventListener('keydown', (event) => {{
      if (event.target.closest && event.target.closest('input, textarea, select, button, [data-label]')) return;
      if (event.key === ' ') {{
        event.preventDefault();
        video.blur();
        video.paused ? video.play() : video.pause();
      }} else if (event.key === 'ArrowRight') {{
        event.preventDefault();
        event.stopPropagation();
        event.stopImmediatePropagation();
        video.blur();
        seek((video.currentTime || 0) + (event.shiftKey ? 8 / 30 : 1 / 30));
      }} else if (event.key === 'ArrowLeft') {{
        event.preventDefault();
        event.stopPropagation();
        event.stopImmediatePropagation();
        video.blur();
        seek((video.currentTime || 0) - (event.shiftKey ? 8 / 30 : 1 / 30));
      }} else if (event.key === 'ArrowUp') {{
        event.preventDefault();
        event.stopPropagation();
        event.stopImmediatePropagation();
        video.blur();
        seek(nearestPeak(1).video_t);
      }} else if (event.key === 'ArrowDown') {{
        event.preventDefault();
        event.stopPropagation();
        event.stopImmediatePropagation();
        video.blur();
        seek(nearestPeak(-1).video_t);
      }} else if (['1', '2', '3', '4', '5', '6', '7', '8', '9'].includes(event.key)) {{
        addLabel(event.key);
      }} else if (event.key === '0') {{
        addLabel('10');
      }} else if (event.key.toLowerCase() === 'n') {{
        seek(nearestPeak(1).video_t);
      }} else if (event.key.toLowerCase() === 'p') {{
        seek(nearestPeak(-1).video_t);
      }} else if (event.key === 'Backspace' || event.key === 'Delete') {{
        event.preventDefault();
        deleteLastLabel();
      }}
    }}, true);

    const configDialog = document.getElementById('configDialog');

    function showConfig() {{
      document.getElementById('offsetInputVal').value = offsetInput.value;
      configDialog.showModal();
    }}

    configDialog.addEventListener('click', (event) => {{
      if (event.target !== configDialog) return;
      configDialog.close();
    }});

    document.querySelectorAll('.btn-browse').forEach(btn => {{
      btn.addEventListener('click', async () => {{
        const targetId = btn.dataset.target;
        const type = btn.dataset.type;
        const oldText = btn.textContent;

        btn.textContent = 'Wählen...';
        btn.disabled = true;

        try {{
          const res = await fetch('/api/browse_native?type=' + type);
          const data = await res.json();
          if (data.path) {{
            document.getElementById(targetId).value = data.path;
            if (targetId === 'csvPath') {{
              const csvPathVal = data.path;
              const lastSlash = csvPathVal.lastIndexOf('/');
              const csvFile = lastSlash !== -1 ? csvPathVal.substring(lastSlash + 1) : csvPathVal;
              const csvName = csvFile.substring(0, csvFile.lastIndexOf('.')) || csvFile;
              // Labels landen immer im labels/-Verzeichnis des Repos (nicht im CSV-Ordner).
              document.getElementById('outputPath').value = 'labels/' + csvName + '_events.csv';
            }}
          }}
        }} catch (err) {{
          console.error(err);
        }} finally {{
          btn.textContent = oldText;
          btn.disabled = false;
        }}
      }});
    }});

    document.getElementById('closeConfigBtn').addEventListener('click', () => configDialog.close());
    document.getElementById('openConfigBtn').addEventListener('click', showConfig);
    if (document.getElementById('welcomeConfigBtn')) {{
      document.getElementById('welcomeConfigBtn').addEventListener('click', showConfig);
    }}

    async function loadConfiguredDataset(dataset, btn, errorDiv = null) {{
      const videoPath = dataset.video_path;
      const csvPath = dataset.csv_path;
      const outputPath = dataset.output_path;
      const offsetSeconds = Number(dataset.offset_seconds) || 0;
      if (errorDiv) errorDiv.style.display = 'none';
      btn.disabled = true;
      try {{
        const res = await fetch('/api/load_config', {{
          method: 'POST',
          headers: {{'Content-Type': 'application/json'}},
          body: JSON.stringify({{video_path: videoPath, csv_path: csvPath, output_path: outputPath, offset_seconds: offsetSeconds}})
        }});
        const data = await res.json();
        if (data.success) {{
          const estimatedOffset = typeof data.estimated_offset === 'number' ? data.estimated_offset : offsetSeconds;
          offsetInput.value = estimatedOffset.toFixed(3);
          document.getElementById('offsetInputVal').value = estimatedOffset.toFixed(3);
          document.getElementById('videoPath').value = videoPath;
          document.getElementById('csvPath').value = csvPath;
          document.getElementById('outputPath').value = data.output_path || outputPath;
          document.getElementById('headerVideoName').textContent = videoPath.split('/').pop();
          document.getElementById('headerCsvName').textContent = csvPath.split('/').pop();
          document.getElementById('headerOutputName').textContent = (data.output_path || outputPath).split('/').pop();
          const welcome = document.getElementById('welcomeOverlay');
          if (welcome) welcome.style.display = 'none';
          configDialog.close();
          video.src = '/video?t=' + new Date().getTime();
          await loadData();
          updateAdaptiveLayout();
          showToast('Konfiguration geladen!', 'success');
        }} else {{
          if (errorDiv) {{
            errorDiv.textContent = data.error;
            errorDiv.style.display = 'block';
          }}
          showToast('Fehler: ' + data.error, 'error');
        }}
      }} catch (err) {{
        if (errorDiv) {{
          errorDiv.textContent = 'Netzwerkfehler: ' + err.message;
          errorDiv.style.display = 'block';
        }}
        showToast('Netzwerkfehler: ' + err.message, 'error');
      }} finally {{ btn.disabled = false; }}
    }}

    document.getElementById('loadDefaultDatasetBtn').addEventListener('click', async () => {{
      const btn = document.getElementById('loadDefaultDatasetBtn');
      await loadConfiguredDataset(defaultDataset, btn);
    }});

    document.getElementById('saveConfigBtn').addEventListener('click', async () => {{
      const errorDiv = document.getElementById('configError');
      const btn = document.getElementById('saveConfigBtn');
      await loadConfiguredDataset({{
        video_path: document.getElementById('videoPath').value,
        csv_path: document.getElementById('csvPath').value,
        output_path: document.getElementById('outputPath').value,
        offset_seconds: parseFloat(document.getElementById('offsetInputVal').value) || 0,
      }}, btn, errorDiv);
    }});

    loadData();
  </script>
</body>
</html>"""


def select_file_native(prompt: str, file_type: str = None) -> str | None:
    # Use AppleScript to open native file picker on macOS
    file_filter = ""
    if file_type == 'video':
        file_filter = ' of type {"mp4", "mov", "avi", "mkv", "public.movie"}'
    elif file_type == 'csv':
        file_filter = ' of type {"csv", "txt", "public.comma-separated-values-text", "public.data"}'

    # We use 'activate' to bring the scripting addition window of osascript to the front
    applescript = (
        'activate\n'
        f'set selectedFile to choose file with prompt "{prompt}"{file_filter}\n'
        'POSIX path of selectedFile'
    )

    try:
        result = subprocess.run(
            ["osascript"],
            input=applescript,
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip()
    except Exception as e:
        print(f"[select_file_native] AppleScript failed: {e}")
        if isinstance(e, subprocess.CalledProcessError):
            print(f"[select_file_native] osascript stderr: {e.stderr.strip()}")

        # Fallback: try choose file without filter or activation in case of type/security issues
        try:
            print("[select_file_native] Attempting fallback choose file...")
            fallback_cmd = ["osascript", "-e", f'POSIX path of (choose file with prompt "{prompt}")']
            result = subprocess.run(fallback_cmd, capture_output=True, text=True, check=True)
            return result.stdout.strip()
        except Exception as fe:
            print(f"[select_file_native] Fallback AppleScript also failed: {fe}")
            if isinstance(fe, subprocess.CalledProcessError):
                print(f"[select_file_native] Fallback osascript stderr: {fe.stderr.strip()}")
            return None



class LabelHandler(BaseHTTPRequestHandler):
    config: AppConfig
    points: list[dict]
    peaks: list[dict]
    audio_points: list[dict]
    audio_peaks: list[dict]
    offset_info: dict

    def do_HEAD(self) -> None:
        parsed = urlparse(self.path)
        route = parsed.path
        if route == "/video":
            if not self.config.video_path or not self.config.video_path.exists():
                self.send_error(HTTPStatus.NOT_FOUND, "Video not found")
            else:
                self.send_file(self.config.video_path, head_only=True)
        elif route in {"/", "/sensor.json", "/labels", "/api/browse_native"}:
            self.send_response(HTTPStatus.OK)
            self.end_headers()
        else:
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        route = parsed.path
        if route == "/":
            self.send_text(app_html(self.config), "text/html; charset=utf-8")
        elif route == "/sensor.json":
            if not self.config.csv_path or not self.config.csv_path.exists():
                self.send_json({"points": [], "peaks": [], "audio_points": [], "audio_peaks": []})
            else:
                self.send_json(
                    {
                        "points": self.points,
                        "peaks": self.peaks,
                        "audio_points": self.audio_points,
                        "audio_peaks": self.audio_peaks,
                        "estimated_offset": self.config.offset_seconds,
                        "offset_info": self.offset_info,
                    }
                )
        elif route == "/labels":
            if not self.config.output_path:
                self.send_json([])
            else:
                self.send_json(read_events(self.config.output_path))
        elif route == "/video":
            if not self.config.video_path or not self.config.video_path.exists():
                self.send_error(HTTPStatus.NOT_FOUND, "Video not found")
            else:
                self.send_file(self.config.video_path)
        elif route == "/api/browse_native":
            query = parse_qs(parsed.query)
            file_type = query.get("type", [None])[0]
            prompt = "Wähle eine Video-Datei" if file_type == "video" else "Wähle eine CSV-Datei"
            path = select_file_native(prompt, file_type)
            self.send_json({"path": path})
        elif route == "/favicon.ico":
            self.send_response(HTTPStatus.NO_CONTENT)
            self.end_headers()
        else:
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self) -> None:
        route = urlparse(self.path).path
        body = self.read_json_body()

        if route == "/api/sync_claps":
            sync_type = body.get("sync_type", "start")
            if not self.config.csv_path or not self.config.csv_path.exists():
                self.send_json({"success": False, "error": "CSV-Datei nicht geladen."})
                return
            if not self.config.video_path or not self.config.video_path.exists():
                self.send_json({"success": False, "error": "Video-Datei nicht geladen."})
                return

            try:
                raw_sensor_rows = read_raw_sensor_rows(self.config.csv_path)

                audio_pts = self.audio_points
                if not audio_pts:
                    audio_pts = extract_audio_envelope(self.config.video_path)

                if not audio_pts:
                    self.send_json({"success": False, "error": "Audio-Spur konnte nicht aus dem Video extrahiert werden."})
                    return

                csv_duration = raw_sensor_rows[-1]["csv_t"] if raw_sensor_rows else 0
                video_duration = audio_pts[-1]["video_t"] if audio_pts else 0

                search_dur = 35.0
                if sync_type == "start":
                    v_start, v_end = 0.0, min(search_dur, video_duration)
                    c_start, c_end = 0.0, min(search_dur, csv_duration)
                else:
                    v_start, v_end = max(0.0, video_duration - search_dur), video_duration
                    c_start, c_end = max(0.0, csv_duration - search_dur), csv_duration

                video_claps = find_triple_clap(audio_pts, "video_t", "amp", v_start, v_end)
                csv_claps = find_triple_clap(raw_sensor_rows, "csv_t", "acc", c_start, c_end)

                if not video_claps or not csv_claps:
                    err_msg = []
                    if not video_claps:
                        err_msg.append("Drei Klatscher am Anfang/Ende des Videos (Audio) nicht gefunden.")
                    if not csv_claps:
                        err_msg.append("Drei Klatscher am Anfang/Ende der Apple Watch CSV (Sensor) nicht gefunden.")
                    self.send_json({"success": False, "error": " ".join(err_msg)})
                    return

                v_avg = sum(video_claps) / 3.0
                c_avg = sum(csv_claps) / 3.0
                new_offset = round(c_avg - v_avg, 3)

                new_config = AppConfig(
                    csv_path=self.config.csv_path,
                    video_path=self.config.video_path,
                    output_path=self.config.output_path,
                    offset_seconds=new_offset
                )
                LabelHandler.config = new_config

                # Recalculate sensor rows with new offset
                sensor_rows = apply_offset_to_rows(raw_sensor_rows, new_offset)
                LabelHandler.points = smooth_rows(downsample_rows(sensor_rows, target_points=16000))
                sensor_peaks = detect_peaks(sensor_rows)
                LabelHandler.peaks = build_audio_based_suggestions(sensor_peaks, self.audio_peaks)

                self.send_json({
                    "success": True,
                    "offset": new_offset,
                    "video_claps": video_claps,
                    "csv_claps": csv_claps
                })
            except Exception as e:
                self.send_json({"success": False, "error": f"Fehler bei der Synchronisation: {e}"})
            return

        if route == "/api/load_config":
            video_path_str = body.get("video_path")
            csv_path_str = body.get("csv_path")
            offset_val = parse_float(str(body.get("offset_seconds", "0")))

            if not video_path_str or not csv_path_str:
                self.send_json({"success": False, "error": "Sowohl Video- als auch CSV-Pfad muessen angegeben werden."})
                return

            video_p = Path(video_path_str).expanduser().resolve()
            csv_p = Path(csv_path_str).expanduser().resolve()

            if not video_p.exists() or not video_p.is_file():
                self.send_json({"success": False, "error": f"Video-Datei existiert nicht: {video_path_str}"})
                return
            if not csv_p.exists() or not csv_p.is_file():
                self.send_json({"success": False, "error": f"CSV-Datei existiert nicht: {csv_path_str}"})
                return

            output_path_str = body.get("output_path")
            requested_output = Path(output_path_str).expanduser() if output_path_str else None
            output_p = resolve_events_output_path(csv_p, requested_output)

            try:
                print(f"Loading sensor/audio data from {csv_p} and {video_p}")
                points, peaks, audio_points, audio_peaks, estimated_offset, offset_info = analyze_media(csv_p, video_p, offset_val)
                ensure_events_file(output_p)
                new_config = AppConfig(
                    csv_path=csv_p,
                    video_path=video_p,
                    output_path=output_p,
                    offset_seconds=estimated_offset
                )
                LabelHandler.config = new_config
                LabelHandler.points = points
                LabelHandler.peaks = peaks
                LabelHandler.audio_points = audio_points
                LabelHandler.audio_peaks = audio_peaks
                LabelHandler.offset_info = offset_info
                save_last_dataset(video_p, csv_p, output_p, estimated_offset)
                self.send_json(
                    {
                        "success": True,
                        "output_path": str(output_p),
                        "estimated_offset": estimated_offset,
                        "offset_info": offset_info,
                    }
                )
            except Exception as e:
                self.send_json({"success": False, "error": f"Fehler beim Laden der CSV: {e}"})
            return

        if not self.config.output_path:
            self.send_error(HTTPStatus.BAD_REQUEST, "Kein Output-Pfad konfiguriert")
            return

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
    parser.add_argument("--csv", type=Path, default=None, help="Apple Watch SensorLog CSV path.")
    parser.add_argument("--video", type=Path, default=None, help="Video file path.")
    parser.add_argument("--output", type=Path, default=None, help="Event label CSV output path.")
    parser.add_argument("--offset", type=float, default=None, help="Seconds: csv_time = video_time + offset.")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind.")
    parser.add_argument("--port", type=int, default=8765, help="Port to bind.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    last = load_last_dataset()

    # Vorrang: explizite CLI-Argumente > zuletzt geladenes Datenset > fest eingebaute Defaults.
    use_last = (
        args.csv is None
        and args.video is None
        and bool(last.get("csv_path"))
        and bool(last.get("video_path"))
        and Path(last["csv_path"]).expanduser().exists()
        and Path(last["video_path"]).expanduser().exists()
    )

    if use_last:
        csv_path = Path(last["csv_path"]).expanduser().resolve()
        video_path = Path(last["video_path"]).expanduser().resolve()
        requested_output = Path(last["output_path"]).expanduser() if last.get("output_path") else None
        offset = parse_float(str(last.get("offset_seconds", DEFAULT_OFFSET_SECONDS)))
        print(f"Using last loaded dataset: {csv_path.name} / {video_path.name}")
    else:
        csv_path = (args.csv or DEFAULT_CSV).expanduser().resolve()
        video_path = (args.video or DEFAULT_VIDEO).expanduser().resolve()
        requested_output = args.output.expanduser() if args.output else None
        offset = args.offset if args.offset is not None else DEFAULT_OFFSET_SECONDS

    config = AppConfig(
        csv_path=csv_path,
        video_path=video_path,
        output_path=resolve_events_output_path(csv_path, requested_output),
        offset_seconds=offset,
    )

    csv_exists = config.csv_path.exists()
    video_exists = config.video_path.exists()

    points, peaks, audio_points, audio_peaks = [], [], [], []
    offset_info = {"source": "fallback", "matches": 0, "confidence": 0.0}
    if csv_exists and video_exists:
        print(f"Loading sensor/audio data from {config.csv_path} and {config.video_path}")
        try:
            points, peaks, audio_points, audio_peaks, estimated_offset, offset_info = analyze_media(
                config.csv_path,
                config.video_path,
                config.offset_seconds,
            )
            config = AppConfig(
                csv_path=config.csv_path,
                video_path=config.video_path,
                output_path=config.output_path,
                offset_seconds=estimated_offset,
            )
            print(
                f"Loaded {len(points)} chart points, {len(audio_points)} audio points, "
                f"{len(peaks)} peak candidates; offset={estimated_offset:.3f}s ({offset_info.get('source')})"
            )
        except Exception as e:
            print(f"Error loading sensor/audio data: {e}")
    elif csv_exists:
        print(f"Loading sensor data from {config.csv_path}")
        try:
            points, peaks, _ = read_sensor_rows(config.csv_path, config.offset_seconds)
            print(f"Loaded {len(points)} chart points and {len(peaks)} peak candidates")
        except Exception as e:
            print(f"Error loading sensor data: {e}")
    else:
        print(f"Warning: CSV file not found: {config.csv_path}")

    if not video_exists:
        print(f"Warning: Video file not found: {config.video_path}")

    if csv_exists:
        ensure_events_file(config.output_path)

    handler = LabelHandler
    handler.config = config
    handler.points = points
    handler.peaks = peaks
    handler.audio_points = audio_points
    handler.audio_peaks = audio_peaks
    handler.offset_info = offset_info

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
