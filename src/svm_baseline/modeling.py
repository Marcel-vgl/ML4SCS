"""Model fitting, evaluation, and artifact export for the SVM baseline."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import pickle
import warnings

import matplotlib.pyplot as plt
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.metrics import (
    ConfusionMatrixDisplay,
    accuracy_score,
    balanced_accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
)
from sklearn.model_selection import LeaveOneGroupOut
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC

from src.random_forest_baseline.data import PreparedDataset

from .config import SVMBaselineConfig


@dataclass
class EvaluationResult:
    """Structured evaluation outputs for reuse in scripts and notebooks."""

    overall_metrics: dict[str, float]
    classification_report: pd.DataFrame
    confusion_matrix: pd.DataFrame
    fold_metrics: pd.DataFrame
    predictions: pd.DataFrame


def build_pipeline(config: SVMBaselineConfig) -> Pipeline:
    """Build the imputation + scaling + SVM baseline pipeline."""
    return Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            ("model", SVC(**config.svm_params)),
        ]
    )


def evaluate_grouped_dataset(dataset: PreparedDataset, config: SVMBaselineConfig) -> EvaluationResult:
    """Evaluate the SVM baseline by leaving one labeled recording session out per fold."""
    splitter = LeaveOneGroupOut()
    unique_groups = dataset.groups.nunique()
    if unique_groups < 2:
        raise ValueError("Grouped evaluation needs at least two distinct sessions.")

    fold_rows: list[dict[str, object]] = []
    prediction_rows: list[pd.DataFrame] = []

    for fold_number, (train_index, test_index) in enumerate(
        splitter.split(dataset.features, dataset.labels, dataset.groups),
        start=1,
    ):
        pipeline = build_pipeline(config)
        X_train = dataset.features.iloc[train_index]
        y_train = dataset.labels.iloc[train_index]
        X_test = dataset.features.iloc[test_index]
        y_test = dataset.labels.iloc[test_index]
        pipeline.fit(X_train, y_train)
        predictions = pipeline.predict(X_test)

        test_session = dataset.groups.iloc[test_index].iloc[0]
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="y_pred contains classes not in y_true")
            fold_accuracy = float(accuracy_score(y_test, predictions))
            fold_balanced_accuracy = float(balanced_accuracy_score(y_test, predictions))
            fold_macro_precision = float(
                precision_score(y_test, predictions, average="macro", zero_division=0)
            )
            fold_macro_recall = float(recall_score(y_test, predictions, average="macro", zero_division=0))
            fold_macro_f1 = float(f1_score(y_test, predictions, average="macro", zero_division=0))
            fold_weighted_f1 = float(f1_score(y_test, predictions, average="weighted", zero_division=0))
        fold_rows.append(
            {
                "fold": fold_number,
                "test_session": test_session,
                "train_events": int(len(train_index)),
                "test_events": int(len(test_index)),
                "accuracy": fold_accuracy,
                "balanced_accuracy": fold_balanced_accuracy,
                "macro_precision": fold_macro_precision,
                "macro_recall": fold_macro_recall,
                "macro_f1": fold_macro_f1,
                "weighted_f1": fold_weighted_f1,
            }
        )

        fold_predictions = dataset.metadata.iloc[test_index].copy()
        fold_predictions["y_true"] = y_test.to_numpy()
        fold_predictions["y_pred"] = predictions
        fold_predictions["fold"] = fold_number
        prediction_rows.append(fold_predictions)

    all_predictions = pd.concat(prediction_rows, ignore_index=True)
    y_true = all_predictions["y_true"]
    y_pred = all_predictions["y_pred"]
    labels = dataset.selected_labels

    report = classification_report(y_true, y_pred, labels=labels, output_dict=True, zero_division=0)
    report_frame = pd.DataFrame(report).transpose().reset_index().rename(columns={"index": "label"})
    matrix = confusion_matrix(y_true, y_pred, labels=labels)
    confusion_frame = pd.DataFrame(matrix, index=labels, columns=labels)
    fold_metrics = pd.DataFrame(fold_rows)

    overall_metrics = {
        "event_count": float(len(all_predictions)),
        "feature_count": float(dataset.features.shape[1]),
        "session_count": float(unique_groups),
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "balanced_accuracy": float(balanced_accuracy_score(y_true, y_pred)),
        "macro_precision": float(precision_score(y_true, y_pred, average="macro", zero_division=0)),
        "macro_recall": float(recall_score(y_true, y_pred, average="macro", zero_division=0)),
        "macro_f1": float(f1_score(y_true, y_pred, average="macro", zero_division=0)),
        "weighted_f1": float(f1_score(y_true, y_pred, average="weighted", zero_division=0)),
    }

    return EvaluationResult(
        overall_metrics=overall_metrics,
        classification_report=report_frame,
        confusion_matrix=confusion_frame,
        fold_metrics=fold_metrics,
        predictions=all_predictions,
    )


def fit_final_model(dataset: PreparedDataset, config: SVMBaselineConfig) -> tuple[Pipeline, dict[str, object]]:
    """Fit the SVM pipeline on all currently selected labeled events."""
    pipeline = build_pipeline(config)
    pipeline.fit(dataset.features, dataset.labels)
    model = pipeline.named_steps["model"]
    model_metadata = {
        "model_type": type(model).__name__,
        "kernel": config.kernel,
        "classes": list(model.classes_),
        "support_vector_count": int(model.support_vectors_.shape[0]),
        "support_vectors_per_class": {
            str(label): int(count) for label, count in zip(model.classes_, model.n_support_, strict=True)
        },
    }
    return pipeline, model_metadata


def save_evaluation_artifacts(
    output_dir: Path,
    config: SVMBaselineConfig,
    dataset: PreparedDataset,
    result: EvaluationResult,
) -> None:
    """Persist metrics, confusion matrix, predictions, and config for comparisons."""
    output_dir.mkdir(parents=True, exist_ok=True)
    result.classification_report.to_csv(output_dir / "classification_report.csv", index=False)
    result.confusion_matrix.to_csv(output_dir / "confusion_matrix.csv", index=True)
    result.fold_metrics.to_csv(output_dir / "fold_metrics.csv", index=False)
    result.predictions.to_csv(output_dir / "predictions.csv", index=False)
    dataset.label_summary.to_csv(output_dir / "label_summary.csv", index=False)

    save_confusion_matrix_plot(
        result.confusion_matrix,
        output_path=output_dir / "confusion_matrix.png",
    )

    metrics_payload = {
        "config": config.to_dict(),
        "selected_labels": dataset.selected_labels,
        "overall_metrics": result.overall_metrics,
    }
    with (output_dir / "metrics.json").open("w", encoding="utf-8") as handle:
        json.dump(metrics_payload, handle, indent=2, ensure_ascii=False)


def save_confusion_matrix_plot(
    confusion_frame: pd.DataFrame,
    output_path: Path | None = None,
) -> plt.Figure:
    """Create a confusion-matrix plot and optionally save it."""
    labels = list(confusion_frame.index)
    matrix = confusion_frame.to_numpy()
    size = max(6.0, len(labels) * 1.3)
    figure, axis = plt.subplots(figsize=(size, size))
    display = ConfusionMatrixDisplay(confusion_matrix=matrix, display_labels=labels)
    display.plot(ax=axis, colorbar=False, cmap="Oranges", xticks_rotation=35, values_format="d")
    axis.set_title("SVM Baseline")
    figure.tight_layout()

    if output_path is not None:
        figure.savefig(output_path, dpi=180, bbox_inches="tight")
    return figure


def save_model_bundle(
    output_path: Path,
    config: SVMBaselineConfig,
    dataset: PreparedDataset,
    pipeline: Pipeline,
    model_metadata: dict[str, object],
) -> None:
    """Serialize the trained SVM model and the metadata needed to reuse it."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "pipeline": pipeline,
        "config": config.to_dict(),
        "feature_columns": list(dataset.features.columns),
        "selected_labels": dataset.selected_labels,
        "sensor_columns": dataset.sensor_columns,
        "model_metadata": model_metadata,
    }
    with output_path.open("wb") as handle:
        pickle.dump(payload, handle)
