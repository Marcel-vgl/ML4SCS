"""Configurable SVM baseline for labeled tennis stroke events."""

from .config import SVMBaselineConfig
from .modeling import (
    EvaluationResult,
    evaluate_grouped_dataset,
    fit_final_model,
    save_confusion_matrix_plot,
    save_evaluation_artifacts,
    save_model_bundle,
)

__all__ = [
    "EvaluationResult",
    "SVMBaselineConfig",
    "evaluate_grouped_dataset",
    "fit_final_model",
    "save_confusion_matrix_plot",
    "save_evaluation_artifacts",
    "save_model_bundle",
]
