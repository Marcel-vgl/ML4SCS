"""Shared feature extraction and inference utilities for tennis stroke models."""

from __future__ import annotations

import csv
import math
from bisect import bisect_left
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

import joblib
import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL_PATH = REPO_ROOT / "models" / "v_r_v1.pkl"

IMU_COLUMNS = [
    "motionUserAccelerationX(G)",
    "motionUserAccelerationY(G)",
    "motionUserAccelerationZ(G)",
    "motionRotationRateX(rad/s)",
    "motionRotationRateY(rad/s)",
    "motionRotationRateZ(rad/s)",
]

OPTIONAL_COLUMNS = [
    "accelerometerAccelerationX(G)",
    "accelerometerAccelerationY(G)",
    "accelerometerAccelerationZ(G)",
    "motionYaw(rad)",
    "motionRoll(rad)",
    "motionPitch(rad)",
]

WINDOW_BEFORE_S = 0.45
WINDOW_AFTER_S = 0.35

STROKE_LABELS = {
    "Vorhand": "Vorhand",
    "Rueckhand": "Rueckhand",
    "Rückhand": "Rueckhand",
}


@dataclass(frozen=True)
class SensorTable:
    times: np.ndarray
    values: dict[str, np.ndarray]
    peak_rows: list[dict]


def parse_float(value: str | None) -> float:
    try:
        return float(value) if value not in (None, "") else 0.0
    except (TypeError, ValueError):
        return 0.0


def normalize_label(label: str | None) -> str | None:
    label = (label or "").strip()
    return STROKE_LABELS.get(label)


def _row_time(row: dict, first_motion_time: float | None, first_logging_time: datetime | None) -> tuple[float | None, float | None, datetime | None]:
    if row.get("motionTimestamp_sinceReboot(s)"):
        motion_time = parse_float(row.get("motionTimestamp_sinceReboot(s)"))
        if first_motion_time is None:
            first_motion_time = motion_time
        return motion_time - first_motion_time, first_motion_time, first_logging_time

    if row.get("loggingTime(txt)"):
        try:
            logging_time = datetime.fromisoformat(str(row["loggingTime(txt)"]))
        except ValueError:
            return None, first_motion_time, first_logging_time
        if first_logging_time is None:
            first_logging_time = logging_time
        return (logging_time - first_logging_time).total_seconds(), first_motion_time, first_logging_time

    return None, first_motion_time, first_logging_time


def load_sensor_table(csv_path: Path) -> SensorTable:
    rows: list[dict[str, float]] = []
    with csv_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"{csv_path.name} has no CSV header")

        missing = [column for column in IMU_COLUMNS if column not in reader.fieldnames]
        if missing:
            raise ValueError(f"{csv_path.name} is missing sensor columns: {', '.join(missing)}")

        columns = [column for column in [*IMU_COLUMNS, *OPTIONAL_COLUMNS] if column in reader.fieldnames]
        first_motion_time: float | None = None
        first_logging_time: datetime | None = None

        for raw_row in reader:
            csv_time_s, first_motion_time, first_logging_time = _row_time(
                raw_row,
                first_motion_time,
                first_logging_time,
            )
            if csv_time_s is None:
                continue

            row = {"csv_time_s": float(csv_time_s)}
            for column in columns:
                row[column] = parse_float(raw_row.get(column))

            acc_x, acc_y, acc_z, gyro_x, gyro_y, gyro_z = [row[column] for column in IMU_COLUMNS]
            acc = math.sqrt(acc_x * acc_x + acc_y * acc_y + acc_z * acc_z)
            gyro = math.sqrt(gyro_x * gyro_x + gyro_y * gyro_y + gyro_z * gyro_z)
            row["user_acc_magnitude"] = acc
            row["rotation_magnitude"] = gyro
            row["score"] = acc + 0.12 * gyro
            rows.append(row)

    if not rows:
        raise ValueError(f"{csv_path.name} contains no readable sensor rows")

    times = np.array([row["csv_time_s"] for row in rows], dtype=float)
    values = {
        column: np.array([row.get(column, 0.0) for row in rows], dtype=float)
        for column in sorted(set(rows[0]) - {"csv_time_s"})
    }
    peak_rows = [
        {
            "csv_time_s": round(row["csv_time_s"], 4),
            "acc": round(row["user_acc_magnitude"], 5),
            "gyro": round(row["rotation_magnitude"], 5),
            "score": round(row["score"], 5),
        }
        for row in rows
    ]
    return SensorTable(times=times, values=values, peak_rows=peak_rows)


