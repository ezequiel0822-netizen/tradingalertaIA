from app.database.models import AlertRecord

# v3.13.2 — título por mercado. Antes todo lo que no era "stock" salía como
# "TOP MEMECOINS" (forex y oro incluidos), con las memecoins apagadas desde v3.7.0.
CATEGORY_TITLES = {
    "stock": "TOP BOLSA",
    "forex": "TOP FOREX",
    "gold": "TOP ORO",
    "memecoin": "TOP MEMECOINS",
    "memecoin_early": "TOP MEMECOINS",
    "memecoin_mature": "TOP MEMECOINS",
}


def _money(value: float | None) -> str:
    if value is None:
        return "unknown"
    if value < 0.01:
        return f"{value:.10f}"
    return f"{value:,.2f}"


def _percent(value: float | None) -> str:
    if value is None:
        return "unknown"
    return f"{value:,.2f}%"


def _signed_percent(value: float | None) -> str:
    if value is None:
        return "n/d"
    return f"{value:+.2f}%"


def _value(value: object | None) -> str:
    if value is None or value == "":
        return "unknown"
    return str(value)


def _price(value: float | None, category: str) -> str:
    # forex con 5 decimales (EURUSD 1.12345): 2 decimales escondían el movimiento.
    if value is not None and category == "forex":
        return f"{value:.5f}"
    return f"${_money(value)}"


def format_grouped_telegram_alert(
    records: list[AlertRecord],
    category: str,
    app_version: str,
) -> str:
    title = CATEGORY_TITLES.get(category, f"TOP {category.upper()}")
    lines = [f"🚨 Trading Alert AI {app_version} / {title}", ""]
    lines.append(f"Señales seleccionadas: {len(records)}")
    lines.append("")

    for index, record in enumerate(records, start=1):
        snapshot = record.snapshot
        top_reason = record.reasons[0] if record.reasons else "Candidato rankeado por el sistema."
        if record.category in {"forex", "gold"}:
            # v3.13.2: el movimiento OBSERVADO. Sin "subida/caída estimada" (el bot no
            # tiene edge en forex/oro) ni score/confianza: ambos salían de fórmulas de
            # memecoins (liquidez de pool, boost...) y para un par no significan nada.
            detail = [
                f"Mov. 1h: {_signed_percent(snapshot.price_change_1h)} | "
                f"24h: {_signed_percent(snapshot.price_change_24h)}"
            ]
        else:
            detail = [
                f"Subida est.: {_percent(record.estimate.estimated_gain_pct)} | "
                f"Caída est.: {_percent(record.estimate.estimated_loss_pct)}",
                f"Confianza: {record.estimate.confidence}/100 | Score: {record.score}/100",
            ]
        lines.extend(
            [
                f"{index}. {_value(snapshot.symbol)} / {_value(snapshot.name)}",
                f"Tipo: {record.alert_type}",
                f"Chain/Fuente: {_value(snapshot.chain)} / {_value(snapshot.source)}",
                f"Precio: {_price(snapshot.price, record.category)}",
                *detail,
                f"Motivo: {top_reason}",
                "",
            ]
        )

    lines.append("⚠️ No es recomendación financiera. Son señales para revisión manual.")
    return "\n".join(lines)
