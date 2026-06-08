#!/usr/bin/env python3
"""Predict Vorhand/Rueckhand strokes from Apple Watch CSV files."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from stroke_model import DEFAULT_MODEL_PATH, detect_energy_peaks, load_model, load_sensor_table, predict_one


def read_event_times(path: Path) -> list[tuple[float, dict]]:
    times: list[tuple[float, dict]] = []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            try:
                times.append((float(row["csv_time_s"]), row))
            except (KeyError, TypeError, ValueError):
                continue
    return times


def dedupe_predictions(rows: list[dict], min_gap_s: float) -> list[dict]:
    selected: list[dict] = []
    for row in sorted(rows, key=lambda item: item["confidence"], reverse=True):
        if all(abs(float(row["csv_time_s"]) - float(other["csv_time_s"])) >= min_gap_s for other in selected):
            selected.append(row)
    return sorted(selected, key=lambda item: item["csv_time_s"])


def write_predictions(path: Path, rows: list[dict], classes: list[str]) -> None:
    fields = ["csv_time_s", "prediction", "confidence", "source_score", "source", "true_label"]
    fields.extend([f"prob_{label}" for label in classes])
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            flat = {field: row.get(field, "") for field in fields}
            for label, probability in row.get("probabilities", {}).items():
                flat[f"prob_{label}"] = probability
            writer.writerow(flat)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run v_r_v1 Vorhand/Rueckhand predictions.")
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL_PATH)
    parser.add_argument("--events-csv", type=Path)
    parser.add_argument("--times", type=float, nargs="*")
    parser.add_argument("--scan", action="store_true", help="Use Offline-Labeler peak detection to find stroke windows.")
    parser.add_argument("--threshold", type=float, default=0.6)
    parser.add_argument("--step", type=float, default=0.2, help="Accepted for dashboard compatibility; peak scan ignores fixed steps.")
    parser.add_argument("--min-gap", type=float, default=0.8)
    parser.add_argument("--out", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = load_model(args.model)
    table = load_sensor_table(args.csv_path)
    classes = list(payload["classes"])
    rows: list[dict] = []

    if args.events_csv:
        for center_time, event in read_event_times(args.events_csv):
            row = predict_one(payload, table, center_time)
            row["source"] = "events_csv"
            row["source_score"] = ""
            row["true_label"] = event.get("label_name", "")
            rows.append(row)
    elif args.times:
        for center_time in args.times:
            row = predict_one(payload, table, center_time)
            row["source"] = "manual_time"
            row["source_score"] = ""
            row["true_label"] = ""
            rows.append(row)
    elif args.scan:
        for peak in detect_energy_peaks(table, min_spacing_s=max(0.1, args.min_gap)):
            row = predict_one(payload, table, float(peak["csv_time_s"]))
            if row["confidence"] < args.threshold:
                continue
            row["source"] = peak.get("source", "detect_energy_peaks")
            row["source_score"] = peak.get("score", "")
            row["true_label"] = ""
            rows.append(row)
        rows = dedupe_predictions(rows, args.min_gap)
    else:
        raise SystemExit("Use --events-csv, --times, or --scan")

    if args.out:
        write_predictions(args.out, rows, classes)
        print(f"Wrote {len(rows)} predictions to {args.out}")
    else:
        writer = csv.DictWriter(__import__("sys").stdout, fieldnames=["csv_time_s", "prediction", "confidence"])
        writer.writeheader()
        writer.writerows({key: row[key] for key in ["csv_time_s", "prediction", "confidence"]} for row in rows)


if __name__ == "__main__":
    main()