def downsample_peak_rows(rows: list[dict], target_points: int = 16000) -> list[dict]:
    if len(rows) <= target_points:
        return rows

    bucket_size = math.ceil(len(rows) / target_points)
    points: list[dict] = []
    for start in range(0, len(rows), bucket_size):
        bucket = rows[start : start + bucket_size]
        points.append(max(bucket, key=lambda item: item["score"]))
    return points


def smooth_peak_rows(rows: list[dict], window: int = 7) -> list[dict]:
    if window < 2 or len(rows) < window:
        return rows

    half = window // 2
    smoothed: list[dict] = []
    for index, row in enumerate(rows):
        lo = max(0, index - half)
        hi = min(len(rows), index + half + 1)
        out = dict(row)
        for key in ("acc", "gyro", "score"):
            out[key] = sum(float(rows[j].get(key, 0.0) or 0.0) for j in range(lo, hi)) / (hi - lo)
        smoothed.append(out)
    return smoothed


def average_window(rows: list[dict], index: int, key: str, radius: int) -> float:
    start = max(0, index - radius)
    end = min(len(rows) - 1, index + radius)
    values = [float(rows[i].get(key, 0.0) or 0.0) for i in range(start, end + 1)]
    return sum(values) / len(values) if values else 0.0


def robust_max(values: Iterable[float], fallback: float = 1.0) -> float:
    sorted_values = sorted(float(value) for value in values if float(value) > 0)
    if not sorted_values:
        return fallback
    index = min(len(sorted_values) - 1, int(len(sorted_values) * 0.98))
    return max(sorted_values[index], fallback)


def _energy_peak_clusters(
    table: SensorTable,
    mode: str = "contrast",
    threshold: float | None = None,
    cluster_gap_s: float = 0.18,
    min_peak_gap_s: float = 0.40,
) -> list[dict]:
    """Detect clustered motion-energy peaks in a sensor table."""
    rows = smooth_peak_rows(downsample_peak_rows(table.peak_rows))
    series: list[dict] = []

    for index, point in enumerate(rows):
        prev = rows[max(0, index - 1)]
        acc = float(point.get("acc", 0.0) or 0.0)
        gyro = float(point.get("gyro", 0.0) or 0.0)
        acc_value = acc
        gyro_value = gyro
        energy_value = float(point.get("score", 0.0) or 0.0)

        if mode == "smooth":
            acc_value = average_window(rows, index, "acc", 4)
            gyro_value = average_window(rows, index, "gyro", 4)
            energy_value = acc_value + 0.12 * gyro_value
        elif mode == "contrast":
            acc_base = average_window(rows, index, "acc", 18)
            gyro_base = average_window(rows, index, "gyro", 18)
            acc_value = max(0.0, acc - acc_base)
            gyro_value = max(0.0, gyro - gyro_base)
            energy_value = acc_value + 0.16 * gyro_value
        elif mode == "energy":
            smooth_acc = average_window(rows, index, "acc", 3)
            smooth_gyro = average_window(rows, index, "gyro", 3)
            acc_value = smooth_acc
            gyro_value = smooth_gyro
            energy_value = smooth_acc + 0.18 * smooth_gyro
        elif mode == "impulse":
            acc_value = abs(acc - float(prev.get("acc", 0.0) or 0.0))
            gyro_value = abs(gyro - float(prev.get("gyro", 0.0) or 0.0))
            energy_value = acc_value + 0.22 * gyro_value

        series.append(
            {
                "csv_time_s": float(point["csv_time_s"]),
                "acc": acc_value,
                "gyro": gyro_value,
                "energy": energy_value,
            }
        )

    if not series:
        return []

    max_energy = robust_max((point["energy"] for point in series), 1.0)
    active_threshold = threshold if threshold is not None else (0.36 if mode == "impulse" else 0.48)
    clusters: list[dict] = []
    current: dict | None = None
    last_active_time: float | None = None

    for point in series:
        value = min(float(point["energy"]) / max_energy, 1.0)
        if value < active_threshold:
            continue
        csv_time_s = float(point["csv_time_s"])
        if current is not None and last_active_time is not None and (csv_time_s - last_active_time) <= cluster_gap_s:
            if value > current["score"]:
                current["score"] = value
                current["csv_time_s"] = csv_time_s
        else:
            current = {"csv_time_s": csv_time_s, "score": value}
            clusters.append(current)
        last_active_time = csv_time_s

    merged: list[dict] = []
    for cluster in sorted(clusters, key=lambda item: item["csv_time_s"]):
        last = merged[-1] if merged else None
        if last and (cluster["csv_time_s"] - last["csv_time_s"]) < min_peak_gap_s:
            if cluster["score"] > last["score"]:
                last["csv_time_s"] = cluster["csv_time_s"]
                last["score"] = cluster["score"]
        else:
            merged.append(dict(cluster))

    return [
        {
            "csv_time_s": round(float(cluster["csv_time_s"]), 4),
            "score": round(float(cluster["score"]), 5),
            "source": f"detect_energy_peaks_{mode}",
        }
        for cluster in merged
    ]


