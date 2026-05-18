from datetime import datetime, timedelta

from app.config.settings import Settings
from app.database.models import AlertRecord
from app.database.repository import Repository
from app.utils.time_utils import parse_iso_datetime, utc_now


def write_daily_memory_if_needed(
    settings: Settings,
    repository: Repository,
    records: list[AlertRecord],
    sent_count: int,
) -> None:
    if not settings.enable_obsidian_memory:
        return
    if not records and sent_count == 0:
        return

    today = utc_now().date().isoformat()
    state_key = "obsidian_memory_last_date"
    if repository.get_state(state_key) == today:
        return

    vault = settings.obsidian_vault_path
    vault.mkdir(parents=True, exist_ok=True)
    memory_file = vault / "09 - Memoria Automatica.md"

    memecoin_count = sum(1 for record in records if record.category == "memecoin")
    stock_count = sum(1 for record in records if record.category == "stock")
    top_records = sorted(
        records,
        key=lambda record: (
            record.estimate.estimated_gain_pct,
            record.score,
            record.estimate.confidence,
        ),
        reverse=True,
    )[:5]

    lines = [
        f"\n## {today} - Resumen automatico {settings.app_version}",
        "",
        f"- Registros analizados en ciclo: {len(records)}",
        f"- Memecoins analizadas: {memecoin_count}",
        f"- Acciones analizadas: {stock_count}",
        f"- Mensajes Telegram enviados en ciclo: {sent_count}",
        "",
        "### Top candidatos guardados",
    ]

    if not top_records:
        lines.append("- Sin candidatos guardados en este ciclo.")
    else:
        for index, record in enumerate(top_records, start=1):
            lines.append(
                "- "
                f"{index}. {record.snapshot.symbol} ({record.category}) | "
                f"subida est. {record.estimate.estimated_gain_pct:.2f}% | "
                f"confianza {record.estimate.confidence}/100 | "
                f"score {record.score}/100 | enviado: {'si' if record.sent_to_telegram else 'no'}"
            )

    lines.extend(
        [
            "",
            "### Nota de seguridad",
            "- No se guardan tokens, chat IDs reales ni credenciales en esta memoria.",
            "- Las señales son para revision manual, no recomendacion financiera.",
        ]
    )

    if not memory_file.exists():
        memory_file.write_text(
            "# Memoria Automatica\n\nRegistro automatico de resumenes diarios del bot.\n",
            encoding="utf-8",
        )

    with memory_file.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")

    repository.set_state(state_key, today)


def write_weekly_report_if_needed(
    settings: Settings,
    repository: Repository,
) -> None:
    if not settings.enable_weekly_obsidian_report:
        return
    if not settings.enable_obsidian_memory:
        return

    today = utc_now().date()
    state_key = "obsidian_weekly_last_date"
    last_value = repository.get_state(state_key)
    if last_value:
        last_date = _parse_date(last_value)
        if last_date is not None and (today - last_date).days < 7:
            return

    # Import local para evitar ciclo con backtester (que no depende de obsidian_memory).
    from app.learning.backtester import rank_top_strategies
    from app.learning.horizon_evaluator import HORIZONS

    since_iso = (utc_now() - timedelta(days=30)).isoformat()
    horizon_rows_by_h: dict[int, list[dict]] = {}
    total_final = 0
    for horizon in HORIZONS:
        rows = repository.fetch_horizons_by_features(
            horizon_hours=horizon,
            since_iso=since_iso,
            limit=2000,
        )
        horizon_rows_by_h[horizon] = rows
        total_final += len(rows)

    vault = settings.obsidian_vault_path
    vault.mkdir(parents=True, exist_ok=True)
    report_file = vault / "11 - Reporte Semanal.md"

    if not report_file.exists():
        report_file.write_text(
            "# Reporte Semanal Trading Alert AI\n\n"
            "Resumen semanal automatico del aprendizaje local.\n"
            "Solo simulacion. No es recomendacion financiera.\n",
            encoding="utf-8",
        )

    lines = [
        "",
        f"## {today.isoformat()} - Reporte Semanal {settings.app_version}",
        "",
    ]

    if total_final == 0:
        lines.extend(
            [
                "Sin datos suficientes esta semana.",
                "Acumulando snapshots historicos para evaluar horizontes.",
                "",
            ]
        )
    else:
        lines.append("### Resumen")
        for horizon in HORIZONS:
            label = _horizon_label(horizon)
            count = len(horizon_rows_by_h.get(horizon, []))
            lines.append(f"- Outcomes finales {label}: {count}")
        lines.append("")

        top_strategies = rank_top_strategies(
            repository,
            horizon_hours=settings.backtest_default_horizon_hours,
            min_samples=settings.backtest_min_samples,
            top_n=5,
        )
        if top_strategies:
            lines.append(
                f"### Top 5 reglas (horizonte "
                f"{settings.backtest_default_horizon_hours}h)"
            )
            for index, rule in enumerate(top_strategies, start=1):
                lines.append(
                    f"{index}. {rule.rule_label} | n={rule.sample_count} | "
                    f"win {rule.win_rate * 100:.1f}% | "
                    f"avg {rule.avg_return_pct:.2f}% | "
                    f"MFE {rule.avg_mfe_pct:.2f}% | "
                    f"MAE {rule.avg_mae_pct:.2f}% | "
                    f"sharpe {rule.sharpe_approx}"
                )
            lines.append("")

        lines.append("### Retornos medios por horizonte y categoria")
        lines.append("| Categoria | 1h | 6h | 24h | 7d |")
        lines.append("|---|---|---|---|---|")
        for category in ("memecoin", "stock"):
            cells: list[str] = [category]
            for horizon in HORIZONS:
                rows = [
                    row
                    for row in horizon_rows_by_h.get(horizon, [])
                    if str(row.get("category") or "") == category
                ]
                cells.append(_avg_return_cell(rows))
            lines.append("| " + " | ".join(cells) + " |")
        lines.append("")

    lines.extend(
        [
            "### Nota",
            "- Simulacion local. No es recomendacion financiera ni orden real.",
            "- El sistema no compra, no vende, no firma transacciones.",
            "",
        ]
    )

    with report_file.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")

    repository.set_state(state_key, today.isoformat())


def _avg_return_cell(rows: list[dict]) -> str:
    if not rows:
        return "-"
    values: list[float] = []
    for row in rows:
        value = row.get("return_pct")
        if value is None:
            continue
        try:
            values.append(float(value))
        except (TypeError, ValueError):
            continue
    if not values:
        return "-"
    avg = sum(values) / len(values)
    return f"{avg:+.2f}%"


def _horizon_label(hours: int) -> str:
    if hours >= 24 and hours % 24 == 0:
        days = hours // 24
        return f"{days}d"
    return f"{hours}h"


def _parse_date(value: str):
    parsed = parse_iso_datetime(value)
    if parsed is not None:
        return parsed.date()
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        return None
