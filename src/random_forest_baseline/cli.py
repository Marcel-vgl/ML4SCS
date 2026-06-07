"""Shared CLI helpers for the Random-Forest baseline scripts."""

from __future__ import annotations

import argparse

from .config import BaselineConfig


DEFAULT_CONFIG_PATH = "baseline_models/random_forest/config.json"


def add_common_arguments(parser: argparse.ArgumentParser) -> None:
    """Attach shared configuration overrides to a CLI parser."""
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH, help="Path to the JSON config file.")
    parser.add_argument("--data-dir", help="Override the labeled CSV directory.")
    parser.add_argument("--output-dir", help="Override the artifact output directory.")
    parser.add_argument("--window-before-s", type=float, help="Seconds before the labeled event.")
    parser.add_argument("--window-after-s", type=float, help="Seconds after the labeled event.")
    parser.add_argument("--min-window-rows", type=int, help="Minimum number of samples inside a window.")
    parser.add_argument("--labels", nargs="+", help="Explicit label list to model.")
    parser.add_argument("--excluded-labels", nargs="+", help="Labels to exclude in auto mode.")
    parser.add_argument("--min-samples-per-label", type=int, help="Minimum event count for auto selection.")
    parser.add_argument("--min-sessions-per-label", type=int, help="Minimum session count for auto selection.")
    parser.add_argument("--n-estimators", type=int, help="Number of Random-Forest trees.")
    parser.add_argument("--max-depth", type=int, help="Optional maximum tree depth.")
    parser.add_argument("--min-samples-leaf", type=int, help="Minimum samples per leaf node.")
    parser.add_argument("--random-state", type=int, help="Random seed.")


def config_from_args(args: argparse.Namespace) -> BaselineConfig:
    """Load the JSON config and apply CLI overrides."""
    config = BaselineConfig.from_json(args.config)
    overrides = {
        "data_dir": args.data_dir,
        "output_dir": args.output_dir,
        "window_before_s": args.window_before_s,
        "window_after_s": args.window_after_s,
        "min_window_rows": args.min_window_rows,
        "labels": args.labels,
        "excluded_labels": args.excluded_labels,
        "min_samples_per_label": args.min_samples_per_label,
        "min_sessions_per_label": args.min_sessions_per_label,
        "n_estimators": args.n_estimators,
        "max_depth": args.max_depth,
        "min_samples_leaf": args.min_samples_leaf,
        "random_state": args.random_state,
    }
    for key, value in overrides.items():
        if value is not None:
            setattr(config, key, value)
    return config
