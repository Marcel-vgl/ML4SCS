"""Evaluate the v_r_v2 multi-class model with the baseline Random-Forest pipeline."""

from __future__ import annotations

import argparse

from src.random_forest_baseline.cli import add_common_arguments, config_from_args
from src.random_forest_baseline.data import prepare_dataset
from src.random_forest_baseline.modeling import evaluate_grouped_dataset, save_evaluation_artifacts


DEFAULT_CONFIG_PATH = "models/v_r_v2/config.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    add_common_arguments(parser)
    for action in parser._actions:
        if action.dest == "config":
            action.default = DEFAULT_CONFIG_PATH
            break
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    config = config_from_args(args)
    dataset = prepare_dataset(config)
    result = evaluate_grouped_dataset(dataset, config)
    save_evaluation_artifacts(config.resolved_output_dir, config, dataset, result)

    print("v_r_v2 evaluation finished.")
    print(f"Selected labels: {', '.join(dataset.selected_labels)}")
    print(
        "Sessions={sessions} | Events={events} | Features={features} | Accuracy={accuracy:.3f} | Macro-F1={macro_f1:.3f}".format(
            sessions=dataset.groups.nunique(),
            events=len(dataset.labels),
            features=dataset.features.shape[1],
            **result.overall_metrics,
        )
    )
    print(f"Artifacts written to: {config.resolved_output_dir}")


if __name__ == "__main__":
    main()
