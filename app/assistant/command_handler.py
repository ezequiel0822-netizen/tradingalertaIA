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
from datetime import timedelta


DISCLAIMER = "No es recomendacion financiera. Revisar manualmente."


class BasicTelegramAssistant:
    def __init__(
        self,
        settings: Settings,
        repository: Repository,
        claude_processor=None,
        reasoner=None,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.claude_processor = claude_processor
        self._reasoner_inst = reasoner

    # -- v2.12.0 / Fase B — capa LLM asesora enchufada a Telegram (READ-ONLY) -- #
    def _reasoner(self):
        """TradingReasoner lazy (crea su propio OllamaProcessor). Inyectable en tests."""
        if self._reasoner_inst is None:
            from app.intelligence.reasoner import TradingReasoner

            self._reasoner_inst = TradingReasoner(self.settings)
        return self._reasoner_inst

    def _advisor_off_message(self) -> str:
        return (
            "El asesor LLM esta apagado. Activalo con ENABLE_LLM_ADVISOR=true "
            "(requiere Ollama corriendo + ENABLE_OLLAMA_INTEGRATION=true)."
        )

    def _analysis_reasoner(self):
        """v3.12.0 — reasoner para /claude_analyze: usa Claude como transporte
        si esta habilitado y disponible (mejor calidad, con sus cost caps);
        si no, cae al Ollama local del reasoner default. Solo texto."""
        if getattr(self.settings, "enable_claude_integration", False):
            try:
                from app.intelligence.claude_processor import ClaudeProcessor
                from app.intelligence.reasoner import TradingReasoner

                cp = ClaudeProcessor(self.settings, self.repository)
                if cp.is_available():
                    return TradingReasoner(self.settings, processor=cp)
            except Exception:
                pass  # soft-fail al transporte local
        return self._reasoner()

    def claude_analyze_message(self, query: str) -> str:
        """/claude_analyze SYMBOL — analisis tecnico NARRADO por LLM combinando
        VWAP + footprint de velas + Hurst + noticias (v3.12.0). A DEMANDA
        (jamas en el hot path del ciclo; en hardware chico tarda ~50s, como
        /market). Analista secundario: texto, sin senales ni override."""
        if not getattr(self.settings, "enable_llm_advisor", False):
            return self._advisor_off_message()
        symbol = query.strip().upper()
        if not symbol:
            return "Dime un simbolo. Ejemplo: /claude_analyze NVDA"

        snapshot = StockCollector(self.settings)._fetch_symbol(symbol)
        if not snapshot:
            return f"No pude obtener data publica para {symbol}."
        candles = snapshot.raw.get("candles") or []
        pattern = analyze_ohlcv(candles)

        news_label, news_score = "no_recent_news", 0
        headlines = ""
        try:
            news_items = NewsCollector(self.settings).collect_for_symbol(symbol)
            news_label, news_score, news_reasons = analyze_news(news_items)
            headlines = " | ".join(news_reasons[:3])
        except Exception:
            pass  # sin noticias el analisis tecnico sigue valiendo

        context = {
            "symbol": symbol,
            "label": pattern.label,
            "trend": pattern.trend,
            "rsi": pattern.rsi,
            "atr_pct": pattern.atr_pct,
            "vwap_dist_pct": pattern.vwap_dist_pct,
            "vwap_position": pattern.vwap_position,
            "vwap_week_dist_pct": pattern.vwap_week_dist_pct,
            "candle_strength": pattern.candle_strength,
            "candle_clv": pattern.candle_clv,
            "candle_patterns": pattern.candle_patterns or None,
            "hurst": pattern.hurst,
            "hurst_regime": pattern.hurst_regime,
            "news_label": news_label,
            "news_score": news_score,
            "headlines": headlines or None,
        }
        text = self._analysis_reasoner().analyze_symbol(context)
        if not text:
            return (
                "No pude generar el analisis (el LLM no respondio o esta "
                "apagado). El bot sigue funcionando igual."
            )
        return f"Analisis LLM de {symbol}:\n\n{text}\n\n{DISCLAIMER}"

    def market_message(self) -> str:
        """/market — evaluacion del mercado de hoy via LLM local (solo texto)."""
        if not getattr(self.settings, "enable_llm_advisor", False):
            return self._advisor_off_message()
        from app.intelligence.macro_context import full_macro_context

        ctx = full_macro_context(self.repository)
        macro = {
            "session": "+".join(ctx.get("active_sessions") or []) or "off-hours",
            "vix": ctx.get("vix"),
            "dxy": ctx.get("dxy"),
        }
        text = self._reasoner().assess_market(macro)
        if not text:
            return (
                "No pude generar la evaluacion (Ollama no respondio o esta apagado). "
                "El bot sigue funcionando igual."
            )
        return f"Evaluacion del mercado (LLM local):\n\n{text}\n\n{DISCLAIMER}"

    def loss_review_message(self) -> str:
        """/porque_perdi — post-mortem del ultimo trade perdedor via LLM local."""
        if not getattr(self.settings, "enable_llm_advisor", False):
            return self._advisor_off_message()
        trade = self._last_losing_trade()
        if trade is None:
            return "No encontre trades perdedores cerrados recientes para analizar."
        text = self._reasoner().analyze_loss(trade)
        if not text:
            return (
                "No pude generar el analisis (Ollama no respondio o esta apagado). "
                "El bot sigue funcionando igual."
            )
        symbol = trade.get("symbol") or "?"
        return f"Por que perdio {symbol} (LLM local):\n\n{text}\n\n{DISCLAIMER}"

    def _last_losing_trade(self):
        """Ultimo paper_trade cerrado no-artifact con R<0 (usa rsi/atr del entry)."""
        from app.learning.trade_outcomes import is_artifact, r_multiple

        for t in self.repository.fetch_paper_trades(limit=50):  # updated_at DESC
            if str(t.get("status") or "") == "open" or not t.get("closed_at"):
                continue
            if is_artifact(t):
                continue
            r = r_multiple(t)
            if r is not None and r < 0:
                return {
                    "symbol": t.get("symbol"),
                    "direction": t.get("direction"),
                    "strategy_name": t.get("strategy_name"),
                    "entry_price": t.get("entry_price"),
                    "stop_loss": t.get("stop_loss") or t.get("original_stop_loss"),
                    "r_multiple": round(r, 2),
                    "rsi_entry": t.get("rsi_entry"),
                    "atr_value": t.get("atr_value"),
                    "close_reason": t.get("status"),
                }
        return None

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

        if normalized in {"/gate_preview", "/preview_gate", "/learning_gate", "preview gate"}:
            return self.gate_preview_message()

        if normalized in {"/expectancy", "expectancy", "/expectativa", "expectativa", "expectancy r"}:
            return self.expectancy_message()

        if normalized in {"/performance", "performance", "/rendimiento", "rendimiento"}:
            return self.performance_message()

        if normalized in {"/readiness", "readiness", "/listo", "listo", "/real", "real money"}:
            return self.readiness_message()

        if normalized in {"/exit_analysis", "exit analysis", "/salidas", "salidas", "/trailing"}:
            return self.exit_analysis_message()

        if normalized in {"/exposicion", "exposicion", "/exposure", "exposure", "/usd"}:
            return self.exposure_message()

        if normalized in {"/agente", "agente", "/agent", "/ia", "agente ia"}:
            return self.ai_agent_message()

        if normalized in {"/edge", "edge", "/edges", "/borde", "bolsillos"}:
            return self.edge_message()

        if normalized in {"/ml_status", "ml_status", "/ml", "estado ml"}:
            return self.ml_status_message()

        if normalized in {"/market", "market", "mercado", "/mercado", "como esta el mercado"}:
            return self.market_message()

        if normalized in {"/porque_perdi", "porque_perdi", "por que perdi",
                          "/porque_perdio", "analiza la perdida"}:
            return self.loss_review_message()

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

        # v3.12.0 — analisis tecnico narrado por LLM (a demanda, solo texto).
        if (normalized.startswith("/claude_analyze") or normalized.startswith("claude_analyze")
                or normalized.startswith("/analisis_llm")):
            parts = raw.split(" ", 1)
            query = parts[1] if len(parts) > 1 else ""
            return self.claude_analyze_message(query)

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

        if normalized in {"/portfolio", "portfolio", "/portafolio", "portafolio"}:
            return self.portfolio_message()

        # v2.5.5: panel de salud del sistema (MT5, trades, riesgo, kill-switch, auto-orders).
        if normalized in {"/health", "health", "/salud", "salud"}:
            return self.health_message()

        # Phase 5.5 Bloque B v2.6.0: scalping commands
        if normalized in {"/scalping_on", "scalping_on", "/escalar_on", "scalping on"}:
            return self.scalping_on_message()
        if normalized in {"/scalping_off", "scalping_off", "/escalar_off", "scalping off"}:
            return self.scalping_off_message()
        if normalized in {"/scalping_status", "scalping_status", "/escalar_estado"}:
            return self.scalping_status_message()
        if normalized in {"/scalping_halt", "scalping_halt", "/parar_scalping"}:
            return self.scalping_halt_message()
        if normalized in {"/scalping_resume", "scalping_resume", "/reanudar_scalping"}:
            return self.scalping_resume_message()
        if normalized in {"/scalping_stats", "scalping_stats", "/escalar_stats"}:
            return self.scalping_stats_message()

        if normalized in {"/posiciones", "posiciones", "/positions", "positions"}:
            return self.positions_message()

        if normalized.startswith("/halt") or normalized.startswith("halt") or normalized.startswith("/parar"):
            parts = raw.split(" ", 1)
            arg = parts[1].strip() if len(parts) > 1 else ""
            return self.halt_message(arg)

        if normalized in {"/resume_trading", "resume_trading", "/reanudar_trading", "reanudar trading"}:
            return self.resume_trading_message()

        if normalized in {"/strategies", "strategies", "/estrategias", "estrategias"}:
            return self.strategies_message()

        # Phase 4.5 v2.4.0: bot mode toggle
        if normalized.startswith("/mode") or normalized == "mode" or normalized.startswith("mode "):
            parts = raw.split(" ", 1)
            arg = parts[1].strip().lower() if len(parts) > 1 else ""
            return self.mode_message(arg)

        # Phase 4 v2.3.0 commands
        if normalized in {"/mt5_status", "mt5_status", "/mt5"}:
            return self.mt5_status_message()

        # Phase 5 v2.5.0 demo MT5 order confirmation commands
        if normalized in {"/demo_candidates", "demo_candidates", "/demo_candidatos"}:
            return self.demo_candidates_message()

        if normalized.startswith("/demo_prepare") or normalized.startswith("demo_prepare"):
            parts = raw.split(" ", 1)
            arg = parts[1].strip() if len(parts) > 1 else ""
            return self.demo_prepare_message(arg)

        if normalized.startswith("/confirm_demo_trade") or normalized.startswith("confirm_demo_trade"):
            parts = raw.split(" ", 1)
            arg = parts[1].strip() if len(parts) > 1 else ""
            return self.confirm_demo_trade_message(arg)

        if normalized in {"/demo_positions", "demo_positions", "/demo_posiciones"}:
            return self.demo_positions_message()

        if normalized in {
            "/demo_close_all",
            "demo_close_all",
            "/cerrar_demo",
            "/cerrar_demo_todo",
        }:
            return self.demo_close_all_message()

        if normalized in {"/demo_halt", "demo_halt", "/parar_demo"}:
            return self.demo_halt_message()

        if normalized in {"/data_quality", "data_quality", "/dq", "/calidad"}:
            return self.data_quality_message()

        if normalized.startswith("/walk_forward") or normalized.startswith("walk_forward") or normalized.startswith("/wf"):
            parts = raw.split(" ", 1)
            args = parts[1].strip() if len(parts) > 1 else ""
            return self.walk_forward_message(args)

        if normalized.startswith("/export_csv") or normalized.startswith("export_csv"):
            parts = raw.split(" ", 1)
            arg = parts[1].strip() if len(parts) > 1 else ""
            return self.export_csv_message(arg)

        if "por que" in normalized or "porque" in normalized:
            return self.recent_alerts_message(limit=3)

        # Phase 3.5 v2.2.0: fallback usando Claude si disponible
        if self.claude_processor is not None and self.claude_processor.is_available():
            available = [
                "/help", "/status", "/cupos", "/top", "/alertas", "/descartes",
                "/aprendizaje", "/paper", "/portfolio", "/posiciones",
                "/strategies", "/horizontes SIMBOLO", "/backtest [Nh] [features]",
                "/analiza SIMBOLO", "/noticias SIMBOLO", "/filings SIMBOLO",
                "/patron SIMBOLO", "/pro SIMBOLO", "/halt [horas]", "/resume_trading",
            ]
            try:
                claude_response = self.claude_processor.interpret_free_text(raw, available)
            except Exception:
                claude_response = None
            if claude_response:
                stripped = claude_response.strip()
                # Si Claude devolvio un comando slash valido, ejecutarlo recursivamente
                if stripped.startswith("/"):
                    parts = stripped.split(" ", 1)
                    cmd = parts[0].lower()
                    known_prefixes = {
                        "/help", "/status", "/cupos", "/top", "/top_memecoins",
                        "/top_stocks", "/alertas", "/ultimas_alertas", "/descartes",
                        "/aprendizaje", "/paper", "/paper_trades", "/entrenar",
                        "/config", "/pausar", "/reanudar", "/analiza", "/noticias",
                        "/filings", "/patron", "/pro", "/horizontes", "/horizons",
                        "/backtest", "/portfolio", "/portafolio", "/posiciones",
                        "/positions", "/halt", "/parar", "/resume_trading",
                        "/strategies", "/estrategias", "/demo_candidates",
                        "/demo_prepare", "/confirm_demo_trade", "/demo_positions",
                        "/demo_close_all", "/cerrar_demo", "/demo_halt",
                        "/agente",
                    }
                    if cmd in known_prefixes:
                        # Re-ejecutar como comando real (recursion controlada por longitud)
                        if len(stripped) < 200:
                            return self.handle(stripped)
                # Texto libre: devolverlo directo
                return stripped + "\n\n🤖 Respuesta generada con IA."

        return (
            "No entendi ese mensaje. Prueba con /help, /status, /top, "
            "/top_stocks, /alertas o /analiza NVDA."
        )

    # ------------------------------------------------------------------ #
    # v3.13.2 — mercados activos (las memecoins están apagadas desde v3.7.0:
    # los textos ya no las muestran salvo que ENABLE_MEMECOIN_ENGINE=true)
    # ------------------------------------------------------------------ #
    MARKET_LABELS = {"stock": "Bolsa", "forex": "Forex", "gold": "Oro", "memecoin": "Memecoins"}

    def _memecoins_on(self) -> bool:
        return bool(getattr(self.settings, "enable_memecoin_engine", True))

    def _alert_markets(self) -> list[tuple[str, int, int]]:
        """(categoria, cupo por ventana, cupo por ciclo) de las alertas ACTIVAS."""
        s = self.settings
        out: list[tuple[str, int, int]] = []
        if getattr(s, "enable_stock_telegram", True):
            out.append(("stock", s.stock_max_alerts_per_24h, s.stock_max_alerts_per_run))
        if getattr(s, "enable_forex_alerts", False):
            out.append(("forex", s.max_forex_alerts_per_24h, s.max_forex_alerts_per_run))
        if getattr(s, "enable_gold_alerts", False):
            out.append(("gold", s.max_gold_alerts_per_24h, s.max_gold_alerts_per_run))
        if self._memecoins_on():
            out.append(("memecoin", s.memecoin_max_alerts_per_24h, s.memecoin_max_alerts_per_run))
        return out

    def _top_markets(self) -> list[str]:
        markets = ["stock"]
        if self._memecoins_on():
            markets.append("memecoin")
        return markets

    def _orders_line(self) -> str:
        if not getattr(self.settings, "enable_mt5_demo_trading", False):
            return "Ordenes: apagadas (solo paper trades)"
        mode = "auto" if getattr(self.settings, "enable_auto_confirm_demo", False) else "confirmacion manual"
        agent = "encendido" if getattr(self.settings, "enable_ai_agent", False) else "apagado"
        return f"Ordenes: solo MT5 DEMO ({mode}) | Agente IA: {agent}"

    def help_message(self) -> str:
        memecoin_line = (
            "/top_memecoins - mejores memecoins guardadas\n" if self._memecoins_on() else ""
        )
        return f"""Trading Alert AI {self.settings.app_version} - asistente basico

Comandos:
/status - estado del sistema y cupos
/cupos - alertas restantes por mercado
/top - mejores acciones guardadas (forex/oro: sin ranking)
{memecoin_line}/top_stocks - mejores acciones guardadas
/alertas - ultimas alertas guardadas
/descartes - mejores candidatos no enviados
/aprendizaje - lecciones que la IA aprendio del historial
/paper - setups simulados en papel
/entrenar - correr aprendizaje local ahora
/analiza SIMBOLO_O_ADDRESS - resumen de un activo
/noticias SIMBOLO - titulares/eventos recientes
/filings SIMBOLO - filings SEC recientes para acciones
/patron SIMBOLO - patron tecnico basico para acciones
/claude_analyze SIMBOLO - analisis tecnico narrado por LLM (VWAP+velas+Hurst+noticias)
/pro SIMBOLO - lectura profesional: grafico, noticias, filings, riesgos
/horizontes SIMBOLO - retornos por horizonte (1h/6h/24h/7d) y MFE/MAE
/backtest [Nh] [filtros] - top reglas o test de una combinacion (ej: /backtest 24h ia_pro,score:80-90)
/portfolio - posiciones abiertas, exposicion, riesgo total, P&L diario
/posiciones - detalle de paper trades abiertos
/halt [horas] - activa kill-switch (default usa setting cooldown)
/resume_trading - libera kill-switch del trader engine
/strategies - estrategias habilitadas y senales recientes
/demo_candidates - paper trades listos para preparar orden demo MT5
/demo_prepare ID - prepara una orden demo pendiente desde un paper trade
/confirm_demo_trade ID - confirma y envia order_send a cuenta demo MT5
/demo_positions - posiciones demo abiertas en MT5
/demo_close_all - cierra todas las posiciones demo abiertas en MT5
/demo_halt - bloquea nuevas ordenes demo
/agente - agente IA en sandbox demo: que decide, que aprendio y como le va
/pausar - pausa alertas automaticas
/reanudar - reactiva alertas automaticas
/config - ver configuracion sin secretos

{self._orders_line()}. Real-money trading sigue bloqueado."""

    def _cupo_lines(self) -> list[tuple[str, int, int, int, int]]:
        """(etiqueta, enviadas, cupo, restantes, cupo por ciclo) por mercado activo."""
        window = self.settings.alert_cap_window_hours
        out = []
        for category, cap, per_run in self._alert_markets():
            sent = self.repository.sent_alert_count(category, window)
            out.append((self.MARKET_LABELS[category], sent, cap, max(cap - sent, 0), per_run))
        return out

    def status_message(self) -> str:
        paused = self.repository.alerts_paused()
        lines = [
            f"Estado Trading Alert AI {self.settings.app_version}",
            "",
            f"Alertas automaticas: {'pausadas' if paused else 'activas'}",
            f"Ventana de cupos: {self.settings.alert_cap_window_hours}h",
        ]
        cupos = self._cupo_lines()
        if not cupos:
            lines.append("Sin mercados con alertas a Telegram activas.")
        for label, sent, cap, left, _ in cupos:
            lines.append(f"{label}: {sent}/{cap} enviadas, {left} restantes")
        lines += ["", f"{self._orders_line()}. Real-money: bloqueado."]
        return "\n".join(lines)

    def cupos_message(self) -> str:
        cupos = self._cupo_lines()
        lines = [f"Cupos restantes ({self.settings.alert_cap_window_hours}h)", ""]
        if not cupos:
            lines.append("Sin mercados con alertas a Telegram activas.")
            return "\n".join(lines)
        for label, sent, cap, left, _ in cupos:
            lines.append(f"{label}: {left} restantes ({sent}/{cap} usados)")
        lines += ["", "Por ciclo:"]
        lines += [f"{label}: max {per_run}" for label, _, _, _, per_run in cupos]
        return "\n".join(lines)

    def top_message(self, category: str, limit: int = 5) -> str:
        rows = self.repository.top_tokens(category, limit)
        title = self.MARKET_LABELS.get(category, category)
        if not rows:
            return f"Todavia no hay datos para {title}. Ejecuta el monitor un rato mas."

        lines = [f"Top {title} guardado:"]
        for index, row in enumerate(rows, start=1):
            lines.append(self._format_token_row(index, row))
        lines.append(DISCLAIMER)
        return "\n".join(lines)

    def combined_top_message(self) -> str:
        parts = [self.top_message(category, 3) for category in self._top_markets()]
        # v3.13.2: forex/oro no se rankean: el score/estimación que había eran fórmulas
        # de memecoins sin sentido para un par, y el bot no tiene edge para ordenarlos.
        parts.append(
            "Forex/oro: sin ranking (el bot no tiene un modelo con edge para ordenarlos). "
            "Lo que si hace: /posiciones (paper), /agente (agente IA en demo), "
            "/patron SIMBOLO (lectura tecnica)."
        )
        return "\n\n".join(parts)

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

        if category in {"forex", "gold"}:
            # v3.13.2: sin subida/caída "estimada" (antes salía la del estimador de
            # memecoins: caída 90 % para EURUSD). El bot no tiene edge en forex/oro.
            return f"""Analisis basico: {symbol} / {name}

Categoria: {category}
Precio: {self._fmt_money(price)}
Estimacion: el bot no estima subidas/caidas en forex/oro (no tiene un modelo con edge).
Para el detalle tecnico: /patron {symbol} o /claude_analyze {symbol}
{DISCLAIMER}"""

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

Lectura: {'candidato fuerte para revisar' if (self._as_float(row.get('latest_estimated_gain_pct')) or 0.0) >= self._threshold_for(category) else 'solo watchlist por ahora'}.
{DISCLAIMER}"""

    def config_message(self) -> str:
        return f"""Config sin secretos:

Version: {self.settings.app_version}
Assistant Telegram: {"activo" if self.settings.enable_telegram_assistant else "apagado"}
IA Pro: {"activa" if self.settings.enable_pro_intelligence else "apagada"}
SEC filings: {"activo" if self.settings.enable_sec_filings_intel else "apagado"}
Learning engine: {"activo" if self.settings.enable_learning_engine else "apagado"}
Paper trading simulado: {"activo" if self.settings.enable_paper_trading else "apagado"}
{self._orders_line()}
Real trading: {"bloqueado" if not self.settings.enable_real_trading else "NO IMPLEMENTADO"}
Stock min subida: {self.settings.min_stock_estimated_gain_pct}%
{self._config_alert_lines()}Stocks: {", ".join(symbol.upper() for symbol in self.settings.stock_symbols[:20])}
Forex/oro: {", ".join(symbol.upper() for symbol in getattr(self.settings, "forex_symbols", [])[:20])}
{self._config_memecoin_lines()}"""

    def _config_alert_lines(self) -> str:
        window = self.settings.alert_cap_window_hours
        lines = [f"Cupo {self.MARKET_LABELS[c].lower()}: {cap}/{window}h"
                 for c, cap, _ in self._alert_markets()]
        if not getattr(self.settings, "enable_forex_alerts", False):
            lines.append("Alertas forex: apagadas")
        if not getattr(self.settings, "enable_gold_alerts", False):
            lines.append("Alertas oro: apagadas")
        return "".join(line + "\n" for line in lines)

    def _config_memecoin_lines(self) -> str:
        if not self._memecoins_on():
            return "Memecoins: motor apagado (ENABLE_MEMECOIN_ENGINE=false)\n"
        return (
            f"Memecoin min subida: {self.settings.min_estimated_gain_pct}%\n"
            f"Chains: {', '.join(self.settings.chains_to_monitor)}\n"
        )

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
        """v2.6.0: separa lessons SWING (categorias normales) vs SCALPING (sufijo _scalping)."""
        # Pedimos más para tener margen tras filtrar.
        all_lessons = self.repository.fetch_strategy_lessons(limit=max(limit * 2, 20))
        runs = self.repository.latest_training_runs(limit=1)
        if not all_lessons:
            return "Todavia no hay suficientes outcomes para aprender. Deja correr el monitor mas tiempo o usa /entrenar."

        # Partir lessons por sufijo _scalping (decisión del Commit 4 v2.6.0)
        swing_lessons = [
            l for l in all_lessons
            if not str(l.get("category") or "").endswith("_scalping")
        ][:limit]
        scalping_lessons = [
            l for l in all_lessons
            if str(l.get("category") or "").endswith("_scalping")
        ][:limit]

        lines = [f"Aprendizaje local de Trading Alert AI {self.settings.app_version}"]
        if runs:
            lines.append(f"Ultimo entrenamiento: {runs[0].get('summary')}")

        def _render_block(title: str, items: list[dict]) -> list[str]:
            block = ["", f"== {title} =="]
            if not items:
                block.append("(sin lessons todavia)")
                return block
            for index, lesson in enumerate(items, start=1):
                win_rate = self._fmt_pct(
                    (self._as_float(lesson.get("win_rate")) or 0) * 100
                )
                avg_return = self._fmt_pct(lesson.get("avg_return_pct"))
                sample_count = lesson.get("sample_count") or 0
                feature = lesson.get("feature") or "unknown"
                category = lesson.get("category") or "unknown"
                block.append(
                    f"{index}. {feature} ({category}) | casos {sample_count} | win {win_rate} | retorno medio {avg_return}"
                )
                block.append(f"   {lesson.get('lesson')}")
            return block

        lines.extend(_render_block("SWING LESSONS", swing_lessons))
        lines.extend(_render_block("SCALPING LESSONS", scalping_lessons))
        lines.append("")
        lines.append(DISCLAIMER)
        return "\n".join(lines)

    def ai_agent_message(self) -> str:
        """v3.13.0: /agente — estado del agente IA en sandbox demo: decisiones, lo que
        aprendio, su medicion contra 'no operar' y 'ejecutar todo'. Read-only."""
        try:
            from app.ai_agent.agent import AiAgent

            text = AiAgent(self.settings, self.repository).status_text(
                self.settings.app_version
            )
        except Exception:
            return "No pude leer el estado del agente IA (error de repositorio)."
        return text + "\n\n" + DISCLAIMER

    def exposure_message(self) -> str:
        """v3.5.0: /exposicion — exposicion neta USD de las posiciones forex abiertas
        que ejecutaron a MT5. Muestra cuantas 'apuestas al dolar' hay concentradas
        (la leccion del 10-jun: 7 posiciones = 1 apuesta). Read-only."""
        from app.risk.exposure import net_usd_exposure, usd_direction

        try:
            open_trades = [
                t for t in self.repository.fetch_open_positions_full()
                if str(t.get("category") or "") == "forex"
                and t.get("id") is not None
                and self.repository.has_successful_demo_order(int(t["id"]))
            ]
        except Exception:
            return "No pude leer las posiciones abiertas (error de repositorio)."
        net = net_usd_exposure(open_trades)
        cap_on = bool(getattr(self.settings, "enable_usd_exposure_cap", False))
        max_net = int(getattr(self.settings, "max_net_usd_exposure", 3))
        lines = [
            f"Exposicion neta USD (forex ejecutado a MT5) — {self.settings.app_version}",
            f"Neto: {net:+d}  (+1 por posicion long-USD, -1 por short-USD)",
            f"Cap: |{max_net}| — gate {'ACTIVO' if cap_on else 'APAGADO (solo medicion)'}",
            "",
        ]
        if not open_trades:
            lines.append("(sin posiciones forex abiertas ejecutadas)")
        for t in open_trades:
            d = usd_direction(str(t.get("symbol") or ""), str(t.get("direction") or ""))
            tag = "+1 long-USD" if d > 0 else ("-1 short-USD" if d < 0 else " 0 sin USD")
            lines.append(
                f"  {str(t.get('symbol') or '?'):10} {str(t.get('direction') or '?'):5} [{tag}]"
            )
        lines.append("")
        lines.append(DISCLAIMER)
        return "\n".join(lines)

    def exit_analysis_message(self) -> str:
        """v3.4.0: /exit_analysis — mide HONESTO si un trailing stop mejoraria las salidas
        de forex, simulando sobre el camino REAL de R de cada trade cerrado
        (trade_r_samples) vs la salida real. SOLO medicion; no cambia ninguna salida.
        Requiere ENABLE_EXIT_SHADOW=true + unos dias de data registrada."""
        from app.learning.exit_shadow import analyze_closed_trades

        if not getattr(self.settings, "enable_exit_shadow", False):
            return (
                "El exit shadow esta apagado. Activalo con ENABLE_EXIT_SHADOW=true para que "
                "el bot registre el camino de R de los trades y poder medir el trailing."
            )
        distances = [0.5, 1.0, 1.5, 2.0]
        comps = analyze_closed_trades(self.repository, distances, category="forex")
        n = comps[0].trades if comps else 0
        lines = [
            f"Exit analysis (forex) — {self.settings.app_version}",
            "Trailing simulado sobre el camino REAL de R vs la salida real (honesto, no el techo).",
            "Metodo: trail se arma en +1R; excluye scalps, partial-close y caminos a mitad "
            "de vida. Fill asumido en el nivel del trail (en gaps reales puede ser peor).",
            "",
        ]
        if n == 0:
            lines.append(
                "(sin datos todavia — necesita ENABLE_EXIT_SHADOW on + unos dias de trades "
                "forex cerrados con camino registrado)"
            )
            lines.append("")
            lines.append(DISCLAIMER)
            return "\n".join(lines)
        lines.append(f"Trades forex con camino: {n}")
        for c in comps:
            lines.append(
                f"  trail D={c.distance}R: real {c.actual_avg_r:+.3f}R -> trailing "
                f"{c.policy_avg_r:+.3f}R (delta {c.delta_avg_r:+.3f}R/trade | mejora "
                f"{c.improved}, empeora {c.hurt})"
            )
        best = max(comps, key=lambda c: c.delta_avg_r)
        lines.append("")
        if best.delta_avg_r > 0.05:
            lines.append(
                f"Mejor: D={best.distance}R (delta {best.delta_avg_r:+.3f}R). Si se sostiene "
                "con mas muestra, vale activar un trailing para forex con esa distancia."
            )
        else:
            lines.append(
                "Ningun trailing mejora claro: las salidas actuales estan OK (o falta muestra)."
            )
        lines.append("Shadow read-only; no cambia ninguna salida. Decidir con muestra suficiente.")
        lines.append("")
        lines.append(DISCLAIMER)
        return "\n".join(lines)

    def readiness_message(self) -> str:
        """v3.3.0: /readiness — evaluacion HONESTA y read-only de cuanto falta para operar
        dinero real. NO habilita NADA (real-money sigue HARDCODED bloqueado); solo reporta
        los gates para que el user vea el progreso real y mantenga la disciplina. El que
        mas pesa no es codigo, es EDGE + DATA, que salen de dejar correr."""
        from app.learning.training_engine import _cost_map_from_settings
        from app.portfolio.performance import performance_since

        lines = [
            f"Readiness para dinero real — {self.settings.app_version}",
            "Read-only. NO habilita nada: real-money sigue bloqueado por diseno.",
            "",
        ]

        # Gate 1 — edge probado (alguna estrategia +R con muestra y pasando el gate)
        rows = self.repository.fetch_strategy_performance(limit=50)
        min_n = int(getattr(self.settings, "strategy_promotion_min_samples", 30))
        min_r = float(getattr(self.settings, "strategy_promotion_min_expectancy_r", 0.0))
        cands = [
            r for r in rows
            if int(r.get("trades") or 0) >= min_n and float(r.get("avg_r") or 0.0) > min_r
        ]
        if cands:
            best = max(cands, key=lambda r: float(r.get("avg_r") or 0.0))
            lines.append(
                f"[!] Edge: candidato {best.get('strategy_name')}/{best.get('category')} "
                f"(avg_r={float(best.get('avg_r') or 0.0):+.2f}, n={best.get('trades')}) — "
                "validar que NO sea de un solo regimen/direccion. Sin confirmar."
            )
        else:
            lines.append(f"[X] Edge: ninguna estrategia con avg_r>{min_r} y n>={min_n}. FALTA.")

        # Gate 2 — data con features tecnicos reales (Fase D)
        n_feat = self.repository.count_closed_trades_with_features()
        target = int(getattr(self.settings, "ml_gate_min_samples", 400))
        ok2 = "[OK]" if n_feat >= target else "[X]"
        lines.append(f"{ok2} Data con features: {n_feat}/{target} trades limpios (rsi/atr/macd).")

        # Gate 3 — performance limpia desde el baseline
        baseline = str(getattr(self.settings, "performance_baseline_date", "") or "")
        trades = (
            self.repository.fetch_closed_trades_since(baseline) if baseline
            else self.repository.fetch_closed_paper_trades(limit=5000)
        )
        executed = self.repository.fetch_executed_paper_trade_ids()
        stored = self.repository.get_state("account_balance")
        try:
            balance = float(stored) if stored else float(self.settings.account_starting_balance)
        except (TypeError, ValueError):
            balance = float(self.settings.account_starting_balance)
        perf = performance_since(
            trades, baseline, executed, balance, _cost_map_from_settings(self.settings)
        )
        ok3 = "[!]" if (perf.net_r > 0 and perf.account_pct > 0) else "[X]"
        lines.append(
            f"{ok3} Performance limpia (desde {baseline or 'inicio'}): {perf.trades} trades, "
            f"R neto {perf.net_r:+.2f}, impacto {perf.account_pct:+.2f}% (muestra chica no prueba edge)."
        )

        # Gate 4 — sizing para cuenta real micro
        lines.append(
            "[X] Sizing para cuenta micro: el position_sizer esta hecho para cuenta grande; "
            "falta reconfigurar (lote 0.01, risk en centavos, kill-switch a escala chica)."
        )

        # Gate 5 — camino de ejecucion real
        lines.append(
            "[X] Ejecucion real: ENABLE_REAL_TRADING=false HARDCODED; el path real nunca se "
            "ejecuto ni se audito. Requiere su propio audit + tests antes de tocar plata."
        )

        lines.append("")
        lines.append(
            "Veredicto: NO LISTO. Lo que mas falta NO es codigo: es EDGE + DATA (gates 1-2). "
            "El edge no se fuerza; sale de dejar correr y juntar muestra limpia."
        )
        lines.append("")
        lines.append(DISCLAIMER)
        return "\n".join(lines)

    def performance_message(self) -> str:
        """v3.3.0: /performance — rendimiento REALIZADO de trades ejecutados a MT5 (con
        demo_order 'sent') y no-artifact, desde el baseline limpio
        (performance_baseline_date, post-correccion de los bugs de mayo). NO altera el
        balance real; solo recorta el periodo medido para sacar la basura del feedback-
        loop / instant-kill / huerfanas. Honesto: el re-baseline no inventa edge."""
        from app.learning.training_engine import _cost_map_from_settings
        from app.portfolio.performance import performance_since

        baseline = str(getattr(self.settings, "performance_baseline_date", "") or "")
        if baseline:
            trades = self.repository.fetch_closed_trades_since(baseline)
        else:
            trades = self.repository.fetch_closed_paper_trades(limit=5000)
        executed = self.repository.fetch_executed_paper_trade_ids()
        stored = self.repository.get_state("account_balance")
        try:
            balance = float(stored) if stored else float(self.settings.account_starting_balance)
        except (TypeError, ValueError):
            balance = float(self.settings.account_starting_balance)
        summ = performance_since(
            trades, baseline, executed, balance, _cost_map_from_settings(self.settings)
        )
        since = baseline or "el inicio"
        lines = [
            f"Rendimiento desde {since} — {self.settings.app_version}",
            "Solo trades EJECUTADOS a MT5 demo y no-artifact (los que tocaron el balance).",
            "",
            f"Trades: {summ.trades} ({summ.wins} ganados, {summ.losses} perdidos, {summ.scratches} neutros)",
            f"Win rate: {summ.win_rate * 100:.1f}%",
            f"R neto (riesgo-normalizado, neto de costos modelados): {summ.net_r:+.2f}",
            f"Impacto en la cuenta (P&L real / balance): {summ.account_pct:+.2f}%",
            "",
            "Nota: el balance real del demo NO se altera; esto mide solo el periodo "
            "post-correccion del bug. 'R neto' descuenta un costo modelado y puede diferir "
            "del 'impacto' (P&L crudo, como lo registro MT5). Muestra chica: NO prueba edge.",
            "",
            DISCLAIMER,
        ]
        return "\n".join(lines)

    def expectancy_message(self) -> str:
        """v2.7.0: expectancy REALIZADA por estrategia, en R-multiples, calculada
        desde paper_trades cerrados (excluyendo artifacts del feedback-loop).

        A diferencia de /aprendizaje y /gate_preview (que miden el drift de la
        alerta con umbrales absolutos y dejan ~99% 'neutral'), esto mide el P&L
        realizado del trade normalizado por el riesgo asumido al entry. avg_r > 0
        significa edge positivo; es la métrica que se conecta con el crecimiento
        de la cuenta. Se refresca en cada ciclo de learning.
        """
        rows = self.repository.fetch_strategy_performance(limit=50)
        lines = [
            f"Expectancy realizada por estrategia (R) — {self.settings.app_version}",
            "R = retorno realizado (neto de costos) / riesgo al entry. Excluye artifacts.",
            "",
        ]
        if not rows:
            lines.append(
                "(sin datos todavia — se computa en cada ciclo de learning sobre "
                "paper_trades cerrados)"
            )
            lines.append("")
            lines.append(DISCLAIMER)
            return "\n".join(lines)

        from app.learning.trade_outcomes import should_execute_live

        gate_on = bool(getattr(self.settings, "enable_strategy_promotion_gate", False))
        min_n = int(getattr(self.settings, "strategy_promotion_min_samples", 30))
        min_r = float(getattr(self.settings, "strategy_promotion_min_expectancy_r", 0.0))
        for r in rows:
            strat = str(r.get("strategy_name") or "?")
            cat = str(r.get("category") or "?")
            n = int(r.get("trades") or 0)
            arts = int(r.get("artifacts_excluded") or 0)
            if n == 0:
                lines.append(
                    f"[--] {strat}/{cat}: 0 trades reales ({arts} artifacts descartados)"
                )
                continue
            avg_r = float(r.get("avg_r") or 0.0)
            wr = float(r.get("win_rate") or 0.0) * 100
            wins = int(r.get("wins") or 0)
            losses = int(r.get("losses") or 0)
            scratches = int(r.get("scratches") or 0)
            edge = "[+]" if avg_r > 0.05 else ("[-]" if avg_r < -0.05 else "[=]")
            art_str = f" | {arts} artifacts excl." if arts else ""
            gate_tag = ""
            if gate_on:
                ok_live, _ = should_execute_live(strat, cat, r, min_n, min_r)
                gate_tag = " | LIVE" if ok_live else " | SHADOW"
            lines.append(
                f"{edge} {strat}/{cat}: n={n} | avgR={avg_r:+.2f} | "
                f"win {wr:.0f}% ({wins}W/{losses}L/{scratches}S){art_str}{gate_tag}"
            )

        lines.append("")
        lines.append(
            "avgR>0 = edge positivo (n>=30-50 para confiar). "
            "LIVE=ejecuta a MT5; SHADOW=paper-only por edge negativo probado."
        )
        lines.append(DISCLAIMER)
        return "\n".join(lines)

    def ml_status_message(self) -> str:
        """v2.9.0: estado de la capa ML hibrida (XGBoost). Muestra version, modo
        (activo vs dormido/degradado), muestras, AUC, fecha de entrenamiento, top-5
        feature importance y la distribucion de decisiones del dia. Soft-fail."""
        if not getattr(self.settings, "enable_ml_predictor", False):
            return (
                "Capa ML: DESACTIVADA (ENABLE_ML_PREDICTOR=false). El sistema opera "
                "solo con reglas + promotion gate.\n\n" + DISCLAIMER
            )
        try:
            from app.learning.ml_predictor import MLPredictor

            pred = MLPredictor(
                min_train_samples=int(getattr(self.settings, "ml_min_train_samples", 100))
            )
            status = pred.get_status()
        except Exception as exc:  # soft-fail
            return f"/ml_status no disponible ({type(exc).__name__})."

        gate_min = int(getattr(self.settings, "ml_gate_min_samples", 400))
        trained = bool(status.get("trained"))
        samples = int(status.get("samples") or 0)
        modulating = trained and samples >= gate_min
        ml_available = bool(status.get("ml_available"))
        mode = (
            "ACTIVO (modula el gate)"
            if modulating
            else "DORMIDO/DEGRADADO (no toca decisiones)"
        )
        auc = status.get("auc")
        lines = [
            f"Capa ML (XGBoost) — {self.settings.app_version}",
            f"Estado: {mode}",
            f"Modelo: {status.get('version')} | libs: "
            f"{'ok' if ml_available else 'ausentes (degradado)'}",
            f"Entrenado: {'si' if trained else 'no'} | muestras: {samples} "
            f"(umbral para modular gate: {gate_min})",
            f"AUC test: {round(auc, 4) if auc is not None else 'n/d'}",
            f"Ultimo entrenamiento: {status.get('trained_at') or 'nunca'}",
        ]
        imp = pred.feature_importance(top=5)
        if imp:
            lines.append("Top 5 features:")
            for name, weight in imp:
                lines.append(f"  - {name}: {weight:.3f}")
        try:
            passed = int(self.repository.get_state("ml_stat_passed", "0") or 0)
            low = int(self.repository.get_state("ml_stat_low", "0") or 0)
            blocked = int(self.repository.get_state("ml_stat_blocked", "0") or 0)
        except Exception:
            passed = low = blocked = 0
        lines.append(
            f"Decisiones hoy: {passed} pasaron | {low} low-confidence (lot/2) | "
            f"{blocked} a paper-only"
        )
        if not modulating:
            lines.append(
                "Nota: el ML aun NO modula decisiones (dormido hasta tener muestra "
                "suficiente). El sistema se comporta igual que sin ML."
            )
        lines.append("")
        lines.append(DISCLAIMER)
        return "\n".join(lines)

    def edge_message(self) -> str:
        """v2.8.0: expectancy realizada en R SLICEADA por sesión y dirección, para
        cazar bolsillos de edge. Marca [OK] los slices con muestra suficiente
        (n>=EDGE_SLICE_MIN_SAMPLES) y resalta los que además son +R; los de poca
        muestra van como [..] (ruido, no concluir todavía). Es el research que
        antes se hacía a mano, ahora permanente y refrescado cada ciclo.
        """
        try:
            rows = self.repository.fetch_sliced_performance(limit=200)
        except Exception as exc:  # soft-fail: no crashear el assistant
            return f"/edge no disponible ({type(exc).__name__}). Reintenta luego."

        min_n = int(getattr(self.settings, "edge_slice_min_samples", 30))
        gate_on = bool(getattr(self.settings, "enable_sliced_promotion_gate", False))
        lines = [
            f"Edge por slice (R realizado, neto de costos) — {self.settings.app_version}",
            f"Confiable con n>={min_n}. Gate sliceado: {'ON' if gate_on else 'OFF'} "
            "(el slicing solo manda a SHADOW, nunca promueve).",
            "",
        ]
        if not rows:
            lines.append(
                "(sin datos todavia — se computa cada ciclo de learning sobre "
                "paper_trades cerrados)"
            )
            lines.append("")
            lines.append(DISCLAIMER)
            return "\n".join(lines)

        by_dim: dict[str, list] = {}
        for r in rows:
            by_dim.setdefault(str(r.get("dimension") or "?"), []).append(r)
        dim_titles = {"session": "POR SESION", "direction": "POR DIRECCION"}
        for dim in sorted(by_dim):
            lines.append(f"== {dim_titles.get(dim, dim.upper())} ==")
            for r in by_dim[dim]:
                strat = str(r.get("strategy_name") or "?")
                cat = str(r.get("category") or "?")
                bucket = str(r.get("bucket") or "?")
                n = int(r.get("trades") or 0)
                avg_r = float(r.get("avg_r") or 0.0)
                wr = float(r.get("win_rate") or 0.0) * 100
                reliable = n >= min_n
                tag = "[OK]" if reliable else "[..]"
                flag = "  <== EDGE+" if (reliable and avg_r > 0.05) else ""
                lines.append(
                    f"{tag} {strat}/{cat} {bucket}: n={n} avgR={avg_r:+.2f} "
                    f"win {wr:.0f}%{flag}"
                )
            lines.append("")
        lines.append(
            "[OK]=muestra suficiente · [..]=ruido (n bajo). "
            "avgR>0 con [OK] = bolsillo con edge real."
        )
        lines.append(DISCLAIMER)
        return "\n".join(lines)

    def gate_preview_message(self) -> str:
        """v2.6.9: Preview de qué features serían filtradas si se activa
        ENABLE_LEARNING_GATE=true con los thresholds actuales.

        El gate filtra signals cuyo subset (category:/alert:/score:) tenga
        win_rate < LEARNING_GATE_MIN_WIN_RATE con LEARNING_GATE_MIN_SAMPLES+
        observaciones en LEARNING_GATE_SINCE_DAYS. Este comando permite
        prever el impacto antes de flipear el toggle.
        """
        horizon = self.settings.learning_gate_horizon_hours
        since = self.settings.learning_gate_since_days
        min_samples = self.settings.learning_gate_min_samples
        min_wr = self.settings.learning_gate_min_win_rate

        lines = [
            f"Learning Gate Preview ({self.settings.app_version})",
            f"Settings: horizon={horizon}h | since={since}d",
            f"min_samples={min_samples} | min_wr={min_wr*100:.0f}%",
            f"ENABLE_LEARNING_GATE actual: {self.settings.enable_learning_gate}",
            f"FORCE_FOR_MEMECOIN: {self.settings.force_learning_gate_for_memecoin}",
            "",
            "Top features por sharpe (samples >= min_samples):",
            "",
        ]

        try:
            ranked = rank_top_strategies(
                repository=self.repository,
                horizon_hours=horizon,
                since_days=since,
                min_samples=min_samples,
                top_n=15,
            )
        except Exception as exc:
            lines.append(f"Error: {exc.__class__.__name__}")
            lines.append(DISCLAIMER)
            return "\n".join(lines)

        if not ranked:
            lines.append("(no hay features con suficientes samples — gate no filtraria nada)")
            lines.append("")
            lines.append(DISCLAIMER)
            return "\n".join(lines)

        blocked = 0
        passed = 0
        for r in ranked[:15]:
            if r.sample_count < min_samples:
                mark = "?"
                decision = "PASS(insuf)"
            elif r.win_rate < min_wr:
                mark = "X"
                decision = "BLOCK"
                blocked += 1
            else:
                mark = "Y"
                decision = "PASS"
                passed += 1
            label = r.rule_label[:30]
            lines.append(
                f"{mark} {label:30s} n={r.sample_count:3d} "
                f"wr={r.win_rate*100:5.1f}% ret={r.avg_return_pct:+5.1f}% [{decision}]"
            )

        lines.append("")
        lines.append(f"Resumen si activas el gate: {blocked} bloqueados | {passed} pasan")
        if blocked > passed and blocked > 0:
            lines.append("ADVERTENCIA: muchos features serian bloqueados — bot operaria poco.")
            lines.append("Considera bajar LEARNING_GATE_MIN_WIN_RATE o esperar mas data.")
        lines.append("")
        lines.append("Para activar: ENABLE_LEARNING_GATE=true en .env")
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
        # v3.12.0 — VWAP de sesion (si hay volumen real; forex Yahoo no tiene).
        if pattern.vwap is not None and pattern.vwap_dist_pct is not None:
            lines.append(
                f"VWAP sesion: {pattern.vwap:g} | precio {pattern.vwap_dist_pct:+.2f}%"
                f" ({pattern.vwap_position})"
            )
        if pattern.vwap_week_dist_pct is not None:
            lines.append(f"VWAP semanal: precio {pattern.vwap_week_dist_pct:+.2f}%")
        # v3.12.0 — footprint lite + Hurst en /patron.
        lines.append(f"Vela: {pattern.candle_strength}"
                     + (f" | clv {pattern.candle_clv:.2f}" if pattern.candle_clv is not None else ""))
        if pattern.candle_patterns:
            lines.append(f"Secuencias: {pattern.candle_patterns}")
        if pattern.hurst is not None:
            lines.append(f"Hurst: {pattern.hurst:.2f} ({pattern.hurst_regime})")
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
            # v3.12.0 — VWAP de sesion en /pro (si hay volumen real).
            if pattern.vwap is not None and pattern.vwap_dist_pct is not None:
                lines.append(
                    f"VWAP {pattern.vwap:g} | precio {pattern.vwap_dist_pct:+.2f}%"
                    f" ({pattern.vwap_position})"
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
        # v3.12.0 — el checklist de IA Pro existia pero no se mostraba en
        # ningun lado (output muerto desde su creacion); /pro es su lugar.
        if pro.checklist:
            lines.append("Checklist:")
            lines.extend(f"- {item}" for item in pro.checklist[:4])
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
        if category in {"forex", "gold"}:
            # v3.13.2: antes comparaba contra la subida mínima de MEMECOINS (500 %).
            if "Movimiento notable" in str(row.get("estimate_summary") or ""):
                return "cupo lleno, duplicado o fuera del top"
            return "sin movimiento notable"
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

    def _parse_int_arg(self, value: str) -> int | None:
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            return None

    def _demo_prepare_failure_hint(self, reason: str) -> str:
        lowered = reason.lower()
        if "requires tp above" in lowered or "requires tp below" in lowered:
            return (
                "setup vencido: el precio actual ya paso la zona del TP. "
                "Pide /demo_candidates para buscar uno fresco."
            )
        if "requires sl below" in lowered or "requires sl above" in lowered:
            return (
                "setup vencido: el precio actual ya invalido el SL. "
                "Pide /demo_candidates para buscar uno fresco."
            )
        if "max open trades" in lowered:
            return "limite de posiciones demo abiertas alcanzado."
        if "allowed list" in lowered:
            return (
                f"{reason}. Agrega el simbolo a DEMO_ALLOWED_SYMBOLS en .env "
                "si quieres practicarlo."
            )
        return reason

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

    # ---------- Fase 2.5 v2.0.0 trader engine commands ----------

    def health_message(self) -> str:
        """Panel de salud — v2.5.5.

        Snapshot rápido del bot: trades abiertos, riesgo consumido, caps
        aplicables, kill-switch, auto-confirm, y últimas auto-orders demo.
        Útil cuando el bot corre autónomo y querés ver qué pasa desde Telegram.
        """
        from app.portfolio.portfolio_manager import PortfolioManager
        pm = PortfolioManager(self.settings, self.repository)
        counts = pm.count_open_by_category()
        total_open = sum(counts.values()) if counts else 0
        balance = pm.account_balance()
        risk_used = pm.total_risk_pct(balance)
        daily_pnl = pm.realized_pnl_today()

        # Estado de switches
        kill_until = self.repository.get_state("kill_switch_active_until") or ""
        kill_reason = self.repository.get_state("kill_switch_reason") or ""
        kill_str = (
            f"ACTIVO hasta {kill_until} ({kill_reason})"
            if kill_until
            else "inactivo"
        )
        demo_halt = self.repository.get_state("demo_trading_halted", "false") == "true"

        # Auto-orders demo
        recent_orders = self.repository.fetch_demo_orders(limit=20)
        sent_orders = [o for o in recent_orders if o.get("status") == "sent"]
        failed_orders = [o for o in recent_orders if o.get("status") == "failed"]
        last_order = recent_orders[0] if recent_orders else None

        lines: list[str] = [
            f"Trading Alert AI {self.settings.app_version}",
            f"Bot mode: {self.settings.bot_mode}",
            "",
            "MT5:",
            f"  reader habilitado: {'si' if self.settings.enable_mt5_reader else 'no'}",
            f"  broker profile: {self.settings.mt5_broker_profile}",
            f"  demo trading: {'ON' if self.settings.enable_mt5_demo_trading else 'OFF'}",
            f"  auto-confirm: {'ON' if self.settings.enable_auto_confirm_demo else 'OFF'}",
            f"  real trading: {'ON' if self.settings.enable_real_trading else 'BLOQUEADO'}",
            "",
            f"Paper trades open: {total_open}/{self.settings.max_open_trades_total}",
        ]
        per_cat_limits = {
            "stock": self.settings.max_open_trades_stock,
            "forex": self.settings.max_open_trades_forex,
            "gold": self.settings.max_open_trades_gold,
        }
        for cat in sorted(counts.keys()) if counts else []:
            n = counts[cat]
            cat_lim = per_cat_limits.get(cat)
            lim_str = f"/{cat_lim}" if cat_lim is not None else ""
            lines.append(f"  {cat}: {n}{lim_str}")
        lines.extend(
            [
                "",
                f"Riesgo agregado: {risk_used:.2f}%",
                f"  cap default: {self.settings.max_total_risk_pct:.1f}% "
                f"({'stocks/memecoin' if self._memecoins_on() else 'stocks'})",
                f"  cap demo: {self.settings.demo_max_total_risk_pct:.1f}% (forex/gold con demo trading)",
                f"Balance demo: {balance:,.2f} USD",
                f"P&L hoy: {daily_pnl:+.2f}%",
                "",
                f"Kill switch: {kill_str}",
                f"Demo trading halt: {'ACTIVO' if demo_halt else 'inactivo'}",
                "",
                f"Auto-orders demo (ultimas 20): {len(sent_orders)} sent, {len(failed_orders)} failed",
            ]
        )
        if last_order:
            sym = last_order.get("symbol") or "?"
            status = last_order.get("status") or "?"
            ticket = last_order.get("order_ticket") or "?"
            retcode = last_order.get("retcode") or "?"
            sent_at = last_order.get("sent_at") or "?"
            lines.append(
                f"Ultima auto-order: {status} {sym} ticket={ticket} retcode={retcode} ({sent_at})"
            )
        else:
            lines.append("Ultima auto-order: ninguna registrada todavia")

        # Phase 5.5 Bloque B v2.6.0: seccion scalping engine
        from app.utils.scalping_state import is_scalping_halted, resolve_scalping_state

        scalping_active = resolve_scalping_state(self.settings, self.repository)
        scalping_halted_state = is_scalping_halted(self.repository)
        scalping_open = self._count_open_scalping()
        scalping_today = self._count_scalping_orders_today()
        lines.extend(
            [
                "",
                "Scalping engine:",
                f"  estado: {'ACTIVO' if scalping_active else 'inactivo'}",
                f"  halt manual: {'SI' if scalping_halted_state else 'no'}",
                f"  trades hoy: {scalping_today}/{self.settings.scalping_max_trades_per_day}",
                f"  abiertos: {scalping_open}/{self.settings.scalping_max_open_trades}",
                f"  simbolos: {','.join(self.settings.scalping_allowed_symbols)}",
            ]
        )
        lines.append("")
        lines.append(DISCLAIMER)
        return "\n".join(lines)

    def portfolio_message(self) -> str:
        from app.portfolio.portfolio_manager import PortfolioManager
        pm = PortfolioManager(self.settings, self.repository)
        positions = pm.get_open_positions()
        counts = pm.count_open_by_category()
        exposure = pm.total_exposure_by_category()
        balance = pm.account_balance()
        risk_pct = pm.total_risk_pct(balance)
        daily_pnl = pm.realized_pnl_today()
        kill_state = self.repository.get_state("kill_switch_active_until") or ""
        kill_str = f" (kill switch hasta {kill_state})" if kill_state else ""
        lines = [
            f"Portfolio Trading Alert AI {self.settings.app_version}",
            f"Balance: {balance:,.0f} USD{kill_str}",
            f"Posiciones abiertas: {len(positions)} (limite {self.settings.max_open_trades_total})",
        ]
        if counts:
            for cat, n in sorted(counts.items()):
                exp = exposure.get(cat, 0.0)
                lines.append(f"  {cat}: {n} abierta(s), exposicion ~{exp:,.0f} USD")
        lines.append(f"Riesgo agregado: {risk_pct:.2f}% (max {self.settings.max_total_risk_pct:.1f}%)")
        lines.append(f"P&L hoy: {daily_pnl:+.2f}%")
        lines.append(DISCLAIMER)
        return "\n".join(lines)

    def positions_message(self) -> str:
        from app.portfolio.portfolio_manager import PortfolioManager
        pm = PortfolioManager(self.settings, self.repository)
        positions = pm.get_open_positions()
        if not positions:
            return "No hay paper trades abiertos."
        lines = [f"Posiciones abiertas ({len(positions)}):"]
        for pos in positions[:10]:
            sym = pos.get("symbol") or "?"
            direction = pos.get("direction") or "long"
            entry = pos.get("entry_price") or 0
            latest = pos.get("latest_price") or entry
            mfe = pos.get("mfe_pct") or 0
            mae = pos.get("mae_pct") or 0
            ret = pos.get("unrealized_return_pct") or 0
            strat = pos.get("strategy_name") or "?"
            lines.append(
                f"{sym} ({direction}, {strat}): entry {entry:g} → {latest:g} "
                f"| ret {ret:+.2f}% | MFE {mfe:+.2f}% | MAE {mae:+.2f}%"
            )
        lines.append(DISCLAIMER)
        return "\n".join(lines)

    def halt_message(self, arg: str) -> str:
        from app.portfolio.portfolio_manager import PortfolioManager
        from app.risk.risk_manager import RiskManager
        try:
            hours = int(arg) if arg else self.settings.kill_switch_cooldown_hours
        except ValueError:
            hours = self.settings.kill_switch_cooldown_hours
        # Clamp a rango seguro [1, 168] (1 hora a 1 semana)
        if hours < 1:
            hours = 1
        if hours > 168:
            hours = 168
        pm = PortfolioManager(self.settings, self.repository)
        rm = RiskManager(self.settings, self.repository, pm)
        rm.trigger_kill_switch(reason="manual halt via Telegram", hours=hours)
        return (
            f"Kill switch activado por {hours}h. No abrire nuevos trades "
            f"hasta /resume_trading o que pase el plazo."
        )

    def resume_trading_message(self) -> str:
        from app.portfolio.portfolio_manager import PortfolioManager
        from app.risk.risk_manager import RiskManager
        pm = PortfolioManager(self.settings, self.repository)
        rm = RiskManager(self.settings, self.repository, pm)
        rm.release_kill_switch()
        self.repository.set_state("demo_trading_halted", "false")
        return "Kill switch liberado. Trader engine y demo trading pueden volver a abrir trades."

    def strategies_message(self) -> str:
        enabled = []
        if self.settings.enable_strategy_breakout:
            enabled.append("breakout")
        if self.settings.enable_strategy_mean_reversion:
            enabled.append("mean_reversion")
        if self.settings.enable_strategy_momentum:
            enabled.append("momentum")
        if self.settings.enable_strategy_news_catalyst:
            enabled.append("news_catalyst")
        # Contar senales por strategy en las ultimas 24h via paper_trades
        trades = self.repository.fetch_paper_trades(limit=200)
        from collections import Counter
        from datetime import datetime, timedelta, timezone
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        recent_counts: Counter[str] = Counter()
        for t in trades:
            opened_at_str = t.get("opened_at") or ""
            try:
                opened = datetime.fromisoformat(str(opened_at_str).replace("Z", "+00:00"))
            except ValueError:
                continue
            if opened.tzinfo is None:
                opened = opened.replace(tzinfo=timezone.utc)
            if opened >= cutoff:
                name = str(t.get("strategy_name") or "unknown")
                recent_counts[name] += 1
        lines = [
            f"Strategies habilitadas: {len(enabled)}",
            *[f"  - {name} ({recent_counts.get(name, 0)} senal(es) en 24h)" for name in enabled],
            f"Min confidence: {self.settings.strategy_min_confidence}",
            DISCLAIMER,
        ]
        return "\n".join(lines)

    # ---------- Phase 4.5 v2.4.0: bot mode ----------

    def mode_message(self, arg: str) -> str:
        """v2.6.0: extiende /mode con macros swing_only / scalping_only / hybrid.

        Modos basicos (afecta solo bot_mode_active):
        - trader: swing engine on.
        - alerts_only: swing engine off, solo alertas Telegram.

        Macros (afecta bot_mode_active Y scalping_active):
        - swing_only: trader + scalping OFF.
        - scalping_only: alerts_only + scalping ON.
        - hybrid: trader + scalping ON (extiende semantic v2.4.0 que era alias de trader).
        """
        from app.utils.bot_mode import VALID_MODES, normalize_mode, resolve_bot_mode
        from app.utils.scalping_state import resolve_scalping_state

        if not arg:
            current_mode = resolve_bot_mode(self.settings, self.repository)
            scalping_on = resolve_scalping_state(self.settings, self.repository)
            return (
                f"Modo bot: {current_mode}\n"
                f"Scalping: {'ON' if scalping_on else 'OFF'}\n"
                f"Validos basicos: {', '.join(sorted(VALID_MODES))}\n"
                "Macros: /mode swing_only | /mode scalping_only | /mode hybrid | /mode alerts_only\n"
                + DISCLAIMER
            )

        normalized_arg = arg.strip().lower()
        # Macros que setean ambos flags
        if normalized_arg == "swing_only":
            self.repository.set_state("bot_mode_active", "trader")
            self.repository.set_state("scalping_active", "false")
            return (
                "Modo: SWING_ONLY (trader + scalping OFF).\n"
                "Efecto en proximo ciclo.\n" + DISCLAIMER
            )
        if normalized_arg == "scalping_only":
            self.repository.set_state("bot_mode_active", "alerts_only")
            self.repository.set_state("scalping_active", "true")
            return (
                "Modo: SCALPING_ONLY (alerts_only swing + scalping ON).\n"
                "Efecto en proximo ciclo. Reinicia el bot para que el thread scalping arranque.\n"
                + DISCLAIMER
            )
        if normalized_arg == "hybrid":
            self.repository.set_state("bot_mode_active", "trader")
            self.repository.set_state("scalping_active", "true")
            return (
                "Modo: HYBRID (swing + scalping ON).\n"
                "Efecto en proximo ciclo. Reinicia el bot para que el thread scalping arranque.\n"
                + DISCLAIMER
            )

        # Modos basicos (solo bot_mode_active)
        target = normalize_mode(arg)
        if target is None:
            return (
                f"Modo invalido '{arg}'. Validos: {', '.join(sorted(VALID_MODES))} | "
                "macros: swing_only, scalping_only, hybrid."
            )
        self.repository.set_state("bot_mode_active", target)
        return (
            f"Modo bot cambiado a: {target} (scalping_active sin cambio).\n"
            f"Efecto en proximo ciclo. Revertir con /mode trader.\n"
            + DISCLAIMER
        )

    # ---------- Phase 5.5 Bloque B v2.6.0: scalping commands ----------

    def scalping_on_message(self) -> str:
        self.repository.set_state("scalping_active", "true")
        return (
            "Scalping engine: ON (persistido).\n"
            "Si el bot ya esta corriendo, REINICIA para que el thread scalping arranque.\n"
            + DISCLAIMER
        )

    def scalping_off_message(self) -> str:
        self.repository.set_state("scalping_active", "false")
        return (
            "Scalping engine: OFF (persistido).\n"
            "Si el bot ya esta corriendo, REINICIA para que el thread scalping se detenga.\n"
            + DISCLAIMER
        )

    def scalping_status_message(self) -> str:
        from app.utils.scalping_state import is_scalping_halted, resolve_scalping_state

        active = resolve_scalping_state(self.settings, self.repository)
        halted = is_scalping_halted(self.repository)
        open_count = self._count_open_scalping()
        today_count = self._count_scalping_orders_today()
        sent_count, failed_count = self._scalping_orders_breakdown()

        lines = [
            f"Scalping engine: {'ACTIVO' if active else 'inactivo'}",
            f"Halt manual: {'SI' if halted else 'no'}",
            f"Trades abiertos: {open_count}/{self.settings.scalping_max_open_trades}",
            f"Trades hoy: {today_count}/{self.settings.scalping_max_trades_per_day}",
            f"Auto-orders (last 20): {sent_count} sent / {failed_count} failed",
            f"Simbolos: {','.join(self.settings.scalping_allowed_symbols)}",
            f"Force-exit: {self.settings.scalping_force_exit_minutes} min",
            f"Risk per trade: {self.settings.scalping_risk_per_trade_pct:.2f}%",
            DISCLAIMER,
        ]
        return "\n".join(lines)

    def scalping_halt_message(self) -> str:
        self.repository.set_state("scalping_halted", "true")
        return (
            "Scalping HALTED. El engine sigue corriendo pero no abre nuevos trades.\n"
            "Liberar con /scalping_resume.\n" + DISCLAIMER
        )

    def scalping_resume_message(self) -> str:
        self.repository.set_state("scalping_halted", "false")
        return (
            "Scalping resumed. El engine puede volver a abrir trades.\n" + DISCLAIMER
        )

    def scalping_stats_message(self) -> str:
        """Win rate + profit factor de scalping vs swing en outcomes recientes."""
        outcomes = self.repository.fetch_signal_outcomes(limit=500)
        scalping_outcomes = [o for o in outcomes if int(o.get("is_scalping") or 0) == 1]
        if not scalping_outcomes:
            return (
                "Sin outcomes scalping todavia. Dejá correr el bot y mandá /scalping_stats luego.\n"
                + DISCLAIMER
            )
        wins = sum(1 for o in scalping_outcomes if str(o.get("outcome_label") or "").startswith("win"))
        losses = sum(1 for o in scalping_outcomes if str(o.get("outcome_label") or "").startswith("loss"))
        total = len(scalping_outcomes)
        win_rate = (wins / total * 100) if total > 0 else 0.0
        returns = [float(o.get("return_pct") or 0) for o in scalping_outcomes]
        avg_return = sum(returns) / len(returns) if returns else 0.0
        return (
            f"Scalping stats (ultimos {total} outcomes)\n"
            f"Win rate: {win_rate:.1f}% ({wins}W / {losses}L)\n"
            f"Avg return per trade: {avg_return:+.3f}%\n"
            + DISCLAIMER
        )

    def _count_open_scalping(self) -> int:
        try:
            all_open = self.repository.fetch_open_positions_full() or []
        except Exception:
            return 0
        return sum(1 for t in all_open if int(t.get("is_scalping") or 0) == 1)

    def _count_scalping_orders_today(self) -> int:
        try:
            from app.utils.time_utils import utc_now
            today = utc_now().date().isoformat()
            orders = self.repository.fetch_demo_orders(limit=200)
            return sum(
                1 for o in orders
                if int(o.get("is_scalping") or 0) == 1
                and str(o.get("sent_at") or "").startswith(today)
            )
        except Exception:
            return 0

    def _scalping_orders_breakdown(self) -> tuple[int, int]:
        try:
            orders = self.repository.fetch_demo_orders(limit=20)
            scalping = [o for o in orders if int(o.get("is_scalping") or 0) == 1]
            sent = sum(1 for o in scalping if o.get("status") == "sent")
            failed = sum(1 for o in scalping if o.get("status") == "failed")
            return sent, failed
        except Exception:
            return 0, 0

    # ---------- Phase 4 v2.3.0 commands ----------

    def mt5_status_message(self) -> str:
        from app.brokers.mt5_reader import MT5Reader
        reader = MT5Reader(self.settings)
        if not reader.connect():
            return (
                "MT5 reader: NO conectado.\n"
                "Pasos: instalar MetaTrader5 + abrir desktop + login demo + "
                "configurar MT5_LOGIN/PASSWORD/SERVER en .env + "
                "ENABLE_MT5_READER=true."
            )
        try:
            account = reader.get_account_info() or {}
            lines = [
                "MT5 reader: conectado",
                f"Broker: {account.get('server') or 'unknown'}",
                f"Account: {account.get('login') or '?'} ({account.get('currency') or 'USD'})",
                f"Balance: {account.get('balance', 0):.2f}",
                f"Equity: {account.get('equity', 0):.2f}",
                f"Leverage: 1:{account.get('leverage', 1)}",
            ]
            # Symbol info de EURUSD si esta disponible
            from app.brokers.mt5_symbol_map import yahoo_to_mt5
            primary = yahoo_to_mt5("EURUSD=X", self.settings.mt5_broker_profile) or "EURUSD"
            info = reader.symbol_info(primary)
            if info:
                pip = reader.compute_pip_value(primary, lot_size=1.0)
                lines.append(
                    f"\nSymbol {primary}: spread {info.get('spread')}, "
                    f"digits {info.get('digits')}, pip_value {pip}/lot"
                )
            return "\n".join(lines) + "\n" + DISCLAIMER
        finally:
            reader.disconnect()

    # ---------- Phase 5 v2.5.0 demo MT5 orders ----------

    def demo_candidates_message(self) -> str:
        if not self.settings.enable_mt5_demo_trading:
            return (
                "Demo trading MT5 esta apagado. En .env usa "
                "ENABLE_MT5_DEMO_TRADING=true solo para cuenta demo."
            )
        if self.repository.get_state("demo_trading_halted", "false") == "true":
            return "Demo trading esta detenido por /demo_halt. Usa /resume_trading para liberar."

        raw_candidates = [
            trade for trade in self.repository.fetch_paper_trades(status="open", limit=20)
            if str(trade.get("category") or "").lower() in {"forex", "gold"}
            and trade.get("stop_loss") is not None
            and trade.get("take_profit_1") is not None
        ]
        if not raw_candidates:
            return (
                "No hay paper trades forex/oro listos para demo. "
                "Primero deja correr el bot en /mode trader."
            )

        from app.brokers.mt5_demo_trader import MT5DemoTrader
        trader = MT5DemoTrader(self.settings)
        valid_candidates = []
        skipped = []
        try:
            open_positions = len(trader.positions())
            for trade in raw_candidates:
                result = trader.prepare_from_paper_trade(trade, open_positions)
                if result.ok and result.draft is not None:
                    valid_candidates.append((trade, result.draft))
                else:
                    skipped.append((trade, result.reason))
        finally:
            trader.disconnect()

        if not valid_candidates:
            lines = [
                "No hay candidatos demo vigentes ahora.",
                "Los paper trades abiertos existen, pero el precio actual ya no permite una orden segura.",
            ]
            if skipped:
                lines.append("Descartes principales:")
                for trade, reason in skipped[:5]:
                    lines.append(
                        f"- ID {trade.get('id')}: "
                        f"{self._demo_prepare_failure_hint(str(reason))}"
                    )
            lines.append("Deja correr el bot unos minutos para generar setups frescos.")
            lines.append(DISCLAIMER)
            return "\n".join(lines)

        lines = [
            "Candidatos demo MT5 (confirmacion manual obligatoria):",
        ]
        for trade, draft in valid_candidates[:8]:
            lines.append(
                f"ID {trade.get('id')}: {trade.get('symbol') or '?'} "
                f"{draft.direction} "
                f"({draft.strategy_name or '?'}) | "
                f"entry actual {self._fmt_money(draft.entry_price)} | "
                f"SL {self._fmt_money(draft.stop_loss)} | "
                f"TP {self._fmt_money(draft.take_profit)} | "
                f"riesgo {self._fmt_pct(draft.risk_pct)}"
            )
        if skipped:
            lines.append(
                f"Oculté {len(skipped)} candidato(s) vencidos o no preparables."
            )
        lines.append("Preparar: /demo_prepare ID")
        lines.append(DISCLAIMER)
        return "\n".join(lines)

    def demo_prepare_message(self, arg: str) -> str:
        if not self.settings.enable_mt5_demo_trading:
            return (
                "Demo trading MT5 esta apagado. En .env usa "
                "ENABLE_MT5_DEMO_TRADING=true solo para cuenta demo."
            )
        if self.repository.get_state("demo_trading_halted", "false") == "true":
            return "Demo trading esta detenido por /demo_halt. Usa /resume_trading para liberar."
        trade_id = self._parse_int_arg(arg)
        if trade_id is None:
            return "Uso: /demo_prepare ID. Mira candidatos con /demo_candidates."
        paper_trade = self.repository.fetch_paper_trade(trade_id)
        if not paper_trade:
            return f"No encontre paper trade ID {trade_id}."

        from app.brokers.mt5_demo_trader import MT5DemoTrader
        trader = MT5DemoTrader(self.settings)
        try:
            open_positions = len(trader.positions())
            result = trader.prepare_from_paper_trade(paper_trade, open_positions)
        finally:
            trader.disconnect()
        if not result.ok or result.draft is None:
            return (
                "No puedo preparar orden demo: "
                f"{self._demo_prepare_failure_hint(result.reason)}"
            )

        now = utc_now()
        expires_at = now + timedelta(minutes=self.settings.demo_trade_request_ttl_minutes)
        draft = result.draft
        request_id = self.repository.create_demo_trade_request(
            {
                "paper_trade_id": trade_id,
                "symbol": draft.symbol,
                "direction": draft.direction,
                "volume": draft.volume,
                "entry_price": draft.entry_price,
                "stop_loss": draft.stop_loss,
                "take_profit": draft.take_profit,
                "risk_pct": draft.risk_pct,
                "strategy_name": draft.strategy_name,
                "status": "pending",
                "reason": draft.reason,
                "request_summary": draft.request_summary,
                "created_at": now.isoformat(),
                "expires_at": expires_at.isoformat(),
            }
        )
        return (
            f"Orden demo preparada #{request_id}\n"
            f"{draft.request_summary}\n"
            f"Estrategia: {draft.strategy_name or '?'}\n"
            f"Motivo: {draft.reason}\n\n"
            f"Confirmar: /confirm_demo_trade {request_id}\n"
            f"Expira en {self.settings.demo_trade_request_ttl_minutes} min.\n"
            "Solo cuenta demo MT5. Real-money trading bloqueado."
        )

    def confirm_demo_trade_message(self, arg: str) -> str:
        if not self.settings.enable_mt5_demo_trading:
            return "Demo trading MT5 esta apagado: ENABLE_MT5_DEMO_TRADING=false."
        if self.repository.get_state("demo_trading_halted", "false") == "true":
            return "Demo trading esta detenido por /demo_halt. Usa /resume_trading para liberar."
        request_id = self._parse_int_arg(arg)
        if request_id is None:
            return "Uso: /confirm_demo_trade ID."
        request = self.repository.fetch_demo_trade_request(request_id)
        if not request:
            return f"No encontre solicitud demo #{request_id}."
        if request.get("status") != "pending":
            return f"La solicitud #{request_id} ya esta en estado {request.get('status')}."
        expires = parse_iso_datetime(str(request.get("expires_at") or ""))
        if expires is None or expires < utc_now():
            self.repository.update_demo_trade_request(
                request_id,
                {"status": "expired", "result_message": "confirmation expired"},
            )
            return f"La solicitud #{request_id} expiro. Prepara otra con /demo_prepare."

        from app.brokers.mt5_demo_trader import MT5DemoTrader
        trader = MT5DemoTrader(self.settings)
        try:
            open_positions = len(trader.positions())
            result = trader.send_prepared_request(request, open_positions)
        finally:
            trader.disconnect()

        now = utc_now().isoformat()
        self.repository.update_demo_trade_request(
            request_id,
            {
                "status": result.status,
                "confirmed_at": now,
                "sent_at": now if result.status == "sent" else None,
                "result_message": result.result_summary or result.reason,
            },
        )
        self.repository.create_demo_order(
            {
                "demo_request_id": request_id,
                "paper_trade_id": request["paper_trade_id"],
                "symbol": request["symbol"],
                "direction": request["direction"],
                "volume": request["volume"],
                "price": result.price,
                "stop_loss": request["stop_loss"],
                "take_profit": request["take_profit"],
                "retcode": result.retcode,
                "order_ticket": result.order_ticket,
                "deal_ticket": result.deal_ticket,
                "status": result.status,
                "strategy_name": request.get("strategy_name"),
                "result_summary": result.result_summary or result.reason,
                "sent_at": now,
            }
        )
        if result.ok:
            return (
                f"Orden demo enviada #{request_id}\n"
                f"{request['direction'].upper()} {request['symbol']} "
                f"{float(request['volume']):g} lot\n"
                f"Order: {result.order_ticket or '?'} | Deal: {result.deal_ticket or '?'}\n"
                f"Retcode: {result.retcode}\n"
                "Revisa la pestaña Operaciones en MT5 demo."
            )
        return (
            f"Orden demo fallida #{request_id}\n"
            f"Motivo: {result.reason}\n"
            f"Detalle: {result.result_summary or 'sin detalle'}"
        )

    def demo_positions_message(self) -> str:
        from app.brokers.mt5_demo_trader import MT5DemoTrader
        trader = MT5DemoTrader(self.settings)
        try:
            positions = trader.positions()
        finally:
            trader.disconnect()
        if not positions:
            return "No hay posiciones demo abiertas o MT5 demo no esta conectado."
        lines = [f"Posiciones demo MT5 abiertas ({len(positions)}):"]
        for pos in positions[:10]:
            ptype = pos.get("type")
            direction = "BUY" if ptype == 0 else "SELL" if ptype == 1 else str(ptype)
            lines.append(
                f"{pos.get('ticket')}: {pos.get('symbol')} {direction} "
                f"{pos.get('volume')} lot @ {pos.get('price_open')} | "
                f"SL {pos.get('sl')} | TP {pos.get('tp')} | PnL {pos.get('profit')}"
            )
        return "\n".join(lines)

    def demo_close_all_message(self) -> str:
        from app.brokers.mt5_demo_trader import MT5DemoTrader
        trader = MT5DemoTrader(self.settings)
        try:
            results = trader.close_all_positions()
        finally:
            trader.disconnect()
        if not results:
            return "No hay posiciones demo abiertas para cerrar."

        closed = [result for result in results if result.ok]
        failed = [result for result in results if not result.ok]
        lines = [
            f"Cierre demo MT5: {len(closed)}/{len(results)} posiciones cerradas."
        ]
        for result in results[:10]:
            status = "OK" if result.ok else "FALLO"
            ticket = result.ticket if result.ticket is not None else "?"
            symbol = result.symbol or "?"
            volume = f"{result.volume:g}" if result.volume is not None else "?"
            detail = result.result_summary or result.reason
            lines.append(f"{status} #{ticket} {symbol} {volume} lot | {detail}")
        if failed:
            lines.append("Revisa MT5 si alguna posicion quedo abierta.")
        return "\n".join(lines)

    def demo_halt_message(self) -> str:
        self.repository.set_state("demo_trading_halted", "true")
        return (
            "Demo trading detenido. No enviare nuevas ordenes demo hasta "
            "/resume_trading."
        )

    def data_quality_message(self) -> str:
        from app.intelligence.data_quality import run_full_check
        try:
            summary = run_full_check(self.repository, self.settings)
        except Exception as exc:
            return f"Data quality check fallo: {exc.__class__.__name__}"
        lines = [
            "Data quality (ultimas 24h):",
            f"  Symbols stale: {summary.get('stale_symbols', 0)}",
            f"  Gaps detectados: {summary.get('gaps_detected', 0)}",
            f"  Collector failures: {summary.get('collector_failures', 0)}",
        ]
        stale_list = summary.get("stale_list") or []
        if stale_list:
            lines.append("\nSymbols viejos:")
            for s in stale_list[:5]:
                lines.append(
                    f"  - {s.get('symbol')} ({s.get('age_minutes')}min)"
                )
        lines.append(DISCLAIMER)
        return "\n".join(lines)

    def walk_forward_message(self, args: str) -> str:
        from app.learning.walk_forward import WalkForwardBacktester
        from datetime import datetime, timedelta, timezone
        parts = args.split()
        if not parts:
            return (
                "Uso: /walk_forward STRATEGY [dias] [categoria]\n"
                "Ej: /walk_forward breakout 30 stock"
            )
        strategy = parts[0].lower()
        days = 30
        category = None
        if len(parts) > 1:
            try:
                days = int(parts[1])
                days = max(7, min(days, 365))
            except ValueError:
                pass
        if len(parts) > 2:
            category = parts[2].lower()

        end = datetime.now(timezone.utc)
        start = end - timedelta(days=days)
        wf = WalkForwardBacktester(self.repository, self.settings)
        windows = wf.run(strategy, category, start.isoformat(), end.isoformat())
        if not windows:
            return (
                f"Walk-forward {strategy} (ultimos {days}d): sin ventanas. "
                f"Posibles causas: pocas muestras (<{self.settings.walk_forward_min_train_samples}), "
                f"sin trades cerrados para esa strategy, o periodo muy corto."
            )
        wf.persist_windows(windows)
        last = windows[-3:]
        lines = [f"Walk-forward {strategy} (ultimos {days}d, {len(windows)} ventanas):"]
        for w in last:
            lines.append(
                f"  {w.train_start[:10]} → {w.test_end[:10]}: "
                f"train sharpe {w.train_sharpe:.2f} (wr {w.train_win_rate:.0%}, n={w.train_samples}) → "
                f"test sharpe {w.test_sharpe:.2f} (wr {w.test_win_rate:.0%}, n={w.test_samples}) | "
                f"degradacion {w.degradation_pct:+.1f}%"
            )
        lines.append(DISCLAIMER)
        return "\n".join(lines)

    def export_csv_message(self, arg: str) -> str:
        from pathlib import Path
        from app.utils.csv_export import (
            export_horizons_csv,
            export_outcomes_csv,
            export_paper_trades_csv,
            export_walk_forward_csv,
        )
        kind = (arg or "").strip().lower() or "outcomes"
        export_root = Path(self.settings.csv_export_path)
        if not export_root.is_absolute():
            export_root = Path.cwd() / export_root
        from datetime import datetime, timezone
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        out_path = export_root / f"{kind}_{ts}.csv"
        n = 0
        if kind == "outcomes":
            n = export_outcomes_csv(
                self.repository, "1970-01-01", "2099-12-31",
                out_path, root=Path.cwd(),
            )
        elif kind in {"trades", "paper_trades", "paper"}:
            n = export_paper_trades_csv(
                self.repository, status=None, path=out_path, root=Path.cwd()
            )
        elif kind in {"horizons", "horizon"}:
            n = export_horizons_csv(
                self.repository, horizon_hours=None, path=out_path, root=Path.cwd()
            )
        elif kind in {"walk_forward", "wf"}:
            n = export_walk_forward_csv(
                self.repository, strategy_name=None, path=out_path, root=Path.cwd()
            )
        else:
            return (
                "Uso: /export_csv [outcomes|trades|horizons|walk_forward]\n"
                "Default: outcomes."
            )
        return (
            f"Export OK. Tipo: {kind}, filas: {n}, archivo: {out_path}\n"
            + DISCLAIMER
        )
