"""Shared CLI helpers for the SVM baseline scripts."""

from __future__ import annotations

import argparse

from .config import SVMBaselineConfig


DEFAULT_CONFIG_PATH = "baseline_models/svm/config.json"


def add_common_arguments(parser: argparse.ArgumentParser) -> None:
    """Attach shared configuration overrides to an SVM CLI parser."""
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
    parser.add_argument("--kernel", help="SVM kernel such as rbf, linear, poly, or sigmoid.")
    parser.add_argument("--c-value", type=float, help="Regularization parameter C.")
    parser.add_argument("--gamma", help="Kernel coefficient gamma. Use scale, auto, or a numeric value.")
    parser.add_argument("--degree", type=int, help="Degree for the polynomial kernel.")
    parser.add_argument("--coef0", type=float, help="Independent term in poly/sigmoid kernels.")
    parser.add_argument("--class-weight", help="Class weight setting, for example balanced or none.")
    parser.add_argument("--random-state", type=int, help="Random seed.")


def config_from_args(args: argparse.Namespace) -> SVMBaselineConfig:
    """Load the JSON config and apply CLI overrides."""
    config = SVMBaselineConfig.from_json(args.config)
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
        "kernel": args.kernel,
        "c_value": args.c_value,
        "gamma": _parse_maybe_numeric(args.gamma),
        "degree": args.degree,
        "coef0": args.coef0,
        "class_weight": _parse_optional_string(args.class_weight),
        "random_state": args.random_state,
    }
    for key, value in overrides.items():
        if value is not None:
            setattr(config, key, value)
    return config


def _parse_optional_string(value: str | None) -> str | None:
    """Parse sentinel strings such as 'none' into Python None."""
    if value is None:
        return None
    lowered = value.strip().lower()
    if lowered in {"none", "null"}:
        return None
    return value


def _parse_maybe_numeric(value: str | None) -> str | float | None:
    """Parse CLI strings into floats when appropriate."""
    parsed = _parse_optional_string(value)
    if parsed is None:
        return None
    try:
        return float(parsed)
    except ValueError:
        return parsed
