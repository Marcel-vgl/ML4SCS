"""Runtime evaluation for the frozen v_r_v1 model artifact."""

from __future__ import annotations

import csv
from dataclasses import dataclass
import json
from pathlib import Path
import warnings

import matplotlib.pyplot as plt
import pandas as pd
from sklearn.metrics import (
    ConfusionMatrixDisplay,
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
)

from src.stroke_model import (
    detect_energy_peaks,
    load_model,
    load_sensor_table,
    nearest_peak_time,
    normalize_label,
    predict_one,
)

from .config import VRModelEvaluationConfig

try:
    from sklearn.exceptions import InconsistentVersionWarning
except Exception:  # pragma: no cover - defensive fallback for older sklearn versions
    InconsistentVersionWarning = UserWarning


@dataclass
class FrozenModelEvaluationResult:
    """Structured outputs from evaluating the frozen v_r_v1 artifact."""

    overall_metrics: dict[str, object]
    classification_report: pd.DataFrame
    confusion_matrix: pd.DataFrame
    session_metrics: pd.DataFrame
    predictions: pd.DataFrame
    label_summary: pd.DataFrame
    feature_importances: pd.DataFrame
    model_metadata: dict[str, object]


def load_model_payload(config: VRModelEvaluationConfig) -> dict:
    """Load the frozen model payload while suppressing the sklearn version warning."""
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=InconsistentVersionWarning)
        return load_model(config.resolved_model_path)


def evaluate_frozen_model(config: VRModelEvaluationConfig) -> FrozenModelEvaluationResult:
    """Evaluate the stored v_r_v1 pickle on the available labeled Vorhand/Rueckhand events."""
    payload = load_model_payload(config)
    classes = [label for label in payload.get("classes", []) if label in config.supported_labels]
    if not classes:
        classes = list(config.supported_labels)

    predictions = build_prediction_frame(config, payload, classes)
    if predictions.empty:
        raise ValueError("No supported evaluation events were found for the frozen model.")

    y_true = predictions["true_label"]
    y_pred = predictions["prediction"]
    report = classification_report(y_true, y_pred, labels=classes, output_dict=True, zero_division=0)
    report_frame = pd.DataFrame(report).transpose().reset_index().rename(columns={"index": "label"})
    matrix = confusion_matrix(y_true, y_pred, labels=classes)
    confusion_frame = pd.DataFrame(matrix, index=classes, columns=classes)

    session_metrics = build_session_metrics(predictions, classes)
    label_summary = build_label_summary(predictions, classes)
    feature_importances = build_feature_importances(payload)
    model_metadata = build_model_metadata(payload)
    overall_metrics = build_overall_metrics(predictions, payload, classes)

    return FrozenModelEvaluationResult(
        overall_metrics=overall_metrics,
        classification_report=report_frame,
        confusion_matrix=confusion_frame,
        session_metrics=session_metrics,
        predictions=predictions,
        label_summary=label_summary,
        feature_importances=feature_importances,
        model_metadata=model_metadata,
    )


