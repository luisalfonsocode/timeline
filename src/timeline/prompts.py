from __future__ import annotations

from rich.console import Console
from rich.table import Table

from timeline.config import TimelineColumnMapping
from timeline.csv_loader import ColumnProfile


def _print_columns(console: Console, profiles: list[ColumnProfile]) -> None:
    table = Table(title="Columnas detectadas")
    table.add_column("#", justify="right")
    table.add_column("Nombre")
    table.add_column("dtype")
    table.add_column("no nulos", justify="right")
    table.add_column("Ejemplos")
    for i, p in enumerate(profiles):
        examples = ", ".join(p.sample_values) if p.sample_values else "—"
        table.add_row(str(i + 1), p.name, p.dtype, str(p.non_null_count), examples)
    console.print(table)


def _pick_index(console: Console, profiles: list[ColumnProfile], prompt: str) -> int:
    n = len(profiles)
    while True:
        raw = console.input(f"{prompt} (1–{n}): ").strip()
        if not raw.isdigit():
            console.print("[red]Introduce un número válido.[/red]")
            continue
        idx = int(raw)
        if 1 <= idx <= n:
            return idx - 1
        console.print("[red]Fuera de rango.[/red]")


def _pick_optional_label(console: Console, profiles: list[ColumnProfile]) -> int | None:
    n = len(profiles)
    while True:
        raw = console.input(f"Columna de etiqueta / título de barra (1–{n}, vacío = ninguna): ").strip()
        if raw == "":
            return None
        if not raw.isdigit():
            console.print("[red]Introduce un número o deja vacío.[/red]")
            continue
        idx = int(raw)
        if 1 <= idx <= n:
            return idx - 1
        console.print("[red]Fuera de rango.[/red]")


def _pick_group_indices(console: Console, profiles: list[ColumnProfile]) -> list[int]:
    console.print(
        "Columnas agrupadoras / filtros: escribe números separados por coma "
        "(p. ej. [cyan]2,4,5[/cyan]) o [cyan]ninguna[/cyan]."
    )
    n = len(profiles)
    while True:
        raw = console.input("Filtros: ").strip().lower()
        if raw in ("", "ninguna", "none", "n"):
            return []
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        if not parts:
            return []
        bad = []
        indices: list[int] = []
        for p in parts:
            if not p.isdigit():
                bad.append(p)
                continue
            i = int(p)
            if not (1 <= i <= n):
                bad.append(p)
            else:
                indices.append(i - 1)
        if bad:
            console.print(f"[red]Valores inválidos: {', '.join(bad)}[/red]")
            continue
        # dedupe preservando orden
        seen: set[int] = set()
        ordered: list[int] = []
        for i in indices:
            if i not in seen:
                seen.add(i)
                ordered.append(i)
        return ordered


def prompt_timeline_mapping(profiles: list[ColumnProfile]) -> TimelineColumnMapping:
    console = Console()
    _print_columns(console, profiles)

    i_start = _pick_index(console, profiles, "Columna de [bold]inicio[/bold] de cada barra")
    i_end = _pick_index(console, profiles, "Columna de [bold]fin[/bold] de cada barra")
    while i_end == i_start:
        console.print("[red]Fin debe ser distinto de inicio.[/red]")
        i_end = _pick_index(console, profiles, "Columna de [bold]fin[/bold] de cada barra")

    i_label = _pick_optional_label(console, profiles)
    group_idx = _pick_group_indices(console, profiles)
    used = {i_start, i_end}
    if i_label is not None:
        used.add(i_label)
    group_idx = [g for g in group_idx if g not in used]

    names = [p.name for p in profiles]
    label = names[i_label] if i_label is not None else None
    groups = tuple(names[i] for i in group_idx)

    return TimelineColumnMapping(
        start_column=names[i_start],
        end_column=names[i_end],
        group_columns=groups,
        label_column=label,
    )
