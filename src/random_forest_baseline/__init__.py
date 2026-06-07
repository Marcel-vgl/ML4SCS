"""Configurable Random-Forest baseline for labeled tennis stroke events."""

from .config import BaselineConfig
from .data import PreparedDataset, prepare_dataset
from .modeling import (
    EvaluationResult,
    evaluate_grouped_dataset,
    fit_final_model,
    save_confusion_matrix_plot,
    save_evaluation_artifacts,
    save_model_bundle,
)

__all__ = [
    "BaselineConfig",
    "EvaluationResult",
    "PreparedDataset",
    "evaluate_grouped_dataset",
    "fit_final_model",
    "prepare_dataset",
    "save_confusion_matrix_plot",
    "save_evaluation_artifacts",
    "save_model_bundle",
]
