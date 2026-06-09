"""Small group-aware hyperparameter search for the Random-Forest baseline."""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path

import pandas as pd
from sklearn.model_selection import ParameterSampler

from .cli import add_common_arguments, config_from_args
from .config import BaselineConfig
from .data import prepare_dataset
from .modeling import evaluate_grouped_dataset


DEFAULT_SEARCH_OUTPUT_DIR = "baseline_models/random_forest_v2/output"

SEARCH_SPACE: dict[str, list[object]] = {
    "n_estimators": [200, 300, 400, 600, 800],
    "max_depth": [None, 8, 12, 16, 24],
    "min_samples_split": [2, 4, 6, 10],
    "min_samples_leaf": [1, 2, 3, 4],
    "max_features": ["sqrt", "log2", 0.5, 0.75],
    "criterion": ["gini", "entropy"],
    "class_weight": ["balanced", "balanced_subsample", None],
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    add_common_arguments(parser)
    parser.add_argument(
        "--search-output-dir",
        default=DEFAULT_SEARCH_OUTPUT_DIR,
        help="Directory where search results should be stored.",
    )
    parser.add_argument(
        "--n-iter",
        type=int,
        default=16,
        help="Number of parameter combinations to sample from the search space.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    base_config = config_from_args(args)
    dataset = prepare_dataset(base_config)
    output_dir = BaselineConfig.resolve_path(args.search_output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    candidates = list(
        ParameterSampler(
            SEARCH_SPACE,
            n_iter=args.n_iter,
            random_state=base_config.random_state,
        )
    )

    rows: list[dict[str, object]] = []
    best_config = base_config
    best_metrics: dict[str, object] | None = None
    best_macro_f1 = float("-inf")

    for index, params in enumerate(candidates, start=1):
        candidate_config = replace(base_config, **params)
        result = evaluate_grouped_dataset(dataset, candidate_config)
        row: dict[str, object] = {
            "candidate_rank_seed_order": index,
            **params,
            **result.overall_metrics,
        }
        rows.append(row)

        macro_f1 = float(result.overall_metrics["macro_f1"])
        balanced_accuracy = float(result.overall_metrics["balanced_accuracy"])
        current_best_balanced = float(best_metrics["balanced_accuracy"]) if best_metrics is not None else float("-inf")

        if (
            macro_f1 > best_macro_f1
            or (
                abs(macro_f1 - best_macro_f1) < 1e-12
                and balanced_accuracy > current_best_balanced
            )
        ):
            best_macro_f1 = macro_f1
            best_config = candidate_config
            best_metrics = row

    if best_metrics is None:
        raise RuntimeError("The search did not evaluate any candidates.")

    results_frame = pd.DataFrame(rows).sort_values(
        ["macro_f1", "balanced_accuracy", "weighted_f1", "accuracy"],
        ascending=[False, False, False, False],
        ignore_index=True,
    )
    results_frame.insert(0, "search_rank", range(1, len(results_frame) + 1))
    results_frame.to_csv(output_dir / "search_results.csv", index=False)

    best_payload = {
        "best_params": {
            "n_estimators": best_config.n_estimators,
            "max_depth": best_config.max_depth,
            "min_samples_split": best_config.min_samples_split,
            "min_samples_leaf": best_config.min_samples_leaf,
            "max_features": best_config.max_features,
            "criterion": best_config.criterion,
            "class_weight": best_config.class_weight,
        },
        "best_metrics": {
            key: best_metrics[key]
            for key in [
                "accuracy",
                "balanced_accuracy",
                "macro_precision",
                "macro_recall",
                "macro_f1",
                "weighted_f1",
                "event_count",
                "feature_count",
                "session_count",
            ]
        },
        "search_space": SEARCH_SPACE,
        "n_iter": args.n_iter,
    }
    with (output_dir / "search_summary.json").open("w", encoding="utf-8") as handle:
        json.dump(best_payload, handle, indent=2, ensure_ascii=False)

    with (output_dir / "recommended_config.json").open("w", encoding="utf-8") as handle:
        json.dump(best_config.to_dict(), handle, indent=2, ensure_ascii=False)

    print("Random-Forest baseline search finished.")
    print(f"Candidates evaluated: {len(results_frame)}")
    print(
        "Best macro_f1={macro_f1:.3f} | balanced_accuracy={balanced_accuracy:.3f} | accuracy={accuracy:.3f}".format(
            **best_metrics
        )
    )
    print("Best params:")
    for key, value in best_payload["best_params"].items():
        print(f"  {key}={value}")
    print(f"Search artifacts written to: {output_dir}")


if __name__ == "__main__":
    main()
