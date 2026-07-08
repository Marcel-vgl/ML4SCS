"""Configuration handling for the SVM baseline."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class SVMBaselineConfig:
    """Editable configuration for the event-window SVM baseline."""

    data_dir: str = "Daten/Daten_Labeled"
    output_dir: str = "baseline_models/svm/output"
    model_output_path: str = "baseline_models/svm/output/svm_model.pkl"
    window_before_s: float = 0.5
    window_after_s: float = 0.5
    min_window_rows: int = 25
    labels: list[str] | None = None
    excluded_labels: list[str] = field(default_factory=lambda: ["Unsicher"])
    min_samples_per_label: int = 10
    min_sessions_per_label: int = 2
    random_state: int = 42
    kernel: str = "rbf"
    c_value: float = 2.0
    gamma: str | float = "scale"
    degree: int = 3
    coef0: float = 0.0
    class_weight: str | None = "balanced"
    probability: bool = True

    @classmethod
    def from_json(cls, path: str | Path) -> "SVMBaselineConfig":
        """Load the SVM configuration from a JSON file."""
        config_path = cls.resolve_path(path)
        with config_path.open(encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, dict):
            raise ValueError(f"{config_path} must contain a JSON object.")
        return cls(**payload)

    @staticmethod
    def resolve_path(path: str | Path) -> Path:
        """Resolve repo-relative and absolute paths consistently."""
        candidate = Path(path).expanduser()
        if candidate.is_absolute():
            return candidate
        return REPO_ROOT / candidate

    @property
    def resolved_data_dir(self) -> Path:
        return self.resolve_path(self.data_dir)

    @property
    def resolved_output_dir(self) -> Path:
        return self.resolve_path(self.output_dir)

    @property
    def resolved_model_output_path(self) -> Path:
        return self.resolve_path(self.model_output_path)

    @property
    def svm_params(self) -> dict[str, Any]:
        return {
            "kernel": self.kernel,
            "C": self.c_value,
            "gamma": self.gamma,
            "degree": self.degree,
            "coef0": self.coef0,
            "class_weight": self.class_weight,
            "probability": self.probability,
            "random_state": self.random_state,
        }

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
