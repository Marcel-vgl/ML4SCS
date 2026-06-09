"""Configuration for evaluating the frozen v_r_v1 model artifact."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class VRModelEvaluationConfig:
    """Editable configuration for the frozen Vorhand/Rueckhand model evaluation."""

    model_path: str = "models/v_r_v1_eval/output/v_r_v1.pkl"
    data_dir: str = "Daten"
    label_dir: str = "labels"
    output_dir: str = "models/v_r_v1_eval/output"
    supported_labels: list[str] = field(default_factory=lambda: ["Rueckhand", "Vorhand"])
    peak_min_spacing_s: float = 0.45
    max_peak_distance_s: float = 0.5

    @classmethod
    def from_json(cls, path: str | Path) -> "VRModelEvaluationConfig":
        """Load the evaluation config from JSON."""
        config_path = cls.resolve_path(path)
        with config_path.open(encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, dict):
            raise ValueError(f"{config_path} must contain a JSON object.")
        return cls(**payload)

    @staticmethod
    def resolve_path(path: str | Path) -> Path:
        candidate = Path(path).expanduser()
        if candidate.is_absolute():
            return candidate
        return REPO_ROOT / candidate

    @property
    def resolved_model_path(self) -> Path:
        return self.resolve_path(self.model_path)

    @property
    def resolved_data_dir(self) -> Path:
        return self.resolve_path(self.data_dir)

    @property
    def resolved_label_dir(self) -> Path:
        return self.resolve_path(self.label_dir)

    @property
    def resolved_output_dir(self) -> Path:
        return self.resolve_path(self.output_dir)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
