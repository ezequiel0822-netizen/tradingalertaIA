from datetime import datetime

from app.config.settings import Settings
from app.database.models import AlertRecord
from app.database.repository import Repository
from app.utils.time_utils import utc_now


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
