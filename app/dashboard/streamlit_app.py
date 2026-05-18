import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st

from app.config.settings import load_settings
from app.database.repository import Repository
from app.learning.backtester import backtest_strategy, rank_top_strategies
from app.learning.horizon_evaluator import HORIZONS


settings = load_settings()
st.set_page_config(page_title=f"Trading Alert AI {settings.app_version}", layout="wide")


def _load_table(table_name: str) -> pd.DataFrame:
    if not settings.sqlite_path.exists():
        return pd.DataFrame()
    with sqlite3.connect(settings.sqlite_path) as connection:
        return pd.read_sql_query(
            f"SELECT * FROM {table_name} ORDER BY id DESC",
            connection,
        )


def _parse_json_list(value: str | None) -> str:
    if not value:
        return ""
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return value
    if isinstance(parsed, list):
        return "\n".join(f"- {item}" for item in parsed)
    return str(parsed)


def _filter_by_time(df: pd.DataFrame, column: str, option: str) -> pd.DataFrame:
    if df.empty or column not in df.columns or option == "Todo":
        return df
    df = df.copy()
    df[column] = pd.to_datetime(df[column], errors="coerce", utc=True)
    now = datetime.now(timezone.utc)
    if option == "Ultimas 24h":
        return df[df[column] >= now - timedelta(hours=24)]
    if option == "Ultimos 7 dias":
        return df[df[column] >= now - timedelta(days=7)]
    return df


def _columns(df: pd.DataFrame, names: list[str]) -> list[str]:
    return [name for name in names if name in df.columns]


tokens = _load_table("tokens")
alerts = _load_table("alerts")
outcomes = _load_table("signal_outcomes")
lessons = _load_table("strategy_lessons")
paper_trades = _load_table("paper_trades")
horizons_df = _load_table("alert_outcome_horizons")
snapshots_df = _load_table("price_snapshots")

st.title(f"Trading Alert AI {settings.app_version}")

if tokens.empty and alerts.empty:
    st.info("Todavia no hay datos. Ejecuta `python main.py` para iniciar el monitoreo.")
    st.stop()

with st.sidebar:
    st.header("Filtros")
    chain_options = sorted(set(alerts.get("chain", pd.Series(dtype=str)).dropna().astype(str)))
    category_options = sorted(set(alerts.get("category", pd.Series(dtype=str)).dropna().astype(str)))
    risk_options = sorted(set(alerts.get("risk_level", pd.Series(dtype=str)).dropna().astype(str)))
    type_options = sorted(set(alerts.get("alert_type", pd.Series(dtype=str)).dropna().astype(str)))

    selected_chain = st.selectbox("Chain", ["Todas"] + chain_options)
    selected_category = st.selectbox("Categoria", ["Todas"] + category_options)
    selected_risk = st.selectbox("Riesgo", ["Todos"] + risk_options)
    selected_type = st.selectbox("Tipo de alerta", ["Todos"] + type_options)
    min_score = st.slider("Score minimo", 0, 100, 0)
    min_estimated_gain = st.slider("Subida estimada minima", 0, 2000, 0)
    time_range = st.selectbox("Rango", ["Todo", "Ultimas 24h", "Ultimos 7 dias"])

filtered_alerts = alerts.copy()
if not filtered_alerts.empty:
    if selected_chain != "Todas":
        filtered_alerts = filtered_alerts[filtered_alerts["chain"] == selected_chain]
    if selected_category != "Todas" and "category" in filtered_alerts.columns:
        filtered_alerts = filtered_alerts[filtered_alerts["category"] == selected_category]
    if selected_risk != "Todos":
        filtered_alerts = filtered_alerts[filtered_alerts["risk_level"] == selected_risk]
    if selected_type != "Todos":
        filtered_alerts = filtered_alerts[filtered_alerts["alert_type"] == selected_type]
    filtered_alerts = filtered_alerts[filtered_alerts["score"].fillna(0) >= min_score]
    if "estimated_gain_pct" in filtered_alerts.columns:
        filtered_alerts = filtered_alerts[
            filtered_alerts["estimated_gain_pct"].fillna(0) >= min_estimated_gain
        ]
    filtered_alerts = _filter_by_time(filtered_alerts, "created_at", time_range)

metric_cols = st.columns(5)
metric_cols[0].metric("Tokens detectados", len(tokens))
metric_cols[1].metric("Alertas guardadas", len(alerts))
metric_cols[2].metric("Alertas filtradas", len(filtered_alerts))
sent_count = int(alerts.get("sent_to_telegram", pd.Series(dtype=int)).fillna(0).sum())
metric_cols[3].metric("Telegram enviadas", sent_count)
critical_count = int((alerts.get("risk_level", pd.Series(dtype=str)) == "critical").sum())
metric_cols[4].metric("Criticas", critical_count)

