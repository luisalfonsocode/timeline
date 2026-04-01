from __future__ import annotations

import pickle
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.express as px
import streamlit as st

from timeline.config import TimelineColumnMapping
from timeline.csv_loader import profile_columns, read_csv_stream
from timeline.records import build_bar_frame

_ENC_PRESETS = ("utf-8", "latin-1", "cp1252", "iso-8859-1")

# Gráfico timeline: altura fija en px por cada barra visible (slot en eje Y)
_TL_AXIS_TICK_PX = 9
_TL_AXIS_TITLE_PX = 11
_TL_ROW_LH_FACTOR = 1.52
_TL_ROW_GAP_PX = 6
_TL_BAR_HEIGHT_PX = int(round(_TL_AXIS_TICK_PX * _TL_ROW_LH_FACTOR)) + _TL_ROW_GAP_PX
_TL_MARGIN_TOP_PX = 6
_TL_MARGIN_BOTTOM_PX = 58
_TL_MARGIN_PAD = 2


def _timeline_fig_height_px(n_rows: int) -> int:
    """Altura total = márgenes + n_filas × _TL_BAR_HEIGHT_PX (cada barra ocupa siempre el mismo slot)."""
    n = max(1, n_rows)
    return (
        _TL_MARGIN_TOP_PX
        + _TL_MARGIN_BOTTOM_PX
        + _TL_MARGIN_PAD
        + n * _TL_BAR_HEIGHT_PX
    )


def _timeline_margin_left_px(max_label_chars: int) -> int:
    """Espacio eje Y acorde a longitud de etiqueta (texto truncado en _y_plot)."""
    mc = min(40, max(4, int(max_label_chars)))
    return min(280, max(52, int(6.2 * mc)))

# Persistencia: snapshot .pkl + puntero última sesión (sobrevive a cerrar / abrir la app sin ?s=)
_PERSIST_DIR = Path.home() / ".cache" / "timeline-streamlit"
_LAST_ACTIVE_SESSION = _PERSIST_DIR / "last_active_session.txt"
_QUERY_SESSION = "s"

# Claves de sesión:
# - config_complete: si True → solo pantalla timeline (si hay df + timeline_mapping)
# - df, csv_bytes, csv_filename, read_params: datos y forma de lectura
# - timeline_mapping: dict listo para TimelineColumnMapping
# - persist_key: id del snapshot en disco (opcional)
# El snapshot (.pkl) guarda: read_params (cómo leer), csv_bytes + csv_filename (referencia al último archivo),
# df materializado, timeline_mapping.


def _mapping_required_columns(mapping: TimelineColumnMapping) -> set[str]:
    names: set[str] = {mapping.start_column, mapping.end_column}
    names.update(mapping.group_columns)
    if mapping.label_column:
        names.add(mapping.label_column)
    return names


def _apply_replacement_csv(raw: bytes, filename: str) -> str | None:
    """
    Sustituye el DataFrame en sesión leyendo ``raw`` con ``read_params`` guardados.
    Exige las mismas columnas que usa el mapeo. Actualiza el snapshot en disco si hay ``persist_key``.
    Devuelve texto de error o None si todo fue bien.
    """
    rp = st.session_state.get("read_params")
    if not rp:
        return "No hay parámetros de lectura guardados. Usa «Limpiar configuración» y vuelve al paso 1."
    raw_map = st.session_state.get("timeline_mapping")
    if not raw_map:
        return "Falta el mapeo de columnas."
    mapping = _mapping_from_saved(raw_map)
    try:
        new_df = _read_csv_from_bytes(
            raw,
            encoding=rp["encoding"],
            sep=rp["sep"],
            has_header_row=rp["has_header_row"],
        )
    except Exception as e:
        return f"No se pudo leer el archivo con la configuración guardada: {e}"
    colset = {str(c) for c in new_df.columns}
    missing = _mapping_required_columns(mapping) - colset
    if missing:
        return "El CSV nuevo no incluye las columnas requeridas por el mapeo: " + ", ".join(
            sorted(missing)
        )
    if new_df.empty:
        return "El archivo no tiene filas."
    st.session_state.df = new_df
    st.session_state.csv_bytes = raw
    st.session_state.csv_filename = filename
    for k in list(st.session_state.keys()):
        if k.startswith("filter_"):
            del st.session_state[k]
    pid = st.session_state.get("persist_key")
    if pid:
        _persist_snapshot_write(str(pid))
    return None


