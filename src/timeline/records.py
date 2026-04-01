from __future__ import annotations

import pandas as pd

from timeline.config import TimelineColumnMapping


def _coerce_bar_dates(series: pd.Series) -> pd.Series:
    """
    Convierte la columna a datetime **solo fecha**: tras parsear, se normaliza a medianoche
    (sin hora ni minuto ni segundo). Así el timeline no depende de la fracción de día en el CSV.
    """
    s = series.reset_index(drop=True)
    if pd.api.types.is_datetime64_any_dtype(s):
        parsed = pd.to_datetime(s, errors="coerce")
    elif pd.api.types.is_numeric_dtype(s):
        parsed = pd.to_datetime(s, errors="coerce", utc=False)
    else:
        # Evita el warning de inferencia fila a fila con formatos de texto heterogéneos (pandas 2+).
        parsed = pd.to_datetime(s, errors="coerce", utc=False, format="mixed")

    tz = getattr(parsed.dtype, "tz", None)
    if tz is not None:
        parsed = parsed.dt.tz_convert("UTC").dt.tz_localize(None)
    return parsed.dt.normalize()


def build_bar_frame(df: pd.DataFrame, mapping: TimelineColumnMapping) -> pd.DataFrame:
    """
    Devuelve un DataFrame con columnas canónicas para pintar barras y filtrar.

    - ``bar_start``, ``bar_end``: fechas (datetime naive a medianoche; sin componente horaria)
    - ``bar_label``: texto (o vacío)
    - Una columna por cada ``group_columns`` con los mismos nombres que en el origen
    - ``_row_id``: índice original para trazabilidad
    """
    out = pd.DataFrame({"_row_id": range(len(df))})
    out["bar_start"] = _coerce_bar_dates(df[mapping.start_column])
    out["bar_end"] = _coerce_bar_dates(df[mapping.end_column])

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