if not alerts.empty and "reasons" in alerts.columns:
    reason_text = alerts["reasons"].fillna("").astype(str)
    pro_count = int(reason_text.str.contains("IA Pro", case=False, regex=False).sum())
    pattern_count = int(reason_text.str.contains("Patron grafico", case=False, regex=False).sum())
    catalyst_count = int(reason_text.str.contains("Noticias/eventos", case=False, regex=False).sum())
    intel_cols = st.columns(3)
    intel_cols[0].metric("Lecturas IA Pro", pro_count)
    intel_cols[1].metric("Patrones detectados", pattern_count)
    intel_cols[2].metric("Catalizadores", catalyst_count)

learning_cols = st.columns(3)
learning_cols[0].metric("Outcomes evaluados", len(outcomes))
learning_cols[1].metric("Lecciones IA", len(lessons))
open_paper = 0
if not paper_trades.empty and "status" in paper_trades.columns:
    open_paper = int((paper_trades["status"] == "open").sum())
learning_cols[2].metric("Paper trades abiertos", open_paper)

st.subheader("Ultimas alertas")
if filtered_alerts.empty:
    st.warning("No hay alertas con los filtros seleccionados.")
else:
    alert_columns = _columns(
        filtered_alerts,
        [
            "created_at",
            "alert_type",
            "category",
            "chain",
            "symbol",
            "name",
            "score",
            "risk_level",
            "estimated_gain_pct",
            "estimated_loss_pct",
            "estimate_confidence",
            "price",
            "liquidity_usd",
            "volume_5m",
            "volume_1h",
            "app_version",
            "sent_to_telegram",
        ],
    )
    st.dataframe(filtered_alerts[alert_columns].head(50), use_container_width=True, hide_index=True)

chart_cols = st.columns(2)
with chart_cols[0]:
    st.subheader("Tokens por score")
    if not tokens.empty and "latest_score" in tokens.columns:
        score_df = tokens[_columns(tokens, ["symbol", "chain", "latest_score"])].dropna()
        score_df = score_df.sort_values("latest_score", ascending=False).head(30)
        st.bar_chart(score_df.set_index("symbol")["latest_score"])

with chart_cols[1]:
    st.subheader("Tokens por chain")
    if not tokens.empty and "chain" in tokens.columns:
        st.bar_chart(tokens["chain"].value_counts())

st.subheader("Alertas criticas")
critical_alerts = alerts[alerts.get("risk_level", pd.Series(dtype=str)) == "critical"]
if critical_alerts.empty:
    st.caption("Sin alertas criticas guardadas.")
else:
    critical_columns = _columns(
        critical_alerts,
        [
            "created_at",
            "alert_type",
            "chain",
            "symbol",
            "score",
            "estimated_loss_pct",
            "estimate_confidence",
            "security_summary",
            "token_address",
        ],
    )
    st.dataframe(critical_alerts[critical_columns].head(50), use_container_width=True, hide_index=True)

st.subheader("Rendimiento por horizonte")
st.caption(
    "Outcomes 1h/6h/24h/7d con MFE/MAE. Solo simulacion local. "
    "Los horizontes finales requieren snapshots historicos suficientes."
)

horizon_metric_cols = st.columns(3)
final_count = 0
pending_count = 0
if not horizons_df.empty and "status" in horizons_df.columns:
    final_count = int((horizons_df["status"] == "final").sum())
    pending_count = int((horizons_df["status"] == "pending").sum())
horizon_metric_cols[0].metric("Snapshots historicos", len(snapshots_df))
horizon_metric_cols[1].metric("Horizontes finales", final_count)
horizon_metric_cols[2].metric("Horizontes pendientes", pending_count)

if horizons_df.empty or "horizon_hours" not in horizons_df.columns:
    st.caption(
        "Aun no hay outcomes por horizonte. Deja correr el monitor "
        "para acumular snapshots historicos."
    )