def _persist_path(session_id: str) -> Path:
    return _PERSIST_DIR / f"{session_id}.pkl"


def _write_last_active_session(session_id: str) -> None:
    _PERSIST_DIR.mkdir(parents=True, exist_ok=True)
    _LAST_ACTIVE_SESSION.write_text(session_id.strip(), encoding="utf-8")


def _read_last_active_session() -> str | None:
    if not _LAST_ACTIVE_SESSION.is_file():
        return None
    try:
        t = _LAST_ACTIVE_SESSION.read_text(encoding="utf-8").strip()
        return t or None
    except OSError:
        return None


def _query_session_id() -> str | None:
    v = st.query_params.get(_QUERY_SESSION)
    if v is None:
        return None
    if isinstance(v, list):
        return str(v[0]) if v else None
    return str(v)


def _persist_snapshot_write(session_id: str) -> None:
    _PERSIST_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "df": st.session_state.df,
        "timeline_mapping": st.session_state.timeline_mapping,
        "read_params": st.session_state.read_params,
        "csv_filename": st.session_state.get("csv_filename"),
        "csv_bytes": st.session_state.get("csv_bytes"),
        "config_complete": True,
    }
    with open(_persist_path(session_id), "wb") as f:
        pickle.dump(payload, f)
    _write_last_active_session(session_id)


def _persist_snapshot_delete(session_id: str) -> None:
    p = _persist_path(session_id)
    if p.is_file():
        p.unlink()
    if _read_last_active_session() == session_id:
        try:
            _LAST_ACTIVE_SESSION.unlink(missing_ok=True)
        except OSError:
            pass


def _try_restore_session_from_query() -> None:
    """Restaura sesión desde disco: primero ?s=, si no hay, última sesión guardada (reabrir la app)."""
    if (
        st.session_state.get("df") is not None
        and st.session_state.get("timeline_mapping")
        and st.session_state.get("config_complete")
    ):
        return
    session_id = _query_session_id() or _read_last_active_session()
    if not session_id:
        return
    path = _persist_path(session_id)
    if not path.is_file():
        if session_id == _read_last_active_session():
            try:
                _LAST_ACTIVE_SESSION.unlink(missing_ok=True)
            except OSError:
                pass
        return
    try:
        with open(path, "rb") as f:
            data = pickle.load(f)
    except Exception:
        return
    st.session_state.df = data["df"]
    st.session_state.timeline_mapping = data["timeline_mapping"]
    st.session_state.read_params = data["read_params"]
    st.session_state.csv_filename = data.get("csv_filename")
    st.session_state.csv_bytes = data.get("csv_bytes")
    st.session_state.config_complete = bool(data.get("config_complete", True))
    st.session_state.persist_key = session_id
    _sync_url_with_session(session_id)


def _sync_url_with_session(session_id: str) -> None:
    if _query_session_id() != session_id:
        st.query_params[_QUERY_SESSION] = session_id


def _clear_url_session_param() -> None:
    try:
        del st.query_params[_QUERY_SESSION]
    except Exception:
        pass


