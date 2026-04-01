from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TimelineColumnMapping:
    """Qué columnas del CSV definen cada barra y los filtros."""

    start_column: str
    end_column: str
    """Columnas categóricas (o discretas) que alimentan filtros / leyenda."""
    group_columns: tuple[str, ...] = field(default_factory=tuple)
    """Columna opcional para el texto principal de la barra (tooltip / etiqueta)."""
    label_column: str | None = None

    def filter_column_names(self) -> tuple[str, ...]:
        return self.group_columns