else:
    finals = horizons_df[horizons_df["status"] == "final"].copy()
    if finals.empty:
        st.caption("Sin horizontes finales todavia. Necesitas snapshots dentro de cada ventana.")
    else:
        merged = finals.merge(
            alerts[_columns(alerts, ["id", "category", "symbol"])].rename(
                columns={"id": "alert_id"}
            ),
            on="alert_id",
            how="left",
        )
        merged["category"] = merged["category"].fillna("unknown")
        summary = (
            merged.groupby(["category", "horizon_hours"])
            .agg(
                count=("return_pct", "size"),
                avg_return=("return_pct", "mean"),
                avg_mfe=("mfe_pct", "mean"),
                avg_mae=("mae_pct", "mean"),
            )
            .reset_index()
            .sort_values(["category", "horizon_hours"])
        )
        summary["avg_return"] = summary["avg_return"].round(2)
        summary["avg_mfe"] = summary["avg_mfe"].round(2)
        summary["avg_mae"] = summary["avg_mae"].round(2)
        st.markdown("**Promedios por categoria x horizonte**")
        st.dataframe(summary, use_container_width=True, hide_index=True)

        horizon_choice = st.selectbox(
            "Horizonte para equity curve y ranking",
            options=list(HORIZONS),
            index=list(HORIZONS).index(settings.backtest_default_horizon_hours)
            if settings.backtest_default_horizon_hours in HORIZONS
            else 2,
            format_func=lambda h: f"{h}h" if h < 24 else f"{h // 24}d",
        )
        repo_for_dashboard = Repository(settings.sqlite_path)
        equity_result = backtest_strategy(
            repo_for_dashboard,
            filter_features=[],
            horizon_hours=int(horizon_choice),
        )
        st.markdown(
            f"**Equity curve simulada — todas las alertas ({horizon_choice}h, "
            f"n={equity_result.sample_count})**"
        )
        if equity_result.equity_curve:
            curve_df = pd.DataFrame(
                {"equity": equity_result.equity_curve},
                index=range(1, len(equity_result.equity_curve) + 1),
            )
            st.line_chart(curve_df)
            stats_cols = st.columns(4)
            stats_cols[0].metric("Win rate", f"{equity_result.win_rate * 100:.1f}%")
            stats_cols[1].metric("Avg return", f"{equity_result.avg_return_pct:.2f}%")
            stats_cols[2].metric("Avg MFE", f"{equity_result.avg_mfe_pct:.2f}%")
            stats_cols[3].metric("Avg MAE", f"{equity_result.avg_mae_pct:.2f}%")
        else:
            st.caption("Sin trades simulados para esta ventana.")

        ranking = rank_top_strategies(
            repo_for_dashboard,
            horizon_hours=int(horizon_choice),
            min_samples=settings.backtest_min_samples,
            top_n=10,
        )
        st.markdown("**Ranking top reglas (sharpe descendiente)**")
        if ranking:
            ranking_rows = []
            for rule in ranking:
                ranking_rows.append(
                    {
                        "rule": rule.rule_label,
                        "n": rule.sample_count,
                        "win_rate": f"{rule.win_rate * 100:.1f}%",
                        "avg_return": f"{rule.avg_return_pct:.2f}%",
                        "avg_mfe": f"{rule.avg_mfe_pct:.2f}%",
                        "avg_mae": f"{rule.avg_mae_pct:.2f}%",
                        "sharpe": rule.sharpe_approx,
                    }
                )
            st.dataframe(pd.DataFrame(ranking_rows), use_container_width=True, hide_index=True)
        else:
            st.caption(
                f"Sin reglas con al menos {settings.backtest_min_samples} casos en este horizonte."
            )

st.subheader("Tokens detectados")
if tokens.empty:
    st.caption("Sin tokens detectados.")
else:
    token_columns = _columns(
        tokens,
        [
            "last_seen_at",
            "category",
            "chain",
            "symbol",
            "name",
            "latest_score",
            "latest_risk_level",
            "latest_estimated_gain_pct",
            "latest_estimated_loss_pct",
            "latest_estimate_confidence",
            "latest_price",
            "latest_liquidity_usd",
            "latest_volume_5m",
            "latest_volume_1h",
            "source",
            "token_address",
        ],
    )
    st.dataframe(tokens[token_columns].head(200), use_container_width=True, hide_index=True)

st.subheader("Historial de alertas")
if filtered_alerts.empty:
    st.caption("Sin historial para los filtros actuales.")
else:
    history = filtered_alerts.copy()
    if "reasons" in history.columns:
        history["reasons"] = history["reasons"].apply(_parse_json_list)
    if "estimate_summary" in history.columns:
        history["estimate_summary"] = history["estimate_summary"].apply(_parse_json_list)

    history_columns = _columns(
        history,
        [
            "created_at",
            "alert_type",
            "category",
            "chain",
            "symbol",
            "score",
            "risk_level",
            "estimated_gain_pct",
            "estimated_loss_pct",
            "estimate_confidence",
            "reasons",
            "estimate_summary",
            "security_summary",
            "token_address",
        ],
    )
    st.dataframe(history[history_columns].head(200), use_container_width=True, hide_index=True)

st.subheader("Aprendizaje IA")
if lessons.empty:
    st.caption("Sin lecciones suficientes todavia.")
else:
    lesson_columns = _columns(
        lessons,
        [
            "feature",
            "category",
            "sample_count",
            "win_rate",
            "avg_return_pct",
            "confidence",
            "lesson",
            "updated_at",
        ],
    )
    st.dataframe(lessons[lesson_columns].head(80), use_container_width=True, hide_index=True)

st.subheader("Paper trading simulado")
if paper_trades.empty:
    st.caption("Sin simulaciones abiertas o cerradas.")
else:
    paper_columns = _columns(
        paper_trades,
        [
            "status",
            "symbol",
            "category",
            "readiness_grade",
            "entry_price",
            "latest_price",
            "unrealized_return_pct",
            "stop_loss",
            "take_profit_1",
            "take_profit_2",
            "thesis",
            "opened_at",
            "updated_at",
        ],
    )
    st.dataframe(paper_trades[paper_columns].head(100), use_container_width=True, hide_index=True)
