"""Dataset preparation for the Random-Forest tennis baseline."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .config import BaselineConfig


TIME_COLUMN_CANDIDATES = [
    "motionTimestamp_sinceReboot(s)",
    "accelerometerTimestamp_sinceReboot(s)",
    "loggingTime(txt)",
]
LABEL_NAME_CANDIDATES = ["label_name", "Label_name"]
LABEL_ID_CANDIDATES = ["Labels", "label"]
EXCLUDED_NUMERIC_COLUMNS = {
    "motionTimestamp_sinceReboot(s)",
    "accelerometerTimestamp_sinceReboot(s)",
    "altimeterTimestamp_sinceReboot(s)",
    "locationTimestamp_since1970(s)",
    "label",
    "Labels",
    "csv_time_s",
    "video_time_s",
    "event_csv_time_s",
    "event_video_time_s",
}
SENSOR_PREFIXES = ("accelerometer", "motion", "altimeter")
FEATURE_STATS = ("mean", "std", "min", "max", "median", "energy")


@dataclass
class SessionData:
    """Container for one labeled CSV session."""

    path: Path
    frame: pd.DataFrame
    time_column: str
    sensor_columns: list[str]


@dataclass
class PreparedDataset:
    """Feature matrix and metadata derived from labeled event windows."""

    features: pd.DataFrame
    labels: pd.Series
    groups: pd.Series
    metadata: pd.DataFrame
    label_summary: pd.DataFrame
    selected_labels: list[str]
    sensor_columns: list[str]


def prepare_dataset(config: BaselineConfig) -> PreparedDataset:
    """Load labeled sessions, build event windows, and summarize them as features."""
    sessions = load_sessions(config.resolved_data_dir)
    raw_events = collect_raw_events(sessions)
    raw_events = remap_event_labels(raw_events, config.label_aliases)
    label_summary = summarize_label_availability(raw_events)
    selected_labels = choose_labels(label_summary, config)
    selected_events = raw_events[raw_events["label_name"].isin(selected_labels)].copy()
    feature_rows = build_feature_rows(sessions, selected_events, config)
    if not feature_rows:
        raise ValueError(
            "No usable event windows were created. Try larger windows or lower min_window_rows."
        )

    features = pd.DataFrame([row["features"] for row in feature_rows]).sort_index(axis=1)
    labels = pd.Series([row["label_name"] for row in feature_rows], name="label_name")
    groups = pd.Series([row["session_name"] for row in feature_rows], name="session_name")
    metadata = pd.DataFrame(
        [
            {
                "session_name": row["session_name"],
                "event_index": row["event_index"],
                "event_time_s": row["event_time_s"],
                "window_start_s": row["window_start_s"],
                "window_end_s": row["window_end_s"],
                "window_rows": row["window_rows"],
                "label_name": row["label_name"],
            }
            for row in feature_rows
        ]
    )
    available_labels = label_summary[label_summary["label_name"].isin(selected_labels)].copy()
    available_labels = available_labels.set_index("label_name").loc[selected_labels].reset_index()
    sensor_columns = sorted({column for session in sessions.values() for column in session.sensor_columns})

    return PreparedDataset(
        features=features,
        labels=labels,
        groups=groups,
        metadata=metadata,
        label_summary=available_labels,
        selected_labels=selected_labels,
        sensor_columns=sensor_columns,
    )


def load_sessions(data_dir: Path) -> dict[str, SessionData]:
    """Load all labeled session CSVs from the configured data directory."""
    if not data_dir.exists():
        raise FileNotFoundError(f"Data directory not found: {data_dir}")

    sessions: dict[str, SessionData] = {}
    for csv_path in sorted(data_dir.glob("*.csv")):
        frame = pd.read_csv(csv_path)
        time_column = pick_time_column(frame)
        normalized_time = normalize_time_column(frame[time_column], time_column)
        sensor_columns = pick_sensor_columns(frame)
        prepared = frame.copy()
        prepared["_time_s"] = normalized_time
        prepared = prepared.dropna(subset=["_time_s"]).reset_index(drop=True)
        sessions[csv_path.name] = SessionData(
            path=csv_path,
            frame=prepared,
            time_column=time_column,
            sensor_columns=sensor_columns,
        )

    if not sessions:
        raise FileNotFoundError(f"No CSV files found in {data_dir}")
    return sessions


def pick_time_column(frame: pd.DataFrame) -> str:
    """Choose the best available timestamp column for window extraction."""
    for column in TIME_COLUMN_CANDIDATES:
        if column in frame.columns:
            return column
    raise ValueError("No supported timestamp column found.")


def normalize_time_column(series: pd.Series, column_name: str) -> pd.Series:
    """Normalize timestamps to seconds since session start."""
    if column_name == "loggingTime(txt)":
        timestamps = pd.to_datetime(series, errors="coerce")
        first_valid = timestamps.dropna().iloc[0]
        return (timestamps - first_valid).dt.total_seconds()

    numeric = pd.to_numeric(series, errors="coerce")
    first_valid = numeric.dropna().iloc[0]
    return numeric - first_valid


def pick_best_label_name_column(frame: pd.DataFrame) -> str | None:
    """Pick the label-name column that contains the most non-empty values."""
    best_column: str | None = None
    best_count = 0
    for column in LABEL_NAME_CANDIDATES:
        if column not in frame.columns:
            continue
        count = frame[column].fillna("").astype(str).str.strip().ne("").sum()
        if count > best_count:
            best_column = column
            best_count = count
    return best_column


def pick_best_label_id_column(frame: pd.DataFrame) -> str | None:
    """Pick the numeric label column with the most non-zero entries."""
    best_column: str | None = None
    best_count = 0
    for column in LABEL_ID_CANDIDATES:
        if column not in frame.columns:
            continue
        numeric = pd.to_numeric(frame[column], errors="coerce")
        count = numeric.fillna(0).ne(0).sum()
        if count > best_count:
            best_column = column
            best_count = count
    return best_column


def collect_raw_events(sessions: dict[str, SessionData]) -> pd.DataFrame:
    """Collect one event row per labeled stroke from every session."""
    rows: list[dict[str, object]] = []

    for session_name, session in sessions.items():
        frame = session.frame
        label_name_column = pick_best_label_name_column(frame)
        label_id_column = pick_best_label_id_column(frame)

        label_names = pd.Series(pd.NA, index=frame.index, dtype="string")
        mask = pd.Series(False, index=frame.index)

        if label_name_column:
            cleaned = frame[label_name_column].fillna("").astype(str).str.strip()
            label_names = cleaned.mask(cleaned.eq(""), pd.NA).astype("string")
            mask |= label_names.notna()

        if label_id_column:
            label_ids = pd.to_numeric(frame[label_id_column], errors="coerce")
            non_zero_ids = label_ids.where(label_ids.fillna(0).ne(0))
            fallback_names = non_zero_ids.dropna().astype(int).astype(str).map(lambda value: f"label_{value}")
            label_names = label_names.combine_first(fallback_names.reindex(frame.index).astype("string"))
            mask |= non_zero_ids.notna()

        event_rows = frame.loc[mask, ["_time_s"]].copy()
        if event_rows.empty:
            continue
        event_rows["label_name"] = label_names.loc[event_rows.index].astype(str).str.strip()
        event_rows["session_name"] = session_name
        event_rows["event_index"] = event_rows.index
        rows.extend(event_rows.rename(columns={"_time_s": "event_time_s"}).to_dict("records"))

    events = pd.DataFrame(rows)
    if events.empty:
        raise ValueError("No labeled events found in the configured CSV files.")
    events = events[events["label_name"].ne("")]
    return events.sort_values(["session_name", "event_time_s"]).reset_index(drop=True)


def remap_event_labels(events: pd.DataFrame, label_aliases: dict[str, str]) -> pd.DataFrame:
    """Collapse or rename raw labels before label selection and feature extraction."""
    if not label_aliases:
        return events

    remapped = events.copy()
    remapped["label_name"] = remapped["label_name"].map(lambda value: label_aliases.get(str(value), str(value)))
    remapped = remapped[remapped["label_name"].astype(str).str.strip().ne("")]
    return remapped.reset_index(drop=True)


def summarize_label_availability(events: pd.DataFrame) -> pd.DataFrame:
    """Summarize label counts and how many sessions contain each label."""
    summary = (
        events.groupby("label_name")
        .agg(total_events=("label_name", "size"), session_count=("session_name", "nunique"))
        .reset_index()
        .sort_values(["total_events", "session_count", "label_name"], ascending=[False, False, True])
        .reset_index(drop=True)
    )
    return summary


def choose_labels(label_summary: pd.DataFrame, config: BaselineConfig) -> list[str]:
    """Select the labels that should be modeled for this experiment."""
    available = label_summary.set_index("label_name")
    excluded = set(config.excluded_labels or [])

    if config.labels:
        missing = [label for label in config.labels if label not in available.index]
        if missing:
            raise ValueError(f"Configured labels not found in the data: {missing}")
        return [label for label in config.labels if label not in excluded]

    filtered = label_summary[
        (label_summary["total_events"] >= config.min_samples_per_label)
        & (label_summary["session_count"] >= config.min_sessions_per_label)
        & (~label_summary["label_name"].isin(excluded))
    ]
    selected = filtered["label_name"].tolist()
    if not selected:
        raise ValueError(
            "Automatic label selection produced no classes. "
            "Lower min_samples_per_label or min_sessions_per_label."
        )
    return selected


def pick_sensor_columns(frame: pd.DataFrame) -> list[str]:
    """Select the numeric sensor columns that should feed the feature extraction."""
    columns: list[str] = []
    for column in frame.select_dtypes(include=["number"]).columns:
        if column in EXCLUDED_NUMERIC_COLUMNS:
            continue
        if not column.startswith(SENSOR_PREFIXES):
            continue
        columns.append(column)
    if not columns:
        raise ValueError("No supported numeric sensor columns found.")
    return columns


def build_feature_rows(
    sessions: dict[str, SessionData],
    selected_events: pd.DataFrame,
    config: BaselineConfig,
) -> list[dict[str, object]]:
    """Create one feature row per labeled event window."""
    rows: list[dict[str, object]] = []

    for session_name, event_group in selected_events.groupby("session_name"):
        session = sessions[session_name]
        frame = session.frame
        time_values = frame["_time_s"]

        for event in event_group.itertuples(index=False):
            window_start = float(event.event_time_s) - config.window_before_s
            window_end = float(event.event_time_s) + config.window_after_s
            window = frame[(time_values >= window_start) & (time_values <= window_end)]
            if len(window) < config.min_window_rows:
                continue

            feature_map = summarize_window(window, session.sensor_columns)
            feature_map["window_rows"] = float(len(window))
            feature_map["window_duration_s"] = float(window["_time_s"].iloc[-1] - window["_time_s"].iloc[0])
            rows.append(
                {
                    "session_name": session_name,
                    "event_index": int(event.event_index),
                    "event_time_s": float(event.event_time_s),
                    "window_start_s": window_start,
                    "window_end_s": window_end,
                    "window_rows": int(len(window)),
                    "label_name": str(event.label_name),
                    "features": feature_map,
                }
            )
    return rows


def summarize_window(window: pd.DataFrame, sensor_columns: list[str]) -> dict[str, float]:
    """Convert a multivariate sensor window into aggregate baseline features."""
    features: dict[str, float] = {}

    for column in sensor_columns:
        values = pd.to_numeric(window[column], errors="coerce").to_numpy(dtype=float)
        if np.isnan(values).all():
            for stat_name in FEATURE_STATS:
                features[f"{column}__{stat_name}"] = np.nan
            continue

        clean_values = values[~np.isnan(values)]
        features[f"{column}__mean"] = float(np.mean(clean_values))
        features[f"{column}__std"] = float(np.std(clean_values))
        features[f"{column}__min"] = float(np.min(clean_values))
        features[f"{column}__max"] = float(np.max(clean_values))
        features[f"{column}__median"] = float(np.median(clean_values))
        features[f"{column}__energy"] = float(np.mean(np.square(clean_values)))

    return features
