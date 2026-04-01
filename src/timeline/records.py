from __future__ import annotations

import pandas as pd

from timeline.config import TimelineColumnMapping


def _coerce_datetime(series: pd.Series) -> pd.Series:
    if pd.api.types.is_datetime64_any_dtype(series):
        return series
    return pd.to_datetime(series, errors="coerce", utc=False)


def build_bar_frame(df: pd.DataFrame, mapping: TimelineColumnMapping) -> pd.DataFrame:
    """
    Devuelve un DataFrame con columnas canónicas para pintar barras y filtrar.

    - ``bar_start``, ``bar_end``: timestamps
    - ``bar_label``: texto (o vacío)
    - Una columna por cada ``group_columns`` con los mismos nombres que en el origen
    - ``_row_id``: índice original para trazabilidad
    """
    out = pd.DataFrame({"_row_id": range(len(df))})
    out["bar_start"] = _coerce_datetime(df[mapping.start_column].reset_index(drop=True))
    out["bar_end"] = _coerce_datetime(df[mapping.end_column].reset_index(drop=True))

    if mapping.label_column:
        out["bar_label"] = df[mapping.label_column].reset_index(drop=True).astype(str)
    else:
        out["bar_label"] = ""

    for col in mapping.group_columns:
        out[col] = df[col].reset_index(drop=True)

    mask = out["bar_start"].notna() & out["bar_end"].notna()
    out = out.loc[mask].copy()
    invalid = out["bar_end"] < out["bar_start"]
    if invalid.any():
        out = out.loc[~invalid].copy()
    out.reset_index(drop=True, inplace=True)
    return out


def filter_options(bar_frame: pd.DataFrame, mapping: TimelineColumnMapping) -> dict[str, list[str]]:
    """Valores únicos por columna de filtro (como strings), para UI o widgets."""
    opts: dict[str, list[str]] = {}
    for col in mapping.group_columns:
        if col not in bar_frame.columns:
            continue
        vals = bar_frame[col].dropna().astype(str).unique().tolist()
        vals.sort()
        opts[col] = vals
    return opts
