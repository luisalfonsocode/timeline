from __future__ import annotations

import argparse
from pathlib import Path

from rich.console import Console

from timeline.csv_loader import load_csv, profile_columns
from timeline.prompts import prompt_timeline_mapping
from timeline.records import build_bar_frame, filter_options


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Carga un CSV y configura columnas de timeline (inicio, fin, filtros)."
    )
    parser.add_argument("csv_path", type=Path, help="Ruta al archivo CSV")
    parser.add_argument(
        "--encoding",
        default=None,
        help="Codificación del CSV (opcional, p. ej. utf-8, latin-1)",
    )
    args = parser.parse_args()

    console = Console()
    df = load_csv(args.csv_path, encoding=args.encoding)
    profiles = profile_columns(df)
    mapping = prompt_timeline_mapping(profiles)
    bars = build_bar_frame(df, mapping)
    opts = filter_options(bars, mapping)

    console.print("\n[bold green]Mapeo[/bold green]")
    console.print(f"  Inicio: {mapping.start_column}")
    console.print(f"  Fin:    {mapping.end_column}")
    console.print(f"  Etiqueta: {mapping.label_column or '—'}")
    console.print(f"  Filtros: {', '.join(mapping.group_columns) or '—'}")
    console.print(f"\n[bold]Registros válidos (barras):[/bold] {len(bars)} de {len(df)}")
    if opts:
        console.print("\n[bold]Opciones de filtro (recuento):[/bold]")
        for col, vals in opts.items():
            console.print(f"  {col}: {len(vals)} valores distintos")

    # Punto de enganche: aquí puedes llamar a plotly, exportar JSON, etc.
    console.print(
        "\n[dim]DataFrame de barras disponible en código vía build_bar_frame(df, mapping).[/dim]"
    )


if __name__ == "__main__":
    main()
