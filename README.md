# timeline

Herramienta en Python para construir **timelines** (barras horizontales en el tiempo) a partir de tablas de registros, sobre todo **CSV**.

- **Interfaz web (recomendada):** **Una sola pantalla de configuración inicial** en memoria (lectura del CSV + columnas de inicio, fin, etiqueta eje Y y columnas de filtro); al guardar, **solo ves el timeline** (más combos de valores para filtrar). Si la sesión ya tiene configuración guardada, la app **abre directamente el timeline**. **Limpiar configuración** vuelve a la pantalla 1 con todo limpio.
- **CLI:** el mismo flujo de configuración, en preguntas por terminal (sin gráfico integrado).
- **API Python:** carga de datos, mapeo de columnas y un `DataFrame` normalizado listo para filtrar o pintar.

## Requisitos

| Componente | Versión |
|------------|---------|
| Python | **3.10+** |
| Instalador | `pip` / `python3 -m pip` |

## Resumen de instalación

| Comando | Incluye |
|---------|---------|
| `pip install -e ".[ui]"` | Interfaz web (Streamlit + Plotly) + CLI + librería |
| `pip install -e .` | CLI + librería (pandas, rich) |
| `pip install -e ".[plot]"` | Plotly además de la base (sin Streamlit) |

---

## Configuración inicial (solo la primera vez)

1. **Entrar al directorio del repo**

   ```bash
   cd ruta/al/timeline
   ```

2. **Crear el entorno virtual** (recomendado)

   ```bash
   python3 -m venv .venv
   ```

3. **Activarlo**

   ```bash
   source .venv/bin/activate          # Linux / macOS
   # .venv\Scripts\Activate.ps1      # Windows (PowerShell)
   # .venv\Scripts\activate.bat      # Windows (cmd)
   ```

4. **Instalar el proyecto en modo editable**

   Para usar la **aplicación web**:

   ```bash
   python3 -m pip install -e ".[ui]"
   ```

   Solo **terminal** o integración como librería:

   ```bash
   python3 -m pip install -e .
   ```

5. **Comprobar la instalación**

   - CLI: `timeline --help`
   - Web: ejecuta `timeline-app` y comprueba que el navegador abre la app (o entra en [http://localhost:8501](http://localhost:8501))
   - Opciones generales de Streamlit (puerto, etc.): `python3 -m streamlit run --help`

Tras esto, el venv tiene los ejecutables **`timeline-app`** y **`timeline`** (y el paquete importable como `timeline`).

---

## Uso diario (proyecto ya configurado)

1. `cd ruta/al/timeline`
2. `source .venv/bin/activate`
3. Elige una de estas formas de trabajo:

### Interfaz web

```bash
timeline-app
```

Arranca **Streamlit** (por defecto suele abrir el navegador en [http://localhost:8501](http://localhost:8501)). Para pararlo, cancela el proceso en la terminal (`Ctrl+C`).

Equivalente manual (útil si depuras rutas):

```bash
python3 -m streamlit run "$(python3 -c "import timeline, pathlib; print(pathlib.Path(timeline.__file__).parent / 'webapp.py')")"
```

### CLI con un CSV

```bash
timeline ruta/al/archivo.csv
python3 -m timeline ruta/al/archivo.csv
```

Codificación opcional:

```bash
timeline ruta/al/archivo.csv --encoding latin-1
```

### Qué hace la interfaz web

**Pantalla 1 — Configuración inicial** (también si aún no hay config o pulsas **Limpiar configuración**)

1. Subes el **CSV** y defines **codificación**, **separador** y **cabecera**.
2. **Cargar datos en memoria** aplica esa lectura y habilita el mapeo.
3. Eliges columnas de **inicio**, **fin**, **etiqueta (eje Y)** y las que usarán los **filtros** (solo nombres de columna; los valores se eligen en la pantalla 2).
4. **Guardar configuración y abrir timeline** persiste en la sesión lectura + mapeo y cambia de pantalla.

**Pantalla 2 — Solo timeline**

5. Vista centrada en el **gráfico Gantt**; desplegables de **valores** para las columnas de filtro definidas antes.
6. **Sustituir CSV** (expander en la **barra lateral**): nuevo archivo con la **misma lectura** y columnas del mapeo; actualiza snapshot y sesión.
7. **Limpiar configuración** (solo en la **barra lateral**) borra datos, snapshot y mapeo y devuelve a la pantalla 1.

**Tras guardar la configuración**, se escribe un **snapshot** (`<id>.pkl`) en `~/.cache/timeline-streamlit/` y el puntero **`last_active_session.txt`** con ese id (y la URL puede llevar **`?s=…`**). **Al recargar la página, cerrar y volver a abrir `timeline-app`, o abrir sin query string**, se **restaura la última sesión** desde ese directorio hasta que pulses **Limpiar configuración**, que borra el `.pkl`, el puntero y `?s`.

El **CLI** replica la lógica de mapeo en texto y muestra resumen de barras válidas y recuentos de valores de filtro; no incluye el gráfico.

---

## Desarrollo: reinstalar dependencias

Si cambia `pyproject.toml` (por ejemplo tras un `git pull`):

```bash
python3 -m pip install -e ".[ui]"
```

---

## Uso desde código

```python
from pathlib import Path
from timeline import load_csv, read_csv_stream, TimelineColumnMapping, build_bar_frame
from timeline.records import filter_options

df = load_csv(Path("examples/sample_tasks.csv"))
mapping = TimelineColumnMapping(
    start_column="issue_inicio",
    end_column="issue_fin",
    group_columns=("release_name", "release_squad"),
    label_column="issue_key",
)
bars = build_bar_frame(df, mapping)
filtros = filter_options(bars, mapping)
```

Para datos ya en memoria (por ejemplo subida en una app propia):

```python
df = read_csv_stream(bytes_del_csv)
```

---

## Datos de ejemplo

| Archivo | Contenido |
|---------|-----------|
| `examples/sample_tasks.csv` | ~2000 filas; fechas `YYYY-MM-DD`. |
| `examples/sample_tasks_datetime.csv` | Mismas filas lógicas con `YYYY-MM-DD HH:MM:SS`. |
| `examples/release_definitions.csv` | Catálogo de combinaciones release / trimestre / squad / tribu (solo referencia para datos de prueba; el paquete no lo carga por defecto). |

---

## Estructura del código

```
src/timeline/
  __init__.py     # Exporta API pública
  config.py       # TimelineColumnMapping
  csv_loader.py   # load_csv, read_csv_stream, profile_columns
  records.py      # build_bar_frame, filter_options
  prompts.py      # Mapeo interactivo (CLI)
  cli.py          # Comando timeline
  __main__.py     # python -m timeline
  webapp.py       # App Streamlit; comando timeline-app
```
