"""Configuration handling for the Random-Forest baseline."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class BaselineConfig:
    """Editable configuration for the event-window Random-Forest baseline."""

    data_dir: str = "Daten/Daten_Labeled"
    output_dir: str = "baseline_models/random_forest/output"
    model_output_path: str = "baseline_models/random_forest/output/random_forest_model.pkl"
    window_before_s: float = 0.5
    window_after_s: float = 0.5
    min_window_rows: int = 25
    labels: list[str] | None = None
    label_aliases: dict[str, str] = field(default_factory=dict)
    excluded_labels: list[str] = field(default_factory=lambda: ["Unsicher"])
    min_samples_per_label: int = 10
    min_sessions_per_label: int = 2
    random_state: int = 42
    n_estimators: int = 400
    max_depth: int | None = None
    min_samples_split: int = 2
    min_samples_leaf: int = 2
    max_features: str | float | int | None = "sqrt"
    criterion: str = "gini"
    class_weight: str | None = "balanced_subsample"

    @classmethod
    def from_json(cls, path: str | Path) -> "BaselineConfig":
        """Load the baseline configuration from a JSON file."""
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
    def random_forest_params(self) -> dict[str, Any]:
        return {
            "n_estimators": self.n_estimators,
            "max_depth": self.max_depth,
            "min_samples_split": self.min_samples_split,
            "min_samples_leaf": self.min_samples_leaf,
            "max_features": self.max_features,
            "criterion": self.criterion,
            "class_weight": self.class_weight,
            "random_state": self.random_state,
            "n_jobs": -1,
        }

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
