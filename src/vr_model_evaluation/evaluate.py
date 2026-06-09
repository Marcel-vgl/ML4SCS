"""Evaluate the stored models/v_r_v1_eval/output/v_r_v1.pkl artifact on labeled Vorhand/Rueckhand events."""

from __future__ import annotations

import argparse

from .config import VRModelEvaluationConfig
from .runner import evaluate_frozen_model, save_evaluation_artifacts


DEFAULT_CONFIG_PATH = "models/v_r_v1_eval/config.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH, help="Path to the evaluation config JSON.")
    parser.add_argument("--model-path", help="Override the .pkl model path.")
    parser.add_argument("--output-dir", help="Override the output artifact directory.")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    config = VRModelEvaluationConfig.from_json(args.config)
    if args.model_path is not None:
        config.model_path = args.model_path
    if args.output_dir is not None:
        config.output_dir = args.output_dir

    result = evaluate_frozen_model(config)
    save_evaluation_artifacts(config.resolved_output_dir, config, result)

    print("v_r_v1 evaluation finished.")
    print(f"Model: {config.resolved_model_path}")
    print(
        "Events={event_count} | Sessions={session_count} | Accuracy={accuracy:.3f} | Macro-F1={macro_f1:.3f}".format(
            **result.overall_metrics
        )
    )
    if result.overall_metrics["matches_model_training_sample_count"]:
        print("Note: Evaluation sample count matches the stored training sample count; results are likely in-sample.")
    print(f"Artifacts written to: {config.resolved_output_dir}")


if __name__ == "__main__":
    main()
