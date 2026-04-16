"""Basic preprocessing utilities for the semester project."""

from pathlib import Path
import pandas as pd


def load_csv(path: str | Path) -> pd.DataFrame:
    """Load a CSV file into a pandas DataFrame."""
    return pd.read_csv(path)


def summarize_dataframe(df: pd.DataFrame) -> dict:
    """Return a simple summary of the dataframe."""
    return {
        "rows": df.shape[0],
        "columns": df.shape[1],
        "column_names": list(df.columns),
        "missing_values": df.isna().sum().to_dict(),
    }


if __name__ == "__main__":
    print("Add your preprocessing pipeline here.")
