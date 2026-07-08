"""Train the configurable SVM baseline on all selected labeled events."""

from __future__ import annotations

import argparse
import json

from src.random_forest_baseline.data import prepare_dataset

from .cli import add_common_arguments, config_from_args
from .modeling import fit_final_model, save_model_bundle


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    add_common_arguments(parser)
    parser.add_argument(
        "--model-output-path",
        help="Override the serialized model output path.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    config = config_from_args(args)
    if args.model_output_path is not None:
        config.model_output_path = args.model_output_path

    dataset = prepare_dataset(config)
    pipeline, model_metadata = fit_final_model(dataset, config)
    config.resolved_output_dir.mkdir(parents=True, exist_ok=True)
    save_model_bundle(
        config.resolved_model_output_path,
        config,
        dataset,
        pipeline,
        model_metadata,
    )
    with (config.resolved_output_dir / "model_metadata.json").open("w", encoding="utf-8") as handle:
        json.dump(model_metadata, handle, indent=2, ensure_ascii=False)

    print("SVM baseline model trained.")
    print(f"Selected labels: {', '.join(dataset.selected_labels)}")
    print(f"Events used for training: {len(dataset.labels)}")
    print(f"Model saved to: {config.resolved_model_output_path}")


if __name__ == "__main__":
    main()
