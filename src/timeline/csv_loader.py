from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

import pandas as pd


@dataclass(frozen=True)
class ColumnProfile:
    name: str
    dtype: str
    non_null_count: int
    sample_values: tuple[str, ...]


def load_csv(path: str | Path, encoding: str | None = None, **read_kwargs) -> pd.DataFrame:
    """Carga un CSV sin forzar tipos; el mapeo de fechas se aplica después."""
    p = Path(path)
    kwargs = {"encoding": encoding} if encoding else {}
    kwargs.update(read_kwargs)
    return pd.read_csv(p, **kwargs)


def read_csv_stream(data: bytes | BinaryIO, encoding: str | None = None, **read_kwargs) -> pd.DataFrame:
    """Carga un CSV desde memoria o fichero binario (p. ej. subida en Streamlit)."""
    kwargs = {"encoding": encoding} if encoding else {}
    kwargs.update(read_kwargs)
    buf = io.BytesIO(data) if isinstance(data, bytes) else data
    return pd.read_csv(buf, **kwargs)


def profile_columns(df: pd.DataFrame, max_samples: int = 3) -> list[ColumnProfile]:
    """Resume columnas para mostrar al usuario y elegir inicio / fin / filtros."""
    profiles: list[ColumnProfile] = []
    for col in df.columns:
        s = df[col]
        non_null = int(s.notna().sum())
        samples = s.dropna().astype(str).head(max_samples).tolist()
        samples_t = tuple(samples[:max_samples])
        profiles.append(
            ColumnProfile(
                name=str(col),
                dtype=str(s.dtype),
                non_null_count=non_null,
                sample_values=samples_t,
            )
        )
    return profiles