def build_prediction_frame(
    config: VRModelEvaluationConfig,
    payload: dict,
    classes: list[str],
) -> pd.DataFrame:
    """Build one evaluation row per labeled Vorhand/Rueckhand event."""
    rows: list[dict[str, object]] = []

    for events_path in sorted(config.resolved_label_dir.glob("*_events.csv")):
        sensor_path = matching_sensor_csv(config, events_path)
        if not sensor_path.exists():
            continue

        table = load_sensor_table(sensor_path)
        peaks = detect_energy_peaks(table, min_spacing_s=config.peak_min_spacing_s)

        with events_path.open(newline="", encoding="utf-8-sig") as handle:
            for event in csv.DictReader(handle):
                true_label = normalize_label(event.get("label_name"))
                if true_label not in config.supported_labels:
                    continue
                try:
                    event_time_s = float(event["csv_time_s"])
                except (KeyError, TypeError, ValueError):
                    continue

                center_time_s = nearest_peak_time(
                    peaks,
                    event_time_s,
                    max_distance_s=config.max_peak_distance_s,
                )
                try:
                    prediction = predict_one(payload, table, center_time_s)
                except ValueError:
                    continue

                row = {
                    "events_csv": events_path.name,
                    "source_csv": sensor_path.name,
                    "event_time_s": round(event_time_s, 4),
                    "window_center_s": round(float(center_time_s), 4),
                    "time_shift_s": round(float(center_time_s - event_time_s), 4),
                    "used_detected_peak": abs(center_time_s - event_time_s) > 1e-9,
                    "true_label": true_label,
                    "prediction": prediction["prediction"],
                    "confidence": float(prediction["confidence"]),
                }
                for label in classes:
                    row[f"prob_{label}"] = float(prediction["probabilities"].get(label, 0.0))
                rows.append(row)

    return pd.DataFrame(rows)


def matching_sensor_csv(config: VRModelEvaluationConfig, events_path: Path) -> Path:
    """Resolve the raw sensor CSV that matches a given events CSV."""
    stem = events_path.name.removesuffix("_events.csv")
    return config.resolved_data_dir / f"{stem}.csv"


def build_session_metrics(predictions: pd.DataFrame, classes: list[str]) -> pd.DataFrame:
    """Aggregate per-session metrics for quick comparisons."""
    rows: list[dict[str, object]] = []
    for session_name, frame in predictions.groupby("events_csv"):
        y_true = frame["true_label"]
        y_pred = frame["prediction"]
        rows.append(
            {
                "events_csv": session_name,
                "source_csv": frame["source_csv"].iloc[0],
                "event_count": int(len(frame)),
                "accuracy": float(accuracy_score(y_true, y_pred)),
                "macro_precision": float(precision_score(y_true, y_pred, labels=classes, average="macro", zero_division=0)),
                "macro_recall": float(recall_score(y_true, y_pred, labels=classes, average="macro", zero_division=0)),
                "macro_f1": float(f1_score(y_true, y_pred, labels=classes, average="macro", zero_division=0)),
                "avg_abs_time_shift_s": float(frame["time_shift_s"].abs().mean()),
            }
        )
    return pd.DataFrame(rows).sort_values("events_csv").reset_index(drop=True)


def build_label_summary(predictions: pd.DataFrame, classes: list[str]) -> pd.DataFrame:
    """Summarize true label counts per session and overall."""
    rows: list[dict[str, object]] = []
    for session_name, frame in predictions.groupby("events_csv"):
        counts = frame["true_label"].value_counts()
        row: dict[str, object] = {"events_csv": session_name, "event_count": int(len(frame))}
        for label in classes:
            row[label] = int(counts.get(label, 0))
        rows.append(row)

    overall_counts = predictions["true_label"].value_counts()
    overall_row: dict[str, object] = {"events_csv": "ALL", "event_count": int(len(predictions))}
    for label in classes:
        overall_row[label] = int(overall_counts.get(label, 0))
    rows.append(overall_row)

    return pd.DataFrame(rows)


def build_feature_importances(payload: dict) -> pd.DataFrame:
    """Extract feature importances from the stored Random-Forest payload."""
    model = payload["model"]
    importances = getattr(model, "feature_importances_", None)
    feature_names = payload.get("feature_names", [])
    if importances is None or not feature_names:
        return pd.DataFrame(columns=["feature", "importance"])

    return pd.DataFrame(
        {
            "feature": feature_names,
            "importance": importances,
        }
    ).sort_values("importance", ascending=False, ignore_index=True)


