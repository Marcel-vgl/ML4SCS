"""Train the configurable Random-Forest baseline on all selected labeled events."""

from __future__ import annotations

import argparse

from .cli import add_common_arguments, config_from_args
from .data import prepare_dataset
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
    pipeline, feature_importances = fit_final_model(dataset, config)
    config.resolved_output_dir.mkdir(parents=True, exist_ok=True)
    save_model_bundle(
        config.resolved_model_output_path,
        config,
        dataset,
        pipeline,
        feature_importances,
    )
    feature_importances.head(20).to_csv(
        config.resolved_output_dir / "feature_importances.csv",
        index=False,
    )

    print("Random-Forest baseline model trained.")
    print(f"Selected labels: {', '.join(dataset.selected_labels)}")
    print(f"Events used for training: {len(dataset.labels)}")
    print(f"Model saved to: {config.resolved_model_output_path}")


if __name__ == "__main__":
    main()
