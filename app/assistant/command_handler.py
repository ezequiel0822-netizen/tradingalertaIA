from app.analyzers.news_analyzer import analyze_news
from app.analyzers.technical_patterns import analyze_ohlcv
from app.config.settings import Settings
from app.collectors.news_collector import NewsCollector
from app.collectors.stock_collector import StockCollector
from app.database.repository import Repository


DISCLAIMER = "No es recomendacion financiera. Revisar manualmente."


class BasicTelegramAssistant:
    def __init__(self, settings: Settings, repository: Repository) -> None:
        self.settings = settings
        self.repository = repository

    def handle(self, text: str) -> str:
        raw = text.strip()
        normalized = raw.lower().strip()

        if not normalized:
            return self.help_message()

        if normalized in {"/start", "/help", "help", "ayuda", "/ayuda"}:
            return self.help_message()

        if normalized in {"/status", "status", "estado", "/estado"}:
            return self.status_message()

        if normalized in {"/cupos", "cupos", "alertas restantes"}:
            return self.cupos_message()

        if normalized in {"/top_memecoins", "top memecoins", "top memes", "mejores memecoins"}:
            return self.top_message("memecoin")

        if normalized in {"/top_stocks", "top stocks", "top acciones", "mejores acciones"}:
            return self.top_message("stock")

        if normalized in {"/top", "top", "mejor", "mejores", "que es lo mejor ahorita"}:
            return self.combined_top_message()

        if normalized in {"/alertas", "/ultimas_alertas", "alertas", "ultimas alertas"}:
            return self.recent_alerts_message()

        if normalized in {"/descartes", "descartes", "descartados"}:
            return self.discards_message()

        if normalized in {"/config", "config", "configuracion"}:
            return self.config_message()

        if normalized in {"/pausar", "pausar", "pausa alertas"}:
            self.repository.set_state("alerts_paused", "true")
            return "Alertas pausadas. Seguire monitoreando y guardando historial, pero no enviare alertas automaticas."

        if normalized in {"/reanudar", "reanudar", "activar alertas"}:
            self.repository.set_state("alerts_paused", "false")
            return f"Alertas reanudadas. Volvere a enviar solo los mejores candidatos segun cupos {self.settings.app_version}."

        if normalized.startswith("/analiza ") or normalized.startswith("analiza "):
            query = raw.split(" ", 1)[1]
            return self.analyze_message(query)

        if normalized.startswith("/noticias ") or normalized.startswith("noticias "):
            query = raw.split(" ", 1)[1]
            return self.news_message(query)

        if normalized.startswith("/patron ") or normalized.startswith("patron ") or normalized.startswith("grafico "):
            query = raw.split(" ", 1)[1]
            return self.pattern_message(query)

        if "por que" in normalized or "porque" in normalized:
            return self.recent_alerts_message(limit=3)

        return (
            "No entendi ese mensaje. Prueba con /help, /status, /top, "
            "/top_memecoins, /top_stocks, /alertas o /analiza NVDA."
        )

    def help_message(self) -> str:
        return f"""Trading Alert AI {self.settings.app_version} - asistente basico

Comandos:
/status - estado del sistema y cupos
/cupos - alertas restantes por categoria
/top - mejores memecoins y acciones
/top_memecoins - mejores memecoins guardadas
/top_stocks - mejores acciones guardadas
/alertas - ultimas alertas guardadas
/descartes - mejores candidatos no enviados
/analiza SIMBOLO_O_ADDRESS - resumen de un activo
/noticias SIMBOLO - titulares/eventos recientes
/patron SIMBOLO - patron tecnico basico para acciones
/pausar - pausa alertas automaticas
/reanudar - reactiva alertas automaticas
/config - ver configuracion sin secretos

Solo observo datos publicos. No compro, no vendo y no conecto wallets."""

    def status_message(self) -> str:
        paused = self.repository.alerts_paused()
        memecoin_sent = self.repository.sent_alert_count(
            "memecoin", self.settings.alert_cap_window_hours
        )
        stock_sent = self.repository.sent_alert_count(
            "stock", self.settings.alert_cap_window_hours
        )
        memecoin_left = max(self.settings.memecoin_max_alerts_per_24h - memecoin_sent, 0)
        stock_left = max(self.settings.stock_max_alerts_per_24h - stock_sent, 0)

        return f"""Estado Trading Alert AI {self.settings.app_version}

Alertas automaticas: {"pausadas" if paused else "activas"}
Ventana de cupos: {self.settings.alert_cap_window_hours}h
Memecoins enviadas: {memecoin_sent}/{self.settings.memecoin_max_alerts_per_24h}
Memecoins restantes: {memecoin_left}
Bolsa enviadas: {stock_sent}/{self.settings.stock_max_alerts_per_24h}
Bolsa restantes: {stock_left}

Modo: read-only, sin compras ni ordenes."""

    def cupos_message(self) -> str:
        memecoin_sent = self.repository.sent_alert_count(
            "memecoin", self.settings.alert_cap_window_hours
        )
        stock_sent = self.repository.sent_alert_count(
            "stock", self.settings.alert_cap_window_hours
        )
        memecoin_left = max(self.settings.memecoin_max_alerts_per_24h - memecoin_sent, 0)
        stock_left = max(self.settings.stock_max_alerts_per_24h - stock_sent, 0)
        return f"""Cupos restantes ({self.settings.alert_cap_window_hours}h)

Memecoins: {memecoin_left} restantes ({memecoin_sent}/{self.settings.memecoin_max_alerts_per_24h} usados)
Bolsa: {stock_left} restantes ({stock_sent}/{self.settings.stock_max_alerts_per_24h} usados)

Por ciclo:
Memecoins: max {self.settings.memecoin_max_alerts_per_run}
Bolsa: max {self.settings.stock_max_alerts_per_run}"""

    def top_message(self, category: str, limit: int = 5) -> str:
        rows = self.repository.top_tokens(category, limit)
        title = "Memecoins" if category == "memecoin" else "Bolsa"
        if not rows:
            return f"Todavia no hay datos para {title}. Ejecuta el monitor un rato mas."

        lines = [f"Top {title} guardado:"]
        for index, row in enumerate(rows, start=1):
            lines.append(self._format_token_row(index, row))
        lines.append(DISCLAIMER)
        return "\n".join(lines)

    def combined_top_message(self) -> str:
        return self.top_message("memecoin", 3) + "\n\n" + self.top_message("stock", 3)

    def recent_alerts_message(self, limit: int = 5) -> str:
        rows = self.repository.recent_alerts_by_category(limit=limit)
        if not rows:
            return "Todavia no hay alertas guardadas."

        lines = ["Ultimas alertas guardadas:"]
        for index, row in enumerate(rows, start=1):
            symbol = row.get("symbol") or "unknown"
            category = row.get("category") or "memecoin"
            alert_type = row.get("alert_type") or "unknown"
            gain = self._fmt_pct(row.get("estimated_gain_pct"))
            confidence = row.get("estimate_confidence") or "unknown"
            sent = "si" if row.get("sent_to_telegram") else "no"
            lines.append(
                f"{index}. {symbol} ({category}) {alert_type} | subida {gain} | confianza {confidence}/100 | enviada: {sent}"
            )
        lines.append(DISCLAIMER)
        return "\n".join(lines)

    def discards_message(self, limit: int = 8) -> str:
        rows = self.repository.recent_unsent_alerts(limit=limit)
        if not rows:
            return "No hay descartes recientes guardados."

        lines = ["Mejores candidatos NO enviados:"]
        for index, row in enumerate(rows, start=1):
            symbol = row.get("symbol") or "unknown"
            category = row.get("category") or "memecoin"
            gain = self._fmt_pct(row.get("estimated_gain_pct"))
            confidence = row.get("estimate_confidence") or "unknown"
            score = row.get("score") or "unknown"
            reason = self._discard_reason(row)
            lines.append(
                f"{index}. {symbol} ({category}) | subida {gain} | confianza {confidence}/100 | score {score}/100 | {reason}"
            )
        lines.append(DISCLAIMER)
        return "\n".join(lines)

    def analyze_message(self, query: str) -> str:
        row = self.repository.find_token(query)
        if not row:
            return f"No encontre datos guardados para: {query}. Espera a que el monitor lo detecte o revisa el simbolo/address."

        symbol = row.get("symbol") or "unknown"
        name = row.get("name") or "unknown"
        category = row.get("category") or "memecoin"
        chain = row.get("chain") or "unknown"
        price = row.get("latest_price")
        liquidity = row.get("latest_liquidity_usd")
        score = row.get("latest_score")
        risk = row.get("latest_risk_level") or "unknown"
        gain = self._fmt_pct(row.get("latest_estimated_gain_pct"))
        loss = self._fmt_pct(row.get("latest_estimated_loss_pct"))
        confidence = row.get("latest_estimate_confidence") or "unknown"

        return f"""Analisis basico: {symbol} / {name}

Categoria: {category}
Chain: {chain}
Precio: {self._fmt_money(price)}
Liquidez/volumen ref: {self._fmt_money(liquidity)}
Score: {score}/100
Riesgo: {risk}
Subida estimada: {gain}
Caida estimada: {loss}
Confianza: {confidence}/100

Lectura: {'candidato fuerte para revisar' if self._as_float(row.get('latest_estimated_gain_pct')) >= self._threshold_for(category) else 'solo watchlist por ahora'}.
{DISCLAIMER}"""

    def config_message(self) -> str:
        return f"""Config sin secretos:

Version: {self.settings.app_version}
Assistant Telegram: {"activo" if self.settings.enable_telegram_assistant else "apagado"}
Memecoin min subida: {self.settings.min_estimated_gain_pct}%
Stock min subida: {self.settings.min_stock_estimated_gain_pct}%
Cupo memecoins: {self.settings.memecoin_max_alerts_per_24h}/{self.settings.alert_cap_window_hours}h
Cupo bolsa: {self.settings.stock_max_alerts_per_24h}/{self.settings.alert_cap_window_hours}h
Stocks: {", ".join(symbol.upper() for symbol in self.settings.stock_symbols[:20])}
Chains: {", ".join(self.settings.chains_to_monitor)}
"""

    def news_message(self, query: str) -> str:
        symbol = query.strip().upper()
        if not symbol:
            return "Dime un simbolo. Ejemplo: /noticias NVDA"

        items = NewsCollector(self.settings).collect_for_symbol(symbol)
        label, score, reasons = analyze_news(items)
        lines = [f"Noticias/eventos para {symbol}", f"Lectura: {label} | score {score}"]
        lines.extend(f"- {reason}" for reason in reasons[:6])
        lines.append(DISCLAIMER)
        return "\n".join(lines)

    def pattern_message(self, query: str) -> str:
        symbol = query.strip().upper()
        if not symbol:
            return "Dime un simbolo. Ejemplo: /patron NVDA"

        snapshot = StockCollector(self.settings)._fetch_symbol(symbol)
        if not snapshot:
            return f"No pude obtener grafico publico para {symbol}."

        candles = snapshot.raw.get("candles") or []
        pattern = analyze_ohlcv(candles)
        lines = [
            f"Patron tecnico para {symbol}",
            f"Lectura: {pattern.label}",
            f"Tendencia: {pattern.trend}",
            f"Score patron: {pattern.score}",
            f"RSI: {pattern.rsi if pattern.rsi is not None else 'unknown'}",
        ]
        lines.extend(f"- {reason}" for reason in pattern.reasons[:5])
        lines.append(DISCLAIMER)
        return "\n".join(lines)

    def _format_token_row(self, index: int, row: dict) -> str:
        symbol = row.get("symbol") or "unknown"
        chain = row.get("chain") or "unknown"
        gain = self._fmt_pct(row.get("latest_estimated_gain_pct"))
        loss = self._fmt_pct(row.get("latest_estimated_loss_pct"))
        confidence = row.get("latest_estimate_confidence") or "unknown"
        score = row.get("latest_score") or "unknown"
        return (
            f"{index}. {symbol} [{chain}] | subida {gain} | caida {loss} | "
            f"confianza {confidence}/100 | score {score}/100"
        )

    def _discard_reason(self, row: dict) -> str:
        category = row.get("category") or "memecoin"
        gain = self._as_float(row.get("estimated_gain_pct")) or 0
        confidence = int(row.get("estimate_confidence") or 0)
        threshold = self._threshold_for(category)
        min_confidence = (
            self.settings.min_stock_estimate_confidence
            if category == "stock"
            else self.settings.min_estimate_confidence
        )
        if gain < threshold:
            return "no alcanzo la subida minima"
        if confidence < min_confidence:
            return "confianza insuficiente"
        return "cupo lleno, duplicado o fuera del top"

    def _threshold_for(self, category: str) -> float:
        if category == "stock":
            return self.settings.min_stock_estimated_gain_pct
        return self.settings.min_estimated_gain_pct

    def _fmt_pct(self, value: object) -> str:
        number = self._as_float(value)
        if number is None:
            return "unknown"
        return f"{number:,.2f}%"

    def _fmt_money(self, value: object) -> str:
        number = self._as_float(value)
        if number is None:
            return "unknown"
        return f"${number:,.4f}" if number < 1 else f"${number:,.2f}"

    def _as_float(self, value: object) -> float | None:
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
