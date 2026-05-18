from app.analyzers.filing_analyzer import analyze_filings
from app.analyzers.news_analyzer import analyze_news
from app.analyzers.pro_intelligence import analyze_professional_setup
from app.analyzers.technical_patterns import analyze_ohlcv
from app.config.settings import Settings
from app.collectors.news_collector import NewsCollector
from app.collectors.sec_collector import SECFilingsCollector
from app.collectors.stock_collector import StockCollector
from app.database.models import SecuritySummary, TokenSnapshot
from app.database.repository import Repository
from app.learning.backtester import (
    BacktestResult,
    backtest_strategy,
    rank_top_strategies,
)
from app.learning.horizon_evaluator import HORIZONS
from app.learning.training_engine import run_learning_cycle
from app.utils.time_utils import parse_iso_datetime, utc_now


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

        if normalized in {"/aprendizaje", "aprendizaje", "que aprendiste", "/learning"}:
            return self.learning_message()

        if normalized in {"/paper", "paper", "simulacion", "/paper_trades"}:
            return self.paper_message()

        if normalized in {"/entrenar", "entrenar", "train", "/train"}:
            return self.train_message()

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

        if normalized.startswith("/filings ") or normalized.startswith("filings "):
            query = raw.split(" ", 1)[1]
            return self.filings_message(query)

        if normalized.startswith("/patron ") or normalized.startswith("patron ") or normalized.startswith("grafico "):
            query = raw.split(" ", 1)[1]
            return self.pattern_message(query)

        if normalized.startswith("/pro ") or normalized.startswith("pro ") or normalized.startswith("/tesis "):
            query = raw.split(" ", 1)[1]
            return self.pro_message(query)

        if normalized.startswith("/horizontes") or normalized.startswith("horizontes") or normalized.startswith("/horizons"):
            parts = raw.split(" ", 1)
            query = parts[1] if len(parts) > 1 else ""
            return self.horizons_message(query)

        if normalized.startswith("/backtest") or normalized.startswith("backtest") or normalized.startswith("/bt"):
            parts = raw.split(" ", 1)
            args = parts[1] if len(parts) > 1 else ""
            return self.backtest_message(args)

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
/aprendizaje - lecciones que la IA aprendio del historial
/paper - setups simulados en papel
/entrenar - correr aprendizaje local ahora
/analiza SIMBOLO_O_ADDRESS - resumen de un activo
/noticias SIMBOLO - titulares/eventos recientes
/filings SIMBOLO - filings SEC recientes para acciones
/patron SIMBOLO - patron tecnico basico para acciones
/pro SIMBOLO - lectura profesional: grafico, noticias, filings, riesgos
/horizontes SIMBOLO - retornos por horizonte (1h/6h/24h/7d) y MFE/MAE
/backtest [Nh] [filtros] - top reglas o test de una combinacion (ej: /backtest 24h ia_pro,score:80-90)
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
IA Pro: {"activa" if self.settings.enable_pro_intelligence else "apagada"}
SEC filings: {"activo" if self.settings.enable_sec_filings_intel else "apagado"}
Learning engine: {"activo" if self.settings.enable_learning_engine else "apagado"}
Paper trading simulado: {"activo" if self.settings.enable_paper_trading else "apagado"}
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

    def learning_message(self, limit: int = 8) -> str:
        lessons = self.repository.fetch_strategy_lessons(limit=limit)
        runs = self.repository.latest_training_runs(limit=1)
        if not lessons:
            return "Todavia no hay suficientes outcomes para aprender. Deja correr el monitor mas tiempo o usa /entrenar."

        lines = ["Aprendizaje local de Trading Alert AI"]
        if runs:
            lines.append(f"Ultimo entrenamiento: {runs[0].get('summary')}")
        for index, lesson in enumerate(lessons, start=1):
            win_rate = self._fmt_pct((self._as_float(lesson.get("win_rate")) or 0) * 100)
            avg_return = self._fmt_pct(lesson.get("avg_return_pct"))
            sample_count = lesson.get("sample_count") or 0
            feature = lesson.get("feature") or "unknown"
            category = lesson.get("category") or "unknown"
            lines.append(
                f"{index}. {feature} ({category}) | casos {sample_count} | win {win_rate} | retorno medio {avg_return}"
            )
            lines.append(f"   {lesson.get('lesson')}")
        lines.append(DISCLAIMER)
        return "\n".join(lines)

    def paper_message(self, limit: int = 8) -> str:
        trades = self.repository.fetch_paper_trades(status="open", limit=limit)
        if not trades:
            return "No hay paper trades abiertos. El sistema solo simula setups A/B, nunca opera real."

        lines = ["Paper trades abiertos (simulados, no reales):"]
        for index, trade in enumerate(trades, start=1):
            symbol = trade.get("symbol") or "unknown"
            grade = trade.get("readiness_grade") or "unknown"
            entry = self._fmt_money(trade.get("entry_price"))
            latest = self._fmt_money(trade.get("latest_price"))
            ret = self._fmt_pct(trade.get("unrealized_return_pct"))
            status = trade.get("status") or "open"
            lines.append(
                f"{index}. {symbol} grade {grade} | entry {entry} | latest {latest} | PnL sim {ret} | {status}"
            )
        lines.append("Esto es simulacion educativa local, no orden real.")
        return "\n".join(lines)

    def train_message(self) -> str:
        if not self.settings.enable_learning_engine:
            return "Learning engine esta apagado en config."
        result = run_learning_cycle(self.settings, self.repository)
        return f"""Entrenamiento local completado.

{result.summary}

Ahora puedes usar /aprendizaje y /paper.
{DISCLAIMER}"""

    def filings_message(self, query: str) -> str:
        symbol = query.strip().upper()
        if not symbol:
            return "Dime un simbolo. Ejemplo: /filings NVDA"

        filings = SECFilingsCollector(self.settings).collect_for_symbol(symbol)
        label, score, reasons = analyze_filings(filings)
        lines = [f"Filings SEC para {symbol}", f"Lectura: {label} | score {score}"]
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

    def pro_message(self, query: str) -> str:
        symbol = query.strip().upper()
        if not symbol:
            return "Dime un simbolo. Ejemplo: /pro NVDA"

        snapshot = StockCollector(self.settings)._fetch_symbol(symbol)
        pattern = None
        news_label = "no_recent_news"
        news_score = 0
        filing_label = "no_recent_filings"
        filing_score = 0
        news_reasons: list[str] = []
        filing_reasons: list[str] = []

        if snapshot:
            candles = snapshot.raw.get("candles") or []
            pattern = analyze_ohlcv(candles)
            news_items = NewsCollector(self.settings).collect_for_symbol(symbol)
            news_label, news_score, news_reasons = analyze_news(news_items)
            filings = SECFilingsCollector(self.settings).collect_for_symbol(symbol)
            filing_label, filing_score, filing_reasons = analyze_filings(filings)
        else:
            row = self.repository.find_token(symbol)
            if not row:
                return f"No encontre datos para {symbol}. Prueba con una accion configurada, por ejemplo /pro NVDA."
            snapshot = self._snapshot_from_row(row)

        pro = analyze_professional_setup(
            snapshot,
            SecuritySummary(raw_summary="unknown"),
            pattern,
            news_label,
            news_score,
            filing_label,
            filing_score,
        )

        lines = [
            f"IA Pro para {symbol}",
            f"Lectura: {pro.label} | sesgo {pro.bias} | score {pro.score}",
            f"Confianza: {pro.confidence}/100",
            f"Setup: {pro.setup}",
        ]
        if pattern and pattern.sparkline:
            lines.append(f"Grafico: {pattern.sparkline}")
        if pattern:
            lines.append(
                f"RSI {pattern.rsi if pattern.rsi is not None else 'unknown'} | "
                f"Volumen rel. {pattern.relative_volume if pattern.relative_volume is not None else 'unknown'}x | "
                f"ATR {pattern.atr_pct if pattern.atr_pct is not None else 'unknown'}%"
            )
        lines.append("Razones:")
        lines.extend(f"- {reason}" for reason in pro.reasons[:5])
        if news_reasons:
            lines.append("Noticias:")
            lines.extend(f"- {reason}" for reason in news_reasons[:3])
        if filing_reasons:
            lines.append("SEC:")
            lines.extend(f"- {reason}" for reason in filing_reasons[:3])
        lines.append("Riesgos:")
        lines.extend(f"- {risk}" for risk in pro.risks[:4])
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

    def _snapshot_from_row(self, row: dict) -> TokenSnapshot:
        return TokenSnapshot(
            chain=row.get("chain") or "unknown",
            token_address=row.get("token_address") or "",
            category=row.get("category") or "memecoin",
            symbol=row.get("symbol") or "unknown",
            name=row.get("name") or "unknown",
            source=row.get("source") or "SQLite",
            price=self._as_float(row.get("latest_price")),
            liquidity_usd=self._as_float(row.get("latest_liquidity_usd")),
            volume_5m=self._as_float(row.get("latest_volume_5m")),
            volume_1h=self._as_float(row.get("latest_volume_1h")),
            volume_24h=self._as_float(row.get("latest_volume_24h")),
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

    def horizons_message(self, query: str) -> str:
        symbol_or_addr = query.strip()
        if not symbol_or_addr:
            return "Dime un simbolo o address. Ejemplo: /horizontes NVDA"

        token = self.repository.find_token(symbol_or_addr)
        if not token:
            return f"No encontre datos guardados para: {symbol_or_addr}."

        chain = str(token.get("chain") or "")
        token_address = str(token.get("token_address") or "")
        alert = self.repository.latest_alert_for_token(chain, token_address)
        if not alert:
            return (
                f"No encontre alertas guardadas para {symbol_or_addr}. "
                "Espera a que el monitor genere alguna."
            )

        horizons = self.repository.fetch_alert_outcome_horizons(
            alert_id=int(alert["id"]),
            limit=len(HORIZONS) + 2,
        )
        horizons_by_h = {int(row["horizon_hours"]): row for row in horizons}

        symbol = alert.get("symbol") or token.get("symbol") or "unknown"
        lines = [f"Horizontes para {symbol} (alert #{alert['id']}):"]
        created_at = parse_iso_datetime(str(alert.get("created_at") or ""))

        for horizon in HORIZONS:
            row = horizons_by_h.get(horizon)
            label = self._horizon_label(horizon)
            if row and row.get("status") == "final":
                lines.append(
                    f"{label}: return {self._fmt_pct(row.get('return_pct'))} | "
                    f"MFE {self._fmt_pct(row.get('mfe_pct'))} | "
                    f"MAE {self._fmt_pct(row.get('mae_pct'))} | "
                    f"snapshots {row.get('snapshots_used')} | {row.get('outcome_label')}"
                )
            elif row and row.get("status") == "pending":
                lines.append(
                    f"{label}: pendiente (datos insuficientes, snapshots {row.get('snapshots_used')})"
                )
            elif created_at is not None:
                remaining_hours = max(
                    horizon - (utc_now() - created_at).total_seconds() / 3600,
                    0,
                )
                lines.append(
                    f"{label}: pendiente (faltan {remaining_hours:.1f}h para evaluar)"
                )
            else:
                lines.append(f"{label}: sin datos")

        lines.append(DISCLAIMER)
        return "\n".join(lines)

    def backtest_message(self, args: str) -> str:
        horizon, filters = self._parse_backtest_args(args)
        if filters:
            result = backtest_strategy(
                self.repository,
                filter_features=filters,
                horizon_hours=horizon,
            )
            return self._format_single_backtest(result)
        top = rank_top_strategies(
            self.repository,
            horizon_hours=horizon,
            min_samples=self.settings.backtest_min_samples,
        )
        if not top:
            return (
                f"Aun no hay outcomes finales suficientes para horizonte {horizon}h. "
                f"Necesitas {self.settings.backtest_min_samples}+ casos por regla."
            )
        lines = [f"Top reglas (horizonte {horizon}h, ultimos 30 dias):"]
        for index, row in enumerate(top, start=1):
            lines.append(self._format_backtest_row(index, row))
        lines.append(DISCLAIMER)
        return "\n".join(lines)

    def _parse_backtest_args(self, args: str) -> tuple[int, list[str]]:
        horizon = self.settings.backtest_default_horizon_hours
        filters: list[str] = []
        for piece in args.split():
            stripped = piece.strip().lower()
            if not stripped:
                continue
            if stripped.endswith("h") and stripped[:-1].isdigit():
                horizon = int(stripped[:-1])
                continue
            if stripped.isdigit():
                horizon = int(stripped)
                continue
            filters.extend(part for part in stripped.split(",") if part)
        if horizon not in HORIZONS:
            horizon = self.settings.backtest_default_horizon_hours
        return horizon, filters

    def _format_single_backtest(self, result: BacktestResult) -> str:
        if result.sample_count == 0:
            return (
                f"Sin casos para regla '{result.rule_label}' "
                f"(horizonte {result.horizon_hours}h)."
            )
        win_rate = self._fmt_pct(result.win_rate * 100)
        return (
            f"Backtest {result.rule_label} (horizonte {result.horizon_hours}h)\n"
            f"Casos: {result.sample_count}\n"
            f"Win rate: {win_rate}\n"
            f"Avg return: {self._fmt_pct(result.avg_return_pct)}\n"
            f"Median: {self._fmt_pct(result.median_return_pct)}\n"
            f"MFE prom: {self._fmt_pct(result.avg_mfe_pct)} | "
            f"MAE prom: {self._fmt_pct(result.avg_mae_pct)}\n"
            f"Drawdown peor: {self._fmt_pct(result.max_drawdown_pct)}\n"
            f"Sharpe aprox: {result.sharpe_approx}\n"
            f"{DISCLAIMER}"
        )

    def _format_backtest_row(self, index: int, row: BacktestResult) -> str:
        win_rate = self._fmt_pct(row.win_rate * 100)
        return (
            f"{index}. {row.rule_label} | n={row.sample_count} | "
            f"win {win_rate} | avg {self._fmt_pct(row.avg_return_pct)} | "
            f"MFE {self._fmt_pct(row.avg_mfe_pct)} | "
            f"MAE {self._fmt_pct(row.avg_mae_pct)} | sharpe {row.sharpe_approx}"
        )

    def _horizon_label(self, hours: int) -> str:
        labels = {1: "1h", 6: "6h", 24: "24h", 168: "7d"}
        return labels.get(hours, f"{hours}h")