def _inject_css() -> None:
    st.markdown(
        """
        <style>
            .block-container { padding-top: 0.5rem; padding-bottom: 0.75rem; max-width: 1600px; }
            [data-testid="stSidebar"] [data-testid="stMarkdown"] p { line-height: 1.35; }
            div[data-testid="stMetricValue"] { font-size: 1.2rem; font-weight: 600; }
            .timeline-step-active { font-weight: 600; color: var(--text-color); }
            .timeline-step-idle { opacity: 0.55; }
            h1 { font-size: 1.55rem; margin-bottom: 0.2rem; }
            .tl-toolbar {
                font-size: 0.92rem;
                line-height: 1.25;
                margin: 0 0 0.15rem 0;
                color: var(--text-color);
            }
            .tl-toolbar code {
                font-size: 0.82rem;
                word-break: break-all;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _fmt_sep_for_display(sep: str) -> str:
    if sep == "\t":
        return "TAB"
    if sep == " ":
        return "espacio"
    return repr(sep).strip("'\"")


def _fmt_file_size(n: int) -> str:
    if n >= 1_048_576:
        return f"{n / 1_048_576:.1f} MB"
    if n >= 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n} B"


def _launch_streamlit() -> int:
    app_path = Path(__file__).resolve()
    return subprocess.call([sys.executable, "-m", "streamlit", "run", str(app_path)])


def launch() -> None:
    raise SystemExit(_launch_streamlit())


def _ensure_session_defaults() -> None:
    if "upload_id" not in st.session_state:
        st.session_state.upload_id = 0
    if "config_complete" not in st.session_state:
        st.session_state.config_complete = False


def _clear_all_configuration() -> None:
    """Borra configuración guardada, datos, filtros, snapshot local y parámetro ?s=."""
    sid = st.session_state.get("persist_key") or _query_session_id()
    if sid:
        _persist_snapshot_delete(str(sid))
    _clear_url_session_param()
    st.session_state.pop("persist_key", None)

    for k in list(st.session_state.keys()):
        if k.startswith(("filter_", "filt_", "cfg_")):
            del st.session_state[k]
    for k in (
        "df",
        "csv_bytes",
        "csv_filename",
        "read_params",
        "timeline_mapping",
        "config_complete",
        "lectura_show_preview",
    ):
        st.session_state.pop(k, None)
    st.session_state.config_complete = False
    st.session_state.upload_id = int(st.session_state.upload_id) + 1


def _read_csv_from_bytes(
    raw: bytes,
    *,
    encoding: str,
    sep: str,
    has_header_row: bool,
) -> pd.DataFrame:
    header = 0 if has_header_row else None
    enc = encoding.strip() or "utf-8"
    return read_csv_stream(raw, encoding=enc, sep=sep, header=header)


def _mapping_from_saved(m: dict[str, Any]) -> TimelineColumnMapping:
    return TimelineColumnMapping(
        start_column=m["start_column"],
        end_column=m["end_column"],
        group_columns=tuple(m["group_columns"]),
        label_column=m.get("label_column"),
    )


def _render_sidebar(*, timeline_only: bool) -> None:
    with st.sidebar:
        st.markdown("### Timeline CSV")

        st.divider()
        st.markdown("**Estado**")
        if timeline_only:
            st.markdown(
                '<p class="timeline-step-idle">1. Configuración inicial</p>',
                unsafe_allow_html=True,
            )
            st.markdown(
                '<p class="timeline-step-active">2. Vista timeline</p>',
                unsafe_allow_html=True,
            )
            fname = st.session_state.get("csv_filename") or "—"
            if len(fname) > 32:
                fname = fname[:29] + "…"
            st.caption(f"**Archivo:** {fname}")
            raw = st.session_state.get("csv_bytes")
            if raw:
                st.caption(_fmt_file_size(len(raw)))
            rp = st.session_state.get("read_params") or {}
            with st.expander("Sustituir CSV", expanded=False):
                enc = rp.get("encoding", "—")
                sep_disp = _fmt_sep_for_display(str(rp.get("sep", ",")))
                hdr = "sí" if rp.get("has_header_row", True) else "no"
                st.caption(f"Lectura: **{enc}** · **{sep_disp}** · cab. **{hdr}**")
                st.caption("Mismas columnas que el mapeo guardado.")
                nu = st.file_uploader("CSV", type=["csv"], key="tl_upload_replace", label_visibility="collapsed")
                if st.button(
                    "Aplicar archivo",
                    type="secondary",
                    width="stretch",
                    disabled=nu is None,
                    key="tl_btn_replace_apply",
                ):
                    if nu is not None:
                        err = _apply_replacement_csv(nu.getvalue(), nu.name)
                        if err:
                            st.error(err)
                        else:
                            st.rerun()
            if st.button(
                "Limpiar configuración",
                width="stretch",
                type="secondary",
                help="Vuelve a la pantalla 1 y borra lectura, mapeo y datos en memoria.",
                key="sidebar_clear_config",
            ):
                _clear_all_configuration()
                st.rerun()
        else:
            st.markdown(
                '<p class="timeline-step-active">1. Configuración inicial</p>',
                unsafe_allow_html=True,
            )
            st.markdown(
                '<p class="timeline-step-idle">2. Vista timeline (tras guardar)</p>',
                unsafe_allow_html=True,
            )
            st.caption("Define lectura del CSV y columnas inicio / fin / etiqueta / filtros.")


def render_config_screen() -> None:
    """Pantalla 1: lectura del archivo + mapeo; al guardar se fija la config en memoria."""
    st.markdown("### Configuración inicial")
    st.caption(
        "**Paso único:** cómo leer el archivo y qué columnas usan inicio, fin, etiqueta (eje Y) y filtros. "
        "Al guardar, esta definición queda en memoria y pasas a ver solo el timeline."
    )

    with st.container(border=True):
        st.markdown("**1. Archivo**")
        uploaded = st.file_uploader(
            "CSV",
            type=["csv"],
            label_visibility="collapsed",
            key=f"csv_upload_{st.session_state.upload_id}",
            help="Los datos no salen de tu sesión de navegador.",
        )

    with st.container(border=True):
        st.markdown("**2. Formato de lectura**")
        st.caption("Ajusta codificación y separador (p. ej. Excel en español suele usar `;`).")
        c1, c2 = st.columns(2)
        with c1:
            enc_choice = st.selectbox(
                "Codificación",
                options=list(_ENC_PRESETS) + ["Otro…"],
                key="cfg_enc_choice",
            )
            if enc_choice == "Otro…":
                encoding = st.text_input(
                    "Nombre",
                    value="utf-8",
                    key="cfg_enc_custom",
                ).strip()
            else:
                encoding = enc_choice
        with c2:
            sep_option = st.selectbox(
                "Separador",
                options=[
                    ("coma", ","),
                    ("punto y coma", ";"),
                    ("tabulador", "\t"),
                    ("pipe", "|"),
                    ("personalizado", None),
                ],
                format_func=lambda x: x[0],
                key="cfg_sep_choice",
            )
            sep = sep_option[1]
            if sep is None:
                sep_raw = st.text_input(
                    "Carácter",
                    value=",",
                    max_chars=4,
                    key="cfg_sep_custom",
                    help="Usa \\t para tab",
                )
                sep = sep_raw.replace("\\t", "\t") if sep_raw else ","
        has_header = st.checkbox(
            "Primera fila = cabecera (nombres de columna)",
            value=True,
            key="cfg_header",
        )

    if uploaded is None:
        st.info("Sube un CSV para poder **cargar datos** y elegir columnas.")
        return

    raw = uploaded.getvalue()

    bp, bg = st.columns([1, 1.2])
    with bp:
        preview = st.button("Vista previa (solo lectura)", width="stretch", key="cfg_btn_preview")
    with bg:
        load = st.button(
            "Cargar datos en memoria",
            type="primary",
            width="stretch",
            key="cfg_btn_load",
        )

    if preview:
        st.session_state.lectura_show_preview = True

    if st.session_state.get("lectura_show_preview"):
        with st.expander("Vista previa", expanded=True):
            try:
                prev_df = _read_csv_from_bytes(
                    raw, encoding=encoding, sep=sep, has_header_row=has_header
                )
                st.dataframe(prev_df.head(40), width="stretch", height=360)
                st.caption(f"{len(prev_df):,} filas × {len(prev_df.columns)} columnas.")
            except Exception as e:
                st.error(str(e))

    if load:
        try:
            df = _read_csv_from_bytes(
                raw, encoding=encoding, sep=sep, has_header_row=has_header
            )
        except Exception as e:
            st.error(f"No se pudo leer el CSV: {e}")
            return
        if df.empty or len(df.columns) == 0:
            st.warning("Archivo vacío o sin columnas.")
            return
        old_pid = st.session_state.get("persist_key")
        if old_pid:
            _persist_snapshot_delete(str(old_pid))
        st.session_state.pop("persist_key", None)
        _clear_url_session_param()
        st.session_state.df = df
        st.session_state.csv_bytes = raw
        st.session_state.csv_filename = uploaded.name
        st.session_state.read_params = {
            "encoding": encoding,
            "sep": sep,
            "has_header_row": has_header,
        }
        st.session_state.config_complete = False
        st.session_state.pop("timeline_mapping", None)
        for k in list(st.session_state.keys()):
            if k.startswith(("cfg_start", "cfg_end", "cfg_label", "cfg_filters", "filter_")):
                del st.session_state[k]
        st.session_state.pop("lectura_show_preview", None)
        st.rerun()

    df = st.session_state.get("df")
    if df is None:
        st.caption("Tras **Cargar datos en memoria**, podrás definir el mapeo de columnas.")
        return

    st.divider()
    st.markdown("**3. Columnas del timeline**")
    st.caption("Elige inicio, fin, etiqueta en el eje Y y columnas que alimentarán los filtros en la vista timeline.")

    columns = [str(c) for c in df.columns]

    with st.expander("Diccionario de columnas (referencia)", expanded=False):
        prof = profile_columns(df)
        prof_df = pd.DataFrame(
            {
                "Columna": [p.name for p in prof],
                "Tipo": [p.dtype for p in prof],
                "No nulos": [p.non_null_count for p in prof],
                "Ejemplos": [
                    ", ".join(p.sample_values) if p.sample_values else "—" for p in prof
                ],
            }
        )
        st.dataframe(prof_df, width="stretch", hide_index=True, height=280)

    a, b = st.columns(2)
    with a:
        start_col = st.selectbox("Columna de **inicio** (fecha/hora)", columns, key="cfg_start")
    end_opts = [c for c in columns if c != start_col]
    with b:
        if not end_opts:
            st.error("Se necesitan al menos dos columnas distintas.")
            return
        end_col = st.selectbox("Columna de **fin** (fecha/hora)", end_opts, key="cfg_end")

    label_ph = "— Sin columna (eje Y por número de fila)"
    label_opts = [label_ph] + columns
    label_pick = st.selectbox("Columna **etiqueta** (eje Y)", label_opts, key="cfg_label")
    label_column: str | None = None if label_pick == label_ph else label_pick

    filt_opts = [c for c in columns if c not in (start_col, end_col)]
    filter_cols = st.multiselect(
        "Columnas para **filtros** (combos de valores en el timeline)",
        filt_opts,
        key="cfg_filters",
        placeholder="Ninguna u opcionalmente varias…",
    )

    test_mapping = TimelineColumnMapping(
        start_column=start_col,
        end_column=end_col,
        group_columns=tuple(filter_cols),
        label_column=label_column,
    )
    try:
        test_bars = build_bar_frame(df, test_mapping)
    except KeyError as e:
        st.error(f"Error de columnas: {e}")
        return

    st.caption(f"Vista rápida: **{len(test_bars):,}** barras válidas de **{len(df):,}** filas.")

    if st.button(
        "Guardar configuración y abrir timeline",
        type="primary",
        width="stretch",
        key="cfg_btn_save_open",
    ):
        st.session_state.timeline_mapping = {
            "start_column": start_col,
            "end_column": end_col,
            "group_columns": list(filter_cols),
            "label_column": label_column,
        }
        st.session_state.config_complete = True
        for k in list(st.session_state.keys()):
            if k.startswith("filter_"):
                del st.session_state[k]
        session_id = st.session_state.get("persist_key") or uuid.uuid4().hex
        st.session_state.persist_key = session_id
        _persist_snapshot_write(session_id)
        _sync_url_with_session(session_id)
        st.rerun()


def render_timeline_screen() -> None:
    """Pantalla 2: solo timeline + filtros por valor; sin reconfigurar columnas aquí."""
    df = st.session_state.get("df")
    raw_map = st.session_state.get("timeline_mapping")
    if df is None or not raw_map:
        st.session_state.config_complete = False
        st.rerun()
        return

    mapping = _mapping_from_saved(raw_map)

    try:
        bars = build_bar_frame(df, mapping)
    except Exception:
        st.error("Los datos ya no cuadran con la configuración guardada. Limpia la configuración y vuelve a definirla.")
        if st.button("Limpiar configuración", key="tl_err_clear"):
            _clear_all_configuration()
            st.rerun()
        return

    fname = st.session_state.get("csv_filename") or "datos cargados"
    plot_df = bars.copy()
    lb = mapping.label_column
    if lb is None:
        plot_df["_y_axis"] = "Fila " + plot_df["_row_id"].astype(str)
    else:
        empty = plot_df["bar_label"].astype(str).str.strip() == ""
        plot_df["_y_axis"] = plot_df["bar_label"].astype(str)
        plot_df.loc[empty, "_y_axis"] = "Fila " + plot_df.loc[empty, "_row_id"].astype(str)

    short_fn = fname if len(fname) <= 52 else fname[:49] + "…"
    st.markdown(
        f'<div class="tl-toolbar"><strong>Timeline</strong> · <code>{short_fn}</code> · '
        f"{len(bars):,} barras en dataset</div>",
        unsafe_allow_html=True,
    )

    fc_list = list(mapping.group_columns)
    with st.container(border=True):
        st.markdown("##### Filtros")
        if not fc_list:
            st.warning(
                "No hay **columnas de filtro** en esta configuración. Pulsa **Limpiar configuración** y en el paso 1 "
                "elige una o más columnas en «Columnas para **filtros**»."
            )
        else:
            ncols = min(5, len(fc_list))

            def _bars_with_other_filters(exclude_fc: str) -> pd.DataFrame:
                out = bars
                for c in fc_list:
                    if c == exclude_fc:
                        continue
                    key_c = f"filter_{c}"
                    sel = st.session_state.get(key_c, "(Todos)")
                    if sel != "(Todos)":
                        out = out[out[c].astype(str) == sel]
                return out

            for i in range(0, len(fc_list), ncols):
                chunk = fc_list[i : i + ncols]
                cols_row = st.columns(len(chunk), gap="small")
                for col_el, fc in zip(cols_row, chunk):
                    with col_el:
                        base = _bars_with_other_filters(fc)
                        if fc not in base.columns:
                            values: list[str] = []
                        else:
                            values = sorted(base[fc].dropna().astype(str).unique().tolist())
                        opts_list = ["(Todos)"] + values
                        key_f = f"filter_{fc}"
                        cur = st.session_state.get(key_f)
                        if cur is not None and cur not in opts_list:
                            st.session_state[key_f] = "(Todos)"
                        choice = st.selectbox(
                            fc,
                            opts_list,
                            key=key_f,
                            label_visibility="visible",
                        )
                        if choice != "(Todos)":
                            plot_df = plot_df[plot_df[fc].astype(str) == choice]

    if plot_df.empty:
        st.warning("No hay barras con los filtros actuales.")
        return

    plot_df = plot_df.reset_index(drop=True)
    n_vis = len(plot_df)
    st.caption(f"**{n_vis:,}** barras visibles en el gráfico.")

    def _axis_y_label(t: object) -> str:
        s = str(t)
        return s if len(s) <= 34 else s[:33] + "…"

    y_labels = [_axis_y_label(x) for x in plot_df["_y_axis"]]
    # Slots ordinales únicos: si varias filas comparten etiqueta truncada, Plotly no debe fusionar categorías.
    y_slots = [f"{i:05d}" for i in range(n_vis)]
    chart_df = plot_df.assign(_y_plot=y_labels, _y_slot=y_slots)
    max_y_chars = int(chart_df["_y_plot"].astype(str).str.len().max()) or 8
    margin_l = _timeline_margin_left_px(max_y_chars)
    # bar_start / bar_end son siempre fecha calendario (medianoche); eje e hover sin hora.
    x_tick_fmt = "%d %b %Y"

    def _hover_lines(r: pd.Series) -> str:
        s = pd.Timestamp(r["bar_start"]).normalize()
        e = pd.Timestamp(r["bar_end"]).normalize()
        return (
            f"<b>{r['_y_axis']}</b><br>"
            f"Inicio: {s.strftime('%Y-%m-%d')}<br>"
            f"Fin: {e.strftime('%Y-%m-%d')}"
        )

    h = _timeline_fig_height_px(n_vis)

    fig = px.timeline(
        chart_df,
        x_start="bar_start",
        x_end="bar_end",
        y="_y_slot",
    )
    hover_lines = [_hover_lines(r) for _, r in chart_df.iterrows()]
    fig.update_traces(
        width=0.72,
        marker_line_width=0,
        marker_color="#1f6fa8",
        opacity=0.92,
        hovertext=hover_lines,
        hovertemplate="%{hovertext}<extra></extra>",
    )
    fig.update_layout(
        template="plotly_white",
        xaxis_title=None,
        showlegend=False,
        autosize=False,
        height=h,
        width=None,
        bargap=0.02,
        bargroupgap=0.01,
        margin=dict(
            l=margin_l,
            r=8,
            t=_TL_MARGIN_TOP_PX,
            b=_TL_MARGIN_BOTTOM_PX,
            pad=_TL_MARGIN_PAD,
        ),
        hoverlabel=dict(bgcolor="white", font_size=11, align="left"),
    )
    fig.update_yaxes(
        type="category",
        autorange="reversed",
        tickmode="array",
        tickvals=y_slots,
        ticktext=y_labels,
        title=dict(text="Etiqueta", font=dict(size=_TL_AXIS_TITLE_PX)),
        title_standoff=4,
        tickfont=dict(size=_TL_AXIS_TICK_PX),
        showgrid=False,
        zeroline=False,
        automargin=False,
        fixedrange=True,
    )
    fig.update_xaxes(
        title=dict(text="Tiempo", font=dict(size=_TL_AXIS_TITLE_PX)),
        tickfont=dict(size=_TL_AXIS_TICK_PX),
        tickformat=x_tick_fmt,
        showgrid=True,
        gridcolor="rgba(80,80,80,0.12)",
        gridwidth=1,
        automargin=False,
        fixedrange=False,
    )

    st.plotly_chart(
        fig,
        width="stretch",
        height=h,
        config={"responsive": False},
    )


def main() -> None:
    st.set_page_config(
        page_title="Timeline CSV",
        layout="wide",
        initial_sidebar_state="expanded",
        menu_items={
            "About": "Snapshot en ~/.cache/timeline-streamlit hasta que pulses Limpiar (last_active_session.txt + .pkl)."
        },
    )
    _inject_css()
    _ensure_session_defaults()
    _try_restore_session_from_query()

    complete = bool(st.session_state.get("config_complete"))
    has_df = st.session_state.get("df") is not None
    has_map = bool(st.session_state.get("timeline_mapping"))

    # Si falta algún elemento de la config guardada, forzar pantalla 1
    if complete and has_df and has_map:
        show_timeline = True
    else:
        show_timeline = False
        if complete and (not has_df or not has_map):
            st.session_state.config_complete = False

    _render_sidebar(timeline_only=show_timeline)

    if not show_timeline:
        st.title("Timeline desde CSV")

    if show_timeline:
        pid = st.session_state.get("persist_key")
        if pid:
            _sync_url_with_session(str(pid))
        render_timeline_screen()
    else:
        render_config_screen()


if __name__ == "__main__":
    main()