def build_model_metadata(payload: dict) -> dict[str, object]:
    """Convert the loaded payload to JSON-friendly metadata."""
    model = payload["model"]
    metadata = {
        key: value
        for key, value in payload.items()
        if key != "model"
    }
    metadata["model_type"] = type(model).__name__
    metadata["feature_count"] = int(len(payload.get("feature_names", [])))
    metadata["signal_count"] = int(len(payload.get("signal_names", [])))
    metadata["classes"] = [str(label) for label in payload.get("classes", [])]
    metadata["class_counts"] = {str(label): int(count) for label, count in payload.get("class_counts", {}).items()}
    return metadata


def build_overall_metrics(
    predictions: pd.DataFrame,
    payload: dict,
    classes: list[str],
) -> dict[str, object]:
    """Create top-level metrics and a few caveat indicators for the frozen model."""
    y_true = predictions["true_label"]
    y_pred = predictions["prediction"]
    true_counts = {label: int(count) for label, count in y_true.value_counts().items()}
    model_class_counts = {str(label): int(count) for label, count in payload.get("class_counts", {}).items()}

    return {
        "event_count": int(len(predictions)),
        "session_count": int(predictions["events_csv"].nunique()),
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "macro_precision": float(precision_score(y_true, y_pred, labels=classes, average="macro", zero_division=0)),
        "macro_recall": float(recall_score(y_true, y_pred, labels=classes, average="macro", zero_division=0)),
        "macro_f1": float(f1_score(y_true, y_pred, labels=classes, average="macro", zero_division=0)),
        "weighted_f1": float(f1_score(y_true, y_pred, labels=classes, average="weighted", zero_division=0)),
        "avg_abs_time_shift_s": float(predictions["time_shift_s"].abs().mean()),
        "predicted_class_counts": {label: int(count) for label, count in predictions["prediction"].value_counts().items()},
        "true_class_counts": true_counts,
        "model_training_samples": int(payload.get("training_samples", 0)),
        "matches_model_training_sample_count": int(len(predictions)) == int(payload.get("training_samples", -1)),
        "matches_model_class_counts": model_class_counts == true_counts,
    }


def save_evaluation_artifacts(
    output_dir: Path,
    config: VRModelEvaluationConfig,
    result: FrozenModelEvaluationResult,
) -> None:
    """Persist all evaluation outputs next to the frozen model."""
    output_dir.mkdir(parents=True, exist_ok=True)
    result.classification_report.to_csv(output_dir / "classification_report.csv", index=False)
    result.confusion_matrix.to_csv(output_dir / "confusion_matrix.csv", index=True)
    result.session_metrics.to_csv(output_dir / "session_metrics.csv", index=False)
    result.predictions.to_csv(output_dir / "predictions.csv", index=False)
    result.label_summary.to_csv(output_dir / "label_summary.csv", index=False)
    result.feature_importances.to_csv(output_dir / "feature_importances.csv", index=False)

    save_confusion_matrix_plot(result.confusion_matrix, output_dir / "confusion_matrix.png")

    with (output_dir / "model_metadata.json").open("w", encoding="utf-8") as handle:
        json.dump(result.model_metadata, handle, indent=2, ensure_ascii=False)

    with (output_dir / "metrics.json").open("w", encoding="utf-8") as handle:
        json.dump(
            {
                "config": config.to_dict(),
                "overall_metrics": result.overall_metrics,
            },
            handle,
            indent=2,
            ensure_ascii=False,
        )


def save_confusion_matrix_plot(confusion_frame: pd.DataFrame, output_path: Path | None = None) -> plt.Figure:
    """Plot and optionally save the confusion matrix for the frozen model."""
    labels = list(confusion_frame.index)
    matrix = confusion_frame.to_numpy()
    size = max(5.5, len(labels) * 1.4)
    figure, axis = plt.subplots(figsize=(size, size))
    display = ConfusionMatrixDisplay(confusion_matrix=matrix, display_labels=labels)
    display.plot(ax=axis, colorbar=False, cmap="Greens", values_format="d")
    axis.set_title("v_r_v1 Frozen Model")
    figure.tight_layout()
    if output_path is not None:
        figure.savefig(output_path, dpi=180, bbox_inches="tight")
    return figure