def detect_energy_peaks(
    table: SensorTable,
    limit: int = 220,
    min_spacing_s: float = 0.45,
) -> list[dict]:
    """Detect candidate stroke times from clustered motion-energy peaks."""
    peaks = _energy_peak_clusters(table, mode="contrast", min_peak_gap_s=min_spacing_s)
    return peaks[:limit]


def nearest_peak_time(peaks: list[dict], target_time_s: float, max_distance_s: float = 0.5) -> float:
    if not peaks:
        return target_time_s

    times = [float(peak["csv_time_s"]) for peak in peaks]
    index = bisect_left(times, target_time_s)
    nearest = target_time_s
    distance = float("inf")
    for candidate_index in (index - 1, index):
        if 0 <= candidate_index < len(times):
            candidate_distance = abs(times[candidate_index] - target_time_s)
            if candidate_distance < distance:
                distance = candidate_distance
                nearest = times[candidate_index]
    return nearest if distance <= max_distance_s else target_time_s


def feature_names(signal_names: Iterable[str]) -> list[str]:
    stats = ("mean", "std", "min", "max", "ptp", "median", "energy")
    return [f"{signal}__{stat}" for signal in signal_names for stat in stats]


def extract_features(
    table: SensorTable,
    center_time_s: float,
    before_s: float = WINDOW_BEFORE_S,
    after_s: float = WINDOW_AFTER_S,
    signal_names: list[str] | None = None,
) -> tuple[np.ndarray, list[str]]:
    if signal_names is None:
        signal_names = sorted(table.values)

    start = center_time_s - before_s
    end = center_time_s + after_s
    mask = (table.times >= start) & (table.times <= end)
    if int(mask.sum()) < 3:
        raise ValueError(f"Not enough sensor rows around {center_time_s:.3f}s")

    features: list[float] = []
    for signal in signal_names:
        values = table.values.get(signal)
        if values is None:
            window_values = np.zeros(int(mask.sum()), dtype=float)
        else:
            window_values = values[mask]
        features.extend(
            [
                float(np.mean(window_values)),
                float(np.std(window_values)),
                float(np.min(window_values)),
                float(np.max(window_values)),
                float(np.ptp(window_values)),
                float(np.median(window_values)),
                float(np.mean(window_values * window_values)),
            ]
        )

    return np.array(features, dtype=float), feature_names(signal_names)


def predict_one(model_payload: dict, table: SensorTable, center_time_s: float) -> dict:
    signal_names = model_payload["signal_names"]
    vector, _ = extract_features(
        table,
        center_time_s,
        before_s=float(model_payload["window_before_s"]),
        after_s=float(model_payload["window_after_s"]),
        signal_names=signal_names,
    )
    model = model_payload["model"]
    classes = list(model_payload["classes"])
    probabilities = model.predict_proba([vector])[0]
    best_index = int(np.argmax(probabilities))
    return {
        "csv_time_s": round(float(center_time_s), 4),
        "prediction": classes[best_index],
        "confidence": round(float(probabilities[best_index]), 4),
        "probabilities": {classes[index]: round(float(probability), 4) for index, probability in enumerate(probabilities)},
    }


def load_model(model_path: Path = DEFAULT_MODEL_PATH) -> dict:
    if not model_path.exists():
        raise FileNotFoundError(f"Model not found: {model_path}")
    return joblib.load(model_path)
