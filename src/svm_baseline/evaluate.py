"""Evaluate the configurable SVM baseline on labeled sessions."""

from __future__ import annotations

import argparse

from src.random_forest_baseline.data import prepare_dataset

from .cli import add_common_arguments, config_from_args
from .modeling import evaluate_grouped_dataset, save_evaluation_artifacts


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    add_common_arguments(parser)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    config = config_from_args(args)
    dataset = prepare_dataset(config)
    result = evaluate_grouped_dataset(dataset, config)
    save_evaluation_artifacts(config.resolved_output_dir, config, dataset, result)

    print("SVM baseline evaluation finished.")
    print(f"Selected labels: {', '.join(dataset.selected_labels)}")
    print(f"Sessions: {dataset.groups.nunique()} | Events: {len(dataset.labels)} | Features: {dataset.features.shape[1]}")
    print(
        "Accuracy={accuracy:.3f} | Macro-F1={macro_f1:.3f} | Macro-Recall={macro_recall:.3f}".format(
            **result.overall_metrics
        )
    )
    print(f"Artifacts written to: {config.resolved_output_dir}")


if __name__ == "__main__":
    main()
