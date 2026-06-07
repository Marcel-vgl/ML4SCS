#!/usr/bin/env python3
"""Train the Vorhand/Rueckhand stroke model."""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
from sklearn.model_selection import train_test_split

from stroke_model import (
    DEFAULT_MODEL_PATH,
    REPO_ROOT,
    WINDOW_AFTER_S,
    WINDOW_BEFORE_S,
    extract_features,
    load_sensor_table,
    nearest_peak_time,
    normalize_label,
    offline_labeler_peaks,
)


DATA_DIR = REPO_ROOT / "Daten"
LABEL_DIR = REPO_ROOT / "labels"


def label_files() -> list[Path]:
    return sorted(LABEL_DIR.glob("*_events.csv"))


def matching_sensor_csv(events_path: Path) -> Path:
    stem = events_path.name.removesuffix("_events.csv")
    return DATA_DIR / f"{stem}.csv"


def build_dataset() -> tuple[np.ndarray, np.ndarray, list[str], list[dict], list[str]]:
    features: list[np.ndarray] = []
    labels: list[str] = []
    rows: list[dict] = []
    signal_names: list[str] | None = None

    for events_path in label_files():
        sensor_path = matching_sensor_csv(events_path)
        if not sensor_path.exists():
            continue

        table = load_sensor_table(sensor_path)
        peaks = offline_labeler_peaks(table)
        with events_path.open(newline="", encoding="utf-8-sig") as handle:
            for event in csv.DictReader(handle):
                label = normalize_label(event.get("label_name"))
                if label is None:
                    continue
                try:
                    event_time = float(event["csv_time_s"])
                except (KeyError, TypeError, ValueError):
                    continue
                center_time = nearest_peak_time(peaks, event_time)
                try:
                    vector, names = extract_features(table, center_time, WINDOW_BEFORE_S, WINDOW_AFTER_S, signal_names)
                except ValueError:
                    continue
                if signal_names is None:
                    signal_names = sorted(table.values)
                features.append(vector)
                labels.append(label)
                rows.append(
                    {
                        "source_csv": sensor_path.name,
                        "events_csv": events_path.name,
                        "event_time_s": round(event_time, 4),
                        "window_center_s": round(center_time, 4),
                        "label": label,
                    }
                )

    if not features or signal_names is None:
        raise RuntimeError("No Vorhand/Rueckhand training samples found")

    return np.vstack(features), np.array(labels), names, rows, signal_names


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train v_r_v1 Vorhand/Rueckhand model.")
    parser.add_argument("--out", type=Path, default=DEFAULT_MODEL_PATH)
    parser.add_argument("--random-state", type=int, default=42)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    x, y, names, rows, signal_names = build_dataset()
    stratify = y if min(Counter(y).values()) >= 2 else None
    x_train, x_test, y_train, y_test = train_test_split(
        x,
        y,
        test_size=0.25,
        random_state=args.random_state,
        stratify=stratify,
    )

    model = RandomForestClassifier(
        n_estimators=400,
        class_weight="balanced",
        random_state=args.random_state,
        n_jobs=-1,
    )
    model.fit(x_train, y_train)
    y_pred = model.predict(x_test)

    class_counts = {str(label): int(count) for label, count in Counter(y).items()}
    payload = {
        "name": "v_r_v1",
        "model": model,
        "classes": [str(label) for label in model.classes_],
        "feature_names": names,
        "signal_names": signal_names,
        "window_before_s": WINDOW_BEFORE_S,
        "window_after_s": WINDOW_AFTER_S,
        "training_samples": len(rows),
        "class_counts": class_counts,
        "source": "Event labels filtered to Vorhand/Rueckhand; windows centered on Offline-Labeler peaks when available.",
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(payload, args.out)

    print(f"saved_model={args.out}")
    print(f"samples={len(rows)}")
    print(f"features={x.shape[1]}")
    print(f"class_counts={class_counts}")
    print(f"accuracy={accuracy_score(y_test, y_pred):.4f}")
    print("confusion_matrix_labels=" + ",".join(model.classes_))
    print(confusion_matrix(y_test, y_pred, labels=model.classes_))
    print(classification_report(y_test, y_pred, labels=model.classes_, zero_division=0))


if __name__ == "__main__":
    main()
