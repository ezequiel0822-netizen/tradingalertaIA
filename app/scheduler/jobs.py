import json
import logging
import time
from datetime import timedelta

from app.alerts.alert_formatter import format_grouped_telegram_alert
from app.alerts.telegram_notifier import TelegramNotifier
from app.analyzers.alert_decision_engine import (
    ALERT_PRIORITY,
    candidate_for_security_check,
    choose_primary_alert,
    security_event_types,
    should_send_alert,
)
from app.analyzers.learned_weights import apply_learned_weights
from app.analyzers.learning_gate import evaluate_learning_gate
from app.analyzers.liquidity_analyzer import detect_liquidity_spike, detect_price_spike
from app.analyzers.move_estimator import estimate_move
from app.analyzers.filing_analyzer import analyze_filings
from app.analyzers.news_analyzer import analyze_news
from app.analyzers.pro_intelligence import analyze_professional_setup
from app.analyzers.risk_analyzer import security_reasons
from app.analyzers.technical_patterns import analyze_ohlcv, candles_from_gecko
from app.analyzers.token_score import score_token
from app.analyzers.volume_spike_detector import detect_volume_spike
from app.assistant.telegram_assistant import TelegramAssistantPoller
from app.alerts.trade_reporter import format_trade_opened
from app.brokers.mt5_reader import MT5Reader
from app.collectors.cot_collector import COTCollector
from app.collectors.dexscreener_collector import DexScreenerCollector
from app.collectors.economic_calendar_collector import EconomicCalendarCollector
from app.collectors.forex_collector import ForexCollector
from app.collectors.geckoterminal_collector import GeckoTerminalCollector
from app.collectors.goplus_collector import GoPlusCollector
from app.collectors.macro_collector import MacroCollector
from app.collectors.news_collector import NewsCollector
from app.collectors.sec_collector import SECFilingsCollector
from app.collectors.stock_collector import StockCollector
from app.config.settings import Settings
from app.intelligence.ollama_processor import build_llm_processor
from app.intelligence.data_quality import run_full_check as run_data_quality_check
from app.intelligence.macro_context import current_session, full_macro_context
from app.learning.feature_extractor import extract_features
from app.learning.lifecycle_manager import manage_open_positions
from app.learning.trade_outcomes import (
    session_of,
    should_execute_live,
    should_execute_live_sliced,
)
from app.portfolio.mt5_reconciler import MT5Reconciler
from app.portfolio.portfolio_manager import PortfolioManager
from app.risk.position_sizer import calculate_position_size
from app.risk.risk_manager import RiskManager
from app.strategies.base import StrategyContext
from app.strategies.strategy_router import StrategyRouter
from app.database.db import init_db
from app.database.models import AlertRecord, SecuritySummary, TokenSnapshot
from app.database.repository import Repository
from app.learning.training_engine import run_learning_cycle
from app.utils.dedup import should_send_deduped_alert
from app.utils.obsidian_memory import (
    write_daily_memory_if_needed,
    write_weekly_report_if_needed,
)
from app.utils.time_utils import minutes_ago, utc_now


logger = logging.getLogger(__name__)

# v3.9.5: retencion (dias) de alerts no-enviadas/outcomes/security_checks.
LEARNING_RETENTION_DAYS = 90


class TradingAlertJob:
    def __init__(
        self,
        settings: Settings,
        cli_mode_override: str | None = None,
    ) -> None:
        self.settings = settings
        # Phase 4.5 v2.4.0: bot_mode override desde CLI (--mode flag)
        self.cli_mode_override = cli_mode_override
        self._active_bot_mode: str = "trader"
        init_db(settings.sqlite_path)
        self.repository = Repository(settings.sqlite_path)
        self.dexscreener = DexScreenerCollector(settings)
        self.geckoterminal = GeckoTerminalCollector(settings)
        self.stocks = StockCollector(settings)
        self.forex = ForexCollector(settings)
        self.news = NewsCollector(settings)
        self.sec = SECFilingsCollector(settings)
        self.goplus = GoPlusCollector(settings)
        self.notifier = TelegramNotifier(settings)
        self.assistant = TelegramAssistantPoller(
            settings,
            self.repository,
            self.notifier,
        )
        # Fase 2.5 trader engine
        self.mt5_reader = MT5Reader(settings)
        if settings.enable_mt5_reader:
            try:
                self.mt5_reader.connect()
            except Exception:
                logger.exception("MT5 connect failed; continuing without")
        self.portfolio_manager = PortfolioManager(
            settings, self.repository, self.mt5_reader
        )
        self.risk_manager = RiskManager(
            settings, self.repository, self.portfolio_manager
        )
        self.strategy_router = StrategyRouter(settings)
        # Phase 3.5 v2.2.0: Claude processor (soft-fail si key no presente)
        # v2.10.0: factory de proveedor LLM (Ollama local si enable_ollama_integration,
        # sino Claude). Ambos soft-fail/read-only; el nombre del atributo se conserva.
        self.claude_processor = build_llm_processor(settings, self.repository)
        # Phase 3 v2.2.0: macro context + economic calendar collectors
        self.macro_collector = MacroCollector(settings)
        self.calendar_collector = EconomicCalendarCollector(settings)
        # v3.9.0: COT collector (CFTC semanal, info que el precio no digirio; opt-in OFF)
        self.cot_collector = COTCollector(settings)
        # Phase 4 v2.3.0: data quality check counter (no es por tiempo, es por ciclo)
        self._cycle_counter = 0
        # v2.6.7: MT5 reconciler. Instancia única reusable; lazy del trader.
        # Sólo se construye si demo trading está activo — evita instanciar
        # MT5DemoTrader sin necesidad.
        self._mt5_reconciler: MT5Reconciler | None = None
        self._mt5_demo_trader = None  # instanciado lazy en _ensure_reconciler
        if settings.enable_mt5_demo_trading:
            try:
                from app.brokers.mt5_demo_trader import MT5DemoTrader
                self._mt5_demo_trader = MT5DemoTrader(settings, self.mt5_reader)
                self._mt5_reconciler = MT5Reconciler(
                    settings, self.repository, self._mt5_demo_trader, self.mt5_reader
                )
            except Exception:
                logger.exception("MT5Reconciler init failed; continuing without")
        # v2.9.0: MLPredictor (capa ML hibrida). Soft-fail: si xgboost no esta
        # instalado o falla, queda None y el sistema se comporta igual que antes.
        self._ml_predictor = None
        self._ml_last_retrain_date: str | None = None
        if settings.enable_ml_predictor:
            try:
                from app.learning.ml_predictor import MLPredictor

                self._ml_predictor = MLPredictor(
                    min_train_samples=settings.ml_min_train_samples
                )
            except Exception:
                logger.exception("MLPredictor init failed; continuing without ML")

    def run_forever(self) -> None:
        # Log solo el nombre del archivo (no path completo) para evitar filesystem leak.
        logger.info("Trading Alert AI started. Database: %s", self.settings.sqlite_path.name)
        while True:
            started = time.monotonic()
            try:
                self.run_once()
            except Exception:
                logger.exception("Monitoring cycle failed, continuing next cycle")

            elapsed = time.monotonic() - started
            sleep_for = max(self.settings.poll_interval_seconds - elapsed, 0)
            logger.info("Next monitoring cycle in %.1f seconds", sleep_for)
            time.sleep(sleep_for)

    def run_once(self) -> None:
        # Phase 4.5 v2.4.0: resolver modo activo (CLI > bot_state > setting)
        from app.utils.bot_mode import resolve_bot_mode
        self._active_bot_mode = resolve_bot_mode(
            self.settings, self.repository, self.cli_mode_override
        )
        logger.info("Bot mode active: %s", self._active_bot_mode)

        # Phase 3.5: reset cycle counter para throttle de Claude
        self.claude_processor.reset_cycle()

        # v3.9.4: defensa en profundidad — el assistant es LO PRIMERO del ciclo;
        # si falla (DB locked al persistir offset, etc.) el ciclo debe seguir igual
        # (lifecycle/reconciler/alertas no pueden depender de Telegram).
        try:
            handled = self.assistant.process_updates()
            if handled:
                logger.info("Telegram assistant handled %s message(s)", handled)
        except Exception:
            logger.exception("Telegram assistant fallo; el ciclo sigue")

        # Phase 3 v2.2.0: macro context refresh (gateado por interval)
        try:
            if self.macro_collector.should_run(self.repository):
                macro_snapshot = self.macro_collector.collect()
                if macro_snapshot:
                    self.repository.insert_macro_snapshot(macro_snapshot)
                    self.repository.set_state(
                        "macro_last_capture_iso", macro_snapshot["captured_at"]
                    )
                    logger.info(
                        "Macro snapshot: VIX=%s DXY=%s regime=%s",
                        macro_snapshot.get("vix_value"),
                        macro_snapshot.get("dxy_value"),
                        macro_snapshot.get("regime"),
                    )
        except Exception:
            logger.exception("Macro collector failed")

        # v3.9.0: COT refresh (CFTC semanal; gateado por interval, soft-fail, solo captura)
        try:
            if self.cot_collector.should_run(self.repository):
                from app.utils.time_utils import utc_now_iso

                cot_snapshots = self.cot_collector.collect() or []
                inserted = 0
                for snap in cot_snapshots:
                    if self.repository.insert_cot_snapshot(snap):
                        inserted += 1
                # Marca el intervalo SIEMPRE que se intento, aunque collect falle/vacio:
                # la data es semanal -> no reintentar cada ciclo ni martillar la API de CFTC.
                self.repository.set_state("cot_last_capture_iso", utc_now_iso())
                if cot_snapshots:
                    logger.info(
                        "COT snapshots: %d mercados, %d nuevos (report %s)",
                        len(cot_snapshots),
                        inserted,
                        cot_snapshots[0].get("report_date"),
                    )
                else:
                    logger.warning(
                        "COT collector: sin data este intento (soft-fail); "
                        "reintenta tras el intervalo"
                    )
        except Exception:
            logger.exception("COT collector failed")

        # Phase 3 v2.2.0: economic calendar refresh (gateado por interval)
        try:
            if self.calendar_collector.should_run(self.repository):
                events = self.calendar_collector.collect()
                created = 0
                for ev in events:
                    if self.repository.upsert_economic_event(ev):
                        created += 1
                self.repository.set_state(
                    "calendar_last_refresh_iso",
                    minutes_ago(0),
                )
                logger.info("Economic calendar refreshed: %s events", created)
        except Exception:
            logger.exception("Economic calendar fetch failed")

        # Fase 2.5: gestionar posiciones abiertas ANTES de buscar nuevas
        if self.settings.enable_paper_trading:
            try:
                lifecycle_summary = manage_open_positions(
                    self.settings, self.repository, self.mt5_reader
                )
                if lifecycle_summary.get("managed", 0):
                    logger.info("Lifecycle: %s", lifecycle_summary)
            except Exception:
                logger.exception("Lifecycle management failed")

        # v2.6.7: MT5 reconciler — cierra huérfanas y sincroniza SLs.
        # Corre DESPUÉS del lifecycle para que las decisiones del lifecycle
        # (cerrar paper_trade por time, mover SL por trailing/breakeven) se
        # reflejen en MT5 dentro del mismo ciclo. Soft-fail.
        if self._mt5_reconciler is not None:
            try:
                self._mt5_reconciler.reconcile()
            except Exception:
                logger.exception("MT5Reconciler.reconcile() failed")

        snapshots = self._limit_snapshots(self._collect_snapshots())
        logger.info("Collected %s market snapshots", len(snapshots))

        records: list[AlertRecord] = []
        send_candidates: list[AlertRecord] = []
        inserted_record_ids: set[int] = set()
        security_checks = 0
        chart_analyses = 0
        sec_analyses = 0
        processed_keys: set[tuple[str, str, str, str]] = set()
        for snapshot in snapshots:
            if not snapshot.token_address:
                continue

            key = (
                snapshot.chain,
                snapshot.token_address.lower(),
                snapshot.source,
                snapshot.event_type,
            )
            if key in processed_keys:
                continue
            processed_keys.add(key)

            previous = self.repository.get_token(snapshot.chain, snapshot.token_address)
            if (
                candidate_for_security_check(snapshot, self.settings)
                and security_checks < self.settings.max_security_checks_per_run
            ):
                security = self.goplus.check_token(snapshot.chain, snapshot.token_address)
                security_checks += 1
            else:
                security = SecuritySummary(raw_summary="unknown")
            score_result = score_token(snapshot, security, self.settings)

            # Phase 4.5 v2.4.0: Memecoin Hunter enriquece score base si aplica
            hunter_bonus = 0
            hunter_multiplier = 1.0
            hunter_reasons: list[str] = []
            if (
                snapshot.category == "memecoin"
                and self.settings.enable_memecoin_hunter
            ):
                from app.analyzers.memecoin_hunter import analyze_memecoin
                hunter = analyze_memecoin(snapshot, security, self.settings)
                hunter_bonus = hunter.early_bonus
                hunter_multiplier = hunter.anti_rug_multiplier
                hunter_reasons = list(hunter.reasons)
                # Override score base con la combinacion
                new_score = int(
                    max(0, min(100, (score_result.score + hunter_bonus) * hunter_multiplier))
                )
                # Mantenemos critical_risk + risk_level, solo ajustamos score
                score_result = type(score_result)(
                    score=new_score,
                    risk_level=score_result.risk_level,
                    reasons=score_result.reasons,
                    critical_risk=score_result.critical_risk,
                )

            estimate = estimate_move(
                snapshot,
                security,
                score_result.score,
                self.settings,
            )
            allow_chart = (
                chart_analyses < self.settings.max_chart_analyses_per_run
                and (
                    snapshot.category == "stock"
                    or estimate.estimated_gain_pct >= self.settings.min_estimated_gain_pct * 0.5
                )
            )
            allow_sec = (
                snapshot.category == "stock"
                and sec_analyses < self.settings.max_sec_filings_per_run
            )
            intel_reasons, intel_rank_bonus, used_chart, used_sec, pro_setup = (
                self._market_intelligence(
                    snapshot,
                    allow_chart,
                    allow_sec,
                    security,
                )
            )
            if used_chart:
                chart_analyses += 1
            if used_sec:
                sec_analyses += 1
            events, event_reasons = self._detect_events(snapshot, previous, security)
            # Phase 4.5 v2.4.0: si el collector marcó EARLY_MEMECOIN, lo
            # priorizamos como alert_type (peso 90 > BOOSTED 65 > TRENDING 60).
            if snapshot.event_type == "EARLY_MEMECOIN" and "EARLY_MEMECOIN" not in events:
                events.insert(0, "EARLY_MEMECOIN")
            alert_type = choose_primary_alert(events)
            reasons = self._unique_reasons(
                event_reasons
                + intel_reasons
                + estimate.reasons
                + security_reasons(security)
                + score_result.reasons
                + hunter_reasons
            )

            features_dict = {
                "category": snapshot.category,
                "alert_type": alert_type,
                "risk_level": score_result.risk_level,
                "reasons": json.dumps(reasons, ensure_ascii=False),
                "estimate_summary": json.dumps(estimate.reasons, ensure_ascii=False),
                "security_summary": security.raw_summary or "unknown",
                "score": score_result.score,
                "estimate_confidence": estimate.confidence,
                "estimated_gain_pct": estimate.estimated_gain_pct,
            }
            features = extract_features(features_dict)
            adjusted_score, weight_reasons = apply_learned_weights(
                score_result.score,
                features,
                snapshot.category,
                self.settings,
                self.repository,
            )
            if weight_reasons:
                reasons = self._unique_reasons(reasons + weight_reasons)

            token_id = self.repository.upsert_token(
                snapshot,
                adjusted_score,
                score_result.risk_level,
                estimate,
            )
            if self.settings.enable_price_snapshots and snapshot.price:
                try:
                    self.repository.insert_price_snapshot(snapshot, token_id)
                except Exception:
                    logger.exception("Failed to insert price snapshot")
            # v3.9.5: solo memecoins tienen chequeo de seguridad real (GoPlus).
            # Para stock/forex/gold se escribia una fila "unknown" por snapshot
            # (~65k filas basura/dia con memecoins apagadas).
            if snapshot.category == "memecoin":
                self.repository.save_security_check(
                    snapshot.chain, snapshot.token_address, security
                )

            should_send = should_send_alert(
                adjusted_score,
                score_result.critical_risk,
                estimate,
                self.settings,
                snapshot.category,
            )

            if should_send and self.settings.enable_learning_gate:
                gate_ok, gate_reason = evaluate_learning_gate(
                    features,
                    snapshot.category,
                    self.settings,
                    self.repository,
                )
                if not gate_ok:
                    should_send = False
                    reasons = self._unique_reasons(
                        reasons + [f"Bloqueada por learning gate: {gate_reason}"]
                    )
                    logger.info(
                        "Alert blocked by learning gate: chain=%s symbol=%s reason=%s",
                        snapshot.chain,
                        snapshot.symbol,
                        gate_reason,
                    )

            alert_record = AlertRecord(
                token_id=token_id,
                alert_type=alert_type,
                snapshot=snapshot,
                app_version=self.settings.app_version,
                category=snapshot.category,
                score=adjusted_score,
                risk_level=score_result.risk_level,
                reasons=reasons,
                security=security,
                estimate=estimate,
                intel_rank_bonus=intel_rank_bonus,
                sent_to_telegram=False,
            )
            # v3.9.5: atributo transitorio (no es campo del dataclass, no se
            # persiste) para expandir con LLM SOLO lo que se envia.
            alert_record._pro_setup = pro_setup  # type: ignore[attr-defined]
            records.append(alert_record)

            # Fase 2.5: Strategy router → potencialmente abre paper trade
            if (
                self.settings.enable_strategy_router
                and snapshot.category in {"stock", "forex", "gold"}
                and self._active_bot_mode != "alerts_only"
            ):
                self._try_open_paper_trades(
                    snapshot, alert_record, inserted_record_ids
                )

            if should_send:
                recent = self.repository.latest_sent_alert(
                    snapshot.chain,
                    snapshot.token_address,
                    alert_type,
                    self.settings.dedup_window_minutes,
                )
                dedup_ok, dedup_reason = should_send_deduped_alert(
                    recent,
                    alert_type,
                    adjusted_score,
                    score_result.risk_level,
                    snapshot,
                    estimate.estimated_gain_pct,
                )
                if dedup_ok:
                    send_candidates.append(alert_record)
                else:
                    logger.info("Alert skipped by dedup: %s", dedup_reason)

        sent_count = self._send_ranked_candidates(send_candidates)
        for record in records:
            if id(record) in inserted_record_ids:
                continue
            self.repository.insert_alert(record)
        # v3.9.4: soft-fail como su hermana weekly — un OSError del vault (OneDrive
        # lockeado, permisos) no puede abortar learning/resumen/purga del ciclo.
        try:
            write_daily_memory_if_needed(
                self.settings,
                self.repository,
                records,
                sent_count,
            )
        except Exception:
            logger.exception("Obsidian daily memory fallo; el ciclo sigue")
        if self.settings.enable_learning_engine:
            learning = run_learning_cycle(self.settings, self.repository)
            logger.info("Learning cycle complete. %s", learning.summary)
            self._maybe_retrain_ml()

        # v3.1.0: resumen diario por Telegram (read-only, soft-fail, gate por fecha UTC).
        self._maybe_send_daily_summary()

        # v3.2.0 (Fase C): lecciones por trade + propuestas (read/registro, soft-fail).
        self._maybe_run_continuous_learner()

        # v3.4.0 (exit shadow): registra el camino de R de los abiertos (read/registro).
        self._maybe_record_exit_shadow()

        # v3.13.0: el agente IA aprende de los candidatos ya cerrados (opt-in, soft-fail).
        self._maybe_ai_agent_learn()

        if self.settings.enable_price_snapshots:
            last_purge = self.repository.get_state("snapshots_last_purge")
            cutoff = minutes_ago(24 * 60)
            if last_purge is None or last_purge < cutoff:
                try:
                    deleted = self.repository.purge_old_snapshots(
                        self.settings.snapshot_retention_days
                    )
                    self.repository.set_state(
                        "snapshots_last_purge",
                        minutes_ago(0),
                    )
                    logger.info("Purged %s old price snapshots", deleted)
                except Exception:
                    logger.exception("Failed to purge old price snapshots")

        # v3.9.5: retencion de las tablas calientes (alerts/signal_outcomes/
        # security_checks crecian ~65k filas/dia c/u sin limite). 1x/dia.
        # Conserva alerts enviadas y las vinculadas a paper_trades.
        last_learning_purge = self.repository.get_state("learning_last_purge")
        if last_learning_purge is None or last_learning_purge < minutes_ago(24 * 60):
            try:
                purged = self.repository.purge_old_learning_data(
                    LEARNING_RETENTION_DAYS
                )
                self.repository.set_state("learning_last_purge", minutes_ago(0))
                logger.info("Purged learning data: %s", purged)
            except Exception:
                logger.exception("Failed to purge learning data")

        if self.settings.enable_weekly_obsidian_report:
            try:
                write_weekly_report_if_needed(self.settings, self.repository)
            except Exception:
                logger.exception("Failed to write weekly Obsidian report")

        # Phase 4 v2.3.0: data quality check cada N ciclos
        self._cycle_counter += 1
        if (
            self.settings.enable_data_quality_monitor
            and self._cycle_counter % max(1, self.settings.data_quality_check_every_n_cycles) == 0
        ):
            try:
                dq = run_data_quality_check(self.repository, self.settings)
                if dq.get("stale_symbols", 0) > 0 or dq.get("gaps_detected", 0) > 0:
                    logger.warning(
                        "Data quality: %s stale symbols, %s gaps",
                        dq.get("stale_symbols", 0),
                        dq.get("gaps_detected", 0),
                    )
            except Exception:
                logger.exception("Data quality check failed")

        logger.info("Monitoring cycle complete. Telegram alerts sent: %s", sent_count)

    def _collect_snapshots(self) -> list[TokenSnapshot]:
        snapshots: list[TokenSnapshot] = []
        collectors: list[tuple[str, object]] = []
        # v3.7.0: el motor de memecoins (DEX/Gecko) solo corre si esta encendido.
        # Apagado => el ciclo no gasta tiempo/red en memecoins y le sobra
        # presupuesto a la bolsa (acciones/forex/oro).
        if self.settings.enable_memecoin_engine:
            collectors.append(("DEX Screener", self.dexscreener))
            collectors.append(("GeckoTerminal", self.geckoterminal))
        collectors.append(("Stocks", self.stocks))
        collectors.append(("Forex", self.forex))
        for collector_name, collector in collectors:
            try:
                snapshots.extend(collector.collect())
            except Exception:
                logger.exception("%s collector failed", collector_name)
        return snapshots

    def _send_ranked_candidates(self, candidates: list[AlertRecord]) -> int:
        if not candidates:
            return 0
        if self.repository.alerts_paused():
            logger.info("Automatic Telegram alerts are paused by assistant state")
            return 0

        sent_count = 0
        # Phase 4.5 v2.4.0: memecoin se separa en early vs mature.
        # Phase 3 v2.2.0: forex/gold ahora pueden alertar segun flags.
        # v2.9.1: las acciones se siguen analizando/aprendiendo siempre; aca solo
        # decidimos si sus ALERTAS DE CANDIDATOS van a Telegram (enable_stock_telegram).
        # Los avisos de apertura/cierre de trades son otro flujo (no se ven afectados).
        cats: list[str] = []
        if self.settings.enable_stock_telegram:
            cats.append("stock")
        if self.settings.enable_memecoin_telegram:
            cats.insert(0, "memecoin_early")
            cats.insert(1, "memecoin_mature")
        if self.settings.enable_forex_alerts:
            cats.append("forex")
        if self.settings.enable_gold_alerts:
            cats.append("gold")
        categories = tuple(cats)
        daily_caps = {
            "memecoin_early": self.settings.max_early_memecoin_alerts_per_24h,
            "memecoin_mature": self.settings.max_mature_memecoin_alerts_per_24h,
            "stock": self.settings.stock_max_alerts_per_24h,
            "forex": self.settings.max_forex_alerts_per_24h,
            "gold": self.settings.max_gold_alerts_per_24h,
        }
        run_caps = {
            "memecoin_early": self.settings.max_early_memecoin_alerts_per_run,
            "memecoin_mature": self.settings.memecoin_max_alerts_per_run,
            "stock": self.settings.stock_max_alerts_per_run,
            "forex": self.settings.max_forex_alerts_per_run,
            "gold": self.settings.max_gold_alerts_per_run,
        }

        def _bucket_of(record: AlertRecord) -> str:
            if record.category == "memecoin":
                return "memecoin_early" if record.alert_type == "EARLY_MEMECOIN" else "memecoin_mature"
            return record.category

        ranked = sorted(candidates, key=self._alert_rank, reverse=True)
        for category in categories:
            # sent_alert_count usa categoria real en DB; para memecoin sumamos
            # ambos buckets ya que la DB no distingue early/mature.
            real_db_cat = "memecoin" if category.startswith("memecoin_") else category
            sent_last_window = self.repository.sent_alert_count(
                real_db_cat,
                self.settings.alert_cap_window_hours,
            )
            slots = min(
                max(daily_caps[category] - sent_last_window, 0),
                run_caps[category],
            )
            if slots <= 0:
                logger.info("No Telegram slots left for category=%s", category)
                continue

            category_candidates = [
                record for record in ranked if _bucket_of(record) == category
            ][:slots]
            if not category_candidates:
                continue
            if sent_count >= self.settings.max_alerts_per_run:
                return sent_count

            # v3.9.5: expand LLM SOLO para lo que se envia (antes corria en el hot
            # path para ~54 snapshots/ciclo; aca son <= slots por categoria).
            self._enrich_with_llm(category_candidates)
            message = format_grouped_telegram_alert(
                category_candidates,
                category,
                self.settings.app_version,
            )
            sent = self.notifier.send_message(message)
            if sent:
                sent_count += 1
                for record in category_candidates:
                    record.sent_to_telegram = True
                logger.info(
                    "Grouped Telegram alert sent: category=%s items=%s",
                    category,
                    len(category_candidates),
                )
        return sent_count

    def _enrich_with_llm(self, records: list[AlertRecord]) -> None:
        """v3.9.5: expande con LLM (Claude/Ollama) las reasons de los records que SI
        van a Telegram. Reemplaza el expand por-snapshot del hot path (~30-50s/ciclo
        para alertas que en un 99.9% no se enviaban). Soft-fail por record."""
        if not self.settings.enable_pro_intelligence:
            return
        for record in records:
            pro = getattr(record, "_pro_setup", None)
            if pro is None:
                continue
            try:
                claude_text = self.claude_processor.expand_pro_analysis(
                    pro, record.snapshot
                )
                if claude_text:
                    record.reasons.append(f"🤖 IA: {claude_text}")
            except Exception:
                logger.exception("Claude expand_pro_analysis failed")

    def _alert_rank(self, record: AlertRecord) -> float:
        event_score = ALERT_PRIORITY.get(record.alert_type, 0)
        gain_weight = 5 if record.category == "stock" else 1
        intel_bonus = record.intel_rank_bonus
        return (
            event_score
            + record.score
            + (record.estimate.estimated_gain_pct * gain_weight)
            + (record.estimate.confidence * 1.5)
            - (record.estimate.estimated_loss_pct * 0.8)
            + intel_bonus
        )

    def _market_intelligence(
        self,
        snapshot: TokenSnapshot,
        allow_chart: bool,
        allow_sec: bool,
        security: SecuritySummary,
    ) -> tuple[list[str], float, bool, bool]:
        if not self.settings.enable_advanced_market_intel:
            return [], 0, False, False

        reasons: list[str] = []
        rank_bonus = 0.0
        used_chart = False
        used_sec = False
        pattern = None
        news_label = "no_recent_news"
        news_score = 0
        filing_label = "no_recent_filings"
        filing_score = 0

        candles = []
        if allow_chart:
            if snapshot.category == "stock":
                candles = snapshot.raw.get("candles") or []
                used_chart = bool(candles)
            elif snapshot.pair_address:
                payload = self.geckoterminal.fetch_pool_ohlcv(
                    snapshot.chain,
                    snapshot.pair_address,
                    timeframe="minute",
                    aggregate=5,
                    limit=60,
                )
                if payload:
                    candles = candles_from_gecko(payload)
                    used_chart = bool(candles)

        if candles:
            pattern = analyze_ohlcv(candles)
            rank_bonus += pattern.score * 1.4
            reasons.append(
                f"Patron grafico: {pattern.label} ({pattern.trend}, score {pattern.score})."
            )
            if pattern.sparkline:
                reasons.append(f"Visual: {pattern.sparkline}")
            # v3.12.0 — VWAP informativo en la alerta (no toca rank_bonus).
            # Texto sin needles del feature_extractor.
            if pattern.vwap_dist_pct is not None:
                side = "sobre" if pattern.vwap_dist_pct >= 0 else "bajo"
                reasons.append(
                    f"VWAP sesion: precio {abs(pattern.vwap_dist_pct):.2f}% {side} VWAP."
                )
            # v3.12.0 — footprint/Hurst: solo lo notable (vela dominante,
            # secuencia detectada, o regimen no-aleatorio). Sin needles.
            if pattern.candle_strength.startswith("strong") or pattern.candle_patterns:
                seq = pattern.candle_patterns or "sin secuencia"
                reasons.append(
                    f"Velas: {pattern.candle_strength} | {seq}."
                )
            if pattern.hurst is not None and pattern.hurst_regime != "random":
                reasons.append(
                    f"Hurst {pattern.hurst:.2f} ({pattern.hurst_regime})."
                )
            reasons.extend(pattern.reasons[:3])

        if snapshot.category == "stock" and self.settings.enable_news_intel:
            news_items = self.news.collect_for_symbol(snapshot.symbol)
            news_label, news_score, news_reasons = analyze_news(news_items)
            rank_bonus += news_score
            reasons.append(f"Noticias/eventos: {news_label} (score {news_score}).")
            reasons.extend(news_reasons[:4])

        if allow_sec and self.settings.enable_sec_filings_intel:
            used_sec = True
            filings = self.sec.collect_for_symbol(snapshot.symbol)
            filing_label, filing_score, filing_reasons = analyze_filings(filings)
            rank_bonus += filing_score
            if filings:
                reasons.append(f"SEC filings: {filing_label} (score {filing_score}).")
                reasons.extend(filing_reasons[:3])

        pro_setup = None
        if self.settings.enable_pro_intelligence:
            pro = analyze_professional_setup(
                snapshot,
                security,
                pattern,
                news_label,
                news_score,
                filing_label,
                filing_score,
            )
            pro_setup = pro
            rank_bonus += pro.score * 1.2
            reasons.append(
                f"IA Pro: {pro.label}, sesgo {pro.bias}, confianza {pro.confidence}/100."
            )
            reasons.append(f"Setup: {pro.setup}.")
            reasons.extend(pro.reasons[:3])
            reasons.extend([f"Riesgo pro: {risk}" for risk in pro.risks[:2]])
            # v3.9.5: el expand LLM (Claude/Ollama) salio de aca — corria para CADA
            # snapshot (~30-50s/ciclo medidos) y el 99.9% de esas alertas jamas se
            # enviaba. Ahora se expande SOLO lo que se envia (_enrich_with_llm en el
            # send-path); el pro se devuelve para eso.

        return reasons[:12], rank_bonus, used_chart, used_sec, pro_setup

    def _limit_snapshots(self, snapshots: list[TokenSnapshot]) -> list[TokenSnapshot]:
        unique: dict[tuple[str, str, str, str], TokenSnapshot] = {}
        for snapshot in snapshots:
            if not snapshot.token_address:
                continue
            key = (
                snapshot.chain,
                snapshot.token_address.lower(),
                snapshot.source,
                snapshot.event_type,
            )
            current = unique.get(key)
            if current is None or self._snapshot_priority(snapshot) > self._snapshot_priority(current):
                unique[key] = snapshot

        memecoins = [
            snapshot for snapshot in unique.values() if snapshot.category == "memecoin"
        ]
        stocks = [
            snapshot for snapshot in unique.values() if snapshot.category == "stock"
        ]
        # Forex y oro entran al pipeline para snapshots/horizons; no van a Telegram.
        forex_and_gold = [
            snapshot
            for snapshot in unique.values()
            if snapshot.category in {"forex", "gold"}
        ]
        ordered_memecoins = sorted(memecoins, key=self._snapshot_priority, reverse=True)
        ordered_stocks = sorted(stocks, key=self._snapshot_priority, reverse=True)
        limit = max(self.settings.max_snapshots_per_run, 1)
        if len(ordered_memecoins) > limit:
            logger.info(
                "Limiting memecoin snapshots from %s to %s for this cycle",
                len(ordered_memecoins),
                limit,
            )
        return ordered_memecoins[:limit] + ordered_stocks + forex_and_gold

    def _snapshot_priority(self, snapshot: TokenSnapshot) -> float:
        event_score = ALERT_PRIORITY.get(snapshot.event_type, 0)
        liquidity_score = min((snapshot.liquidity_usd or 0) / 100_000, 20)
        volume_score = min((snapshot.volume_1h or 0) / 100_000, 20)
        return event_score + liquidity_score + volume_score

    def _detect_events(
        self,
        snapshot: TokenSnapshot,
        previous: dict | None,
        security: SecuritySummary,
    ) -> tuple[list[str], list[str]]:
        events = [snapshot.event_type or "WATCHLIST_MOVEMENT"]
        reasons: list[str] = []

        volume_spike, volume_reasons = detect_volume_spike(
            snapshot, previous, self.settings
        )
        if volume_spike:
            events.append("VOLUME_SPIKE")
            reasons.extend(volume_reasons)

        liquidity_spike, liquidity_reasons = detect_liquidity_spike(
            snapshot, previous, self.settings
        )
        if liquidity_spike:
            events.append("LIQUIDITY_SPIKE")
            reasons.extend(liquidity_reasons)

        price_spike, price_reasons = detect_price_spike(snapshot)
        if price_spike:
            events.append("PRICE_SPIKE")
            reasons.extend(price_reasons)

        events.extend(security_event_types(security))

        if snapshot.is_boosted:
            reasons.append("Token aparece con boost activo.")
        if snapshot.is_trending:
            reasons.append("Pool aparece en trending.")
        if snapshot.is_new:
            reasons.append("Perfil reciente de token detectado.")

        return self._unique_events(events), self._unique_reasons(reasons)

    def _unique_events(self, events: list[str]) -> list[str]:
        seen: set[str] = set()
        output: list[str] = []
        for event in events:
            if event not in seen:
                output.append(event)
                seen.add(event)
        return output

    def _unique_reasons(self, reasons: list[str]) -> list[str]:
        seen: set[str] = set()
        output: list[str] = []
        for reason in reasons:
            if reason and reason not in seen:
                output.append(reason)
                seen.add(reason)
        return output[:10] or ["Evento detectado y guardado para revisión manual."]

    def _try_open_paper_trades(
        self,
        snapshot: TokenSnapshot,
        alert_record: AlertRecord,
        inserted_record_ids: set[int],
    ) -> None:
        """Pregunta al strategy router; abre paper trades si pasan risk + sizing."""
        from app.utils.time_utils import utc_now_iso

        candles = snapshot.raw.get("candles") if snapshot.raw else []
        if not candles:
            return  # sin OHLCV no podemos pattern → strategy
        try:
            from app.analyzers.technical_patterns import analyze_ohlcv
            pattern = analyze_ohlcv(candles)
        except Exception:
            logger.exception("analyze_ohlcv failed for %s", snapshot.symbol)
            return

        ctx = StrategyContext(
            snapshot=snapshot,
            candles=candles,
            pattern=pattern,
            pro=None,  # pro analysis ya pasó al score; usar None aquí simplifica
            news_label="no_recent_news",
            news_score=0,
            macro=current_session(),
        )
        try:
            signals = self.strategy_router.route(ctx, self.settings)
        except Exception:
            logger.exception("Strategy router failed for %s", snapshot.symbol)
            return

        if not signals:
            return

        # Evitar duplicados: si ya hay un open trade para (chain, address), skip
        existing_open = [
            p
            for p in self.portfolio_manager.get_open_positions()
            if str(p.get("chain")) == snapshot.chain
            and str(p.get("token_address")) == snapshot.token_address
        ]
        if existing_open:
            return

        balance = self.portfolio_manager.account_balance()

        for signal in signals:
            sizing = calculate_position_size(
                entry=signal.entry,
                stop=signal.stop,
                account_balance=balance,
                risk_pct=self.settings.risk_per_trade_pct,
                direction=signal.direction,
            )
            if sizing.invalid_reason:
                logger.info(
                    "Signal sizing invalid: %s symbol=%s",
                    sizing.invalid_reason,
                    snapshot.symbol,
                )
                continue
            ok, reason = self.risk_manager.check_can_open_trade(
                snapshot.category,
                sizing.risk_pct_actual,
                symbol=snapshot.token_address or snapshot.symbol,
            )
            if not ok:
                logger.info(
                    "Trade blocked by risk manager: %s strategy=%s symbol=%s",
                    reason,
                    signal.strategy_name,
                    snapshot.symbol,
                )
                continue

            # Insertar alert primero (necesitamos alert_id)
            if id(alert_record) not in inserted_record_ids:
                # Phase 3 v2.2.0: copiar strategy_name al alert_record
                alert_record.strategy_name = signal.strategy_name
                alert_id = self.repository.insert_alert(alert_record)
                inserted_record_ids.add(id(alert_record))
            else:
                # ya insertado por una señal previa de este mismo snapshot.
                # solo permitimos 1 trade por snapshot/alert para evitar UNIQUE constraint.
                continue

            now = utc_now_iso()
            trade = {
                "alert_id": int(alert_id),
                "token_id": int(alert_record.token_id),
                "category": snapshot.category,
                "chain": snapshot.chain,
                "token_address": snapshot.token_address,
                "symbol": snapshot.symbol,
                "thesis": f"{signal.strategy_name}: {'; '.join(signal.reasoning[:2])}",
                "readiness_grade": "A" if signal.confidence >= 80 else "B",
                "entry_price": signal.entry,
                "latest_price": signal.entry,
                "stop_loss": signal.stop,
                "take_profit_1": signal.targets[0] if signal.targets else None,
                "take_profit_2": signal.targets[1] if len(signal.targets) > 1 else None,
                "invalidation": f"strategy {signal.strategy_name} signal pierde validez",
                "status": "open",
                "unrealized_return_pct": 0,
                "opened_at": now,
                "updated_at": now,
                "closed_at": None,
                "mfe_pct": 0,
                "mae_pct": 0,
                "original_stop_loss": signal.stop,
                "trailing_active": 0,
                "strategy_name": signal.strategy_name,
                "direction": signal.direction,
                "time_horizon_hours": signal.time_horizon_hours,
                "size_notional": sizing.size_notional,
                "size_units": sizing.size_units,
                "risk_pct": sizing.risk_pct_actual,
                "partial_closed": 0,
                "account_balance_at_open": balance,
                # v2.11.0 — features tecnicas al ENTRY (habilitan el ML, que hoy
                # las recibia NaN). Vienen del TechnicalPattern ya calculado arriba.
                # atr_value = ATR en % (atr_pct): normalizado entre simbolos.
                "rsi_entry": pattern.rsi,
                "atr_value": pattern.atr_pct,
                "macd_value": pattern.macd,
                "macd_signal_value": pattern.macd_signal,
                # v3.12.0 — VWAP al entry (research/ML dataset; ML sigue OFF).
                # None honesto si no hay volumen (forex Yahoo).
                "vwap_dist_pct": pattern.vwap_dist_pct,
                "vwap_week_dist_pct": pattern.vwap_week_dist_pct,
                # v3.12.0 — Hurst + footprint lite al entry (mismo contrato).
                "hurst_entry": pattern.hurst,
                "clv_entry": pattern.candle_clv,
                "candle_strength": pattern.candle_strength,
            }
            created = self.repository.create_paper_trade(trade)
            if created and self.settings.enable_trade_action_reports:
                try:
                    msg = format_trade_opened(snapshot, signal, sizing)
                    self.notifier.send_message(msg)
                except Exception:
                    logger.exception("Trade opened report failed")
            if created:
                paper_trade = self.repository.fetch_paper_trade_by_alert_id(int(alert_id))
                if paper_trade:
                    self._try_prepare_demo_order(paper_trade)
            return  # solo 1 trade por snapshot (la primera signal valida)

    def _record_ml_decision(self, outcome: str) -> None:
        """v2.9.0: contador diario de decisiones ML en bot_state para /ml_status
        (passed/low/blocked). Resetea al cambiar de dia UTC. Soft-fail."""
        try:
            today = utc_now().date().isoformat()
            if self.repository.get_state("ml_stat_date") != today:
                self.repository.set_state("ml_stat_date", today)
                self.repository.set_state("ml_stat_passed", "0")
                self.repository.set_state("ml_stat_low", "0")
                self.repository.set_state("ml_stat_blocked", "0")
            key = f"ml_stat_{outcome}"
            current = int(self.repository.get_state(key, "0") or 0)
            self.repository.set_state(key, str(current + 1))
        except Exception:
            logger.exception("ML decision record fallo; ignoro")

    def _maybe_retrain_ml(self) -> None:
        """v2.9.0: reentrena el ML 1x/dia si hay >= ml_retrain_min_new_trades nuevos
        desde el ultimo entrenamiento. Gate por fecha UTC. Soft-fail total: cualquier
        error no afecta el ciclo. La reversion por degradacion de AUC (>0.05) la
        maneja retrain_if_needed (mantiene el modelo anterior)."""
        if self._ml_predictor is None or not self.settings.enable_ml_predictor:
            return
        today = utc_now().date().isoformat()
        if self._ml_last_retrain_date == today:
            return
        self._ml_last_retrain_date = today
        try:
            from app.learning.ml_dataset_builder import build_ml_dataset

            df = build_ml_dataset(self.settings.sqlite_path, export_csv=False)
            result = self._ml_predictor.retrain_if_needed(
                df, self.settings.ml_retrain_min_new_trades
            )
            logger.info("ML retrain diario: %s", result)
        except Exception:
            logger.exception("ML retrain fallo; soft-fail (modelo anterior intacto)")

    def _maybe_send_daily_summary(self) -> None:
        """v3.1.0 (Fase B p3): 1x/dia, tras la hora de corte (UTC), manda por Telegram
        un resumen del dia (trades cerrados hoy: wins/losses/R neto) + una leccion via
        LLM local si el asesor esta on. Gate por fecha en bot_state (sobrevive
        reinicios). READ-ONLY + soft-fail total: no toca ninguna decision ni orden."""
        if not getattr(self.settings, "enable_daily_summary", False):
            return
        now = utc_now()
        if now.hour < int(getattr(self.settings, "daily_summary_hour_utc", 21)):
            return
        today = now.date().isoformat()
        if self.repository.get_state("daily_summary_last_date") == today:
            return
        try:
            stats = self._today_trade_stats(today)
            message = self._format_daily_summary(today, stats)
            self.notifier.send_message(message)
            self.repository.set_state("daily_summary_last_date", today)
        except Exception:
            logger.exception("Resumen diario fallo; soft-fail (reintenta proximo ciclo)")

    def _today_trade_stats(self, today: str) -> dict:
        """Agrega paper_trades cerrados HOY (UTC, no-artifact): wins/losses/R neto."""
        from app.learning.trade_outcomes import is_artifact, r_multiple

        wins = losses = 0
        net_r = 0.0
        for t in self.repository.fetch_paper_trades(limit=200):
            if not str(t.get("closed_at") or "").startswith(today):
                continue
            if str(t.get("status") or "") == "open" or is_artifact(t):
                continue
            r = r_multiple(t)
            if r is None:
                continue
            net_r += r
            if r > 0:
                wins += 1
            elif r < 0:
                losses += 1
        return {"total": wins + losses, "wins": wins, "losses": losses,
                "net_r": round(net_r, 2)}

    def _format_daily_summary(self, today: str, stats: dict) -> str:
        """Mensaje: numeros (siempre) + leccion LLM opcional (si el asesor esta on)."""
        lines = [
            f"Resumen del dia - {today}",
            f"Trades cerrados: {stats['total']} "
            f"({stats['wins']} ganados, {stats['losses']} perdidos)",
            f"R neto del dia: {stats['net_r']:+.2f}",
        ]
        lesson = None
        try:
            from app.intelligence.reasoner import TradingReasoner

            proc = (
                self.claude_processor
                if hasattr(self.claude_processor, "generate")
                else None
            )
            lesson = TradingReasoner(self.settings, processor=proc).daily_summary(stats)
        except Exception:
            lesson = None
        if lesson:
            lines.append("")
            lines.append(lesson)
        return "\n".join(lines)

    def _maybe_run_continuous_learner(self) -> None:
        """v3.2.0 (Fase C): al cerrar trades, extrae una leccion razonada via LLM
        local y la registra en trade_lessons; si N lecciones comparten clave, PROPONE
        una revision por Telegram (no la aplica). Opt-in OFF (enable_continuous_learner
        + store_trade_lessons), soft-fail total: no toca ejecucion, gate ni order_send."""
        if not getattr(self.settings, "enable_continuous_learner", False):
            return
        try:
            from app.intelligence.reasoner import TradingReasoner
            from app.learning.continuous_learner import ContinuousLearner

            proc = (
                self.claude_processor
                if hasattr(self.claude_processor, "generate")
                else None
            )
            reasoner = TradingReasoner(self.settings, processor=proc)
            summary = ContinuousLearner(
                self.settings,
                self.repository,
                reasoner=reasoner,
                notifier=self.notifier,
            ).run()
            if summary.lessons_created or summary.proposals_made:
                logger.info("ContinuousLearner: %s", summary)
        except Exception:
            logger.exception("ContinuousLearner fallo; soft-fail (no afecta el ciclo)")

    def _maybe_record_exit_shadow(self) -> None:
        """v3.4.0: cada ciclo registra el R no-realizado de los trades abiertos en
        trade_r_samples (camino de R) para medir si un trailing mejoraria las salidas
        (/exit_analysis). SOLO registro: no toca ninguna salida ni ejecucion. Opt-in OFF,
        soft-fail. Poda 1x/dia (gate por fecha) las muestras de trades CERRADOS hace > 7
        dias — nunca de abiertos, para no decapitar el camino de trades longevos."""
        if not getattr(self.settings, "enable_exit_shadow", False):
            return
        try:
            from datetime import timedelta

            from app.learning.exit_shadow import record_open_trade_samples
            from app.utils.time_utils import utc_now, utc_now_iso

            open_trades = self.repository.fetch_open_positions_full()
            record_open_trade_samples(self.repository, open_trades, utc_now_iso())

            today = utc_now().date().isoformat()
            if self.repository.get_state("r_samples_last_prune") != today:
                cutoff = (utc_now() - timedelta(days=7)).isoformat()
                deleted = self.repository.prune_r_samples(cutoff)
                self.repository.set_state("r_samples_last_prune", today)
                if deleted:
                    logger.info("exit shadow: podadas %s muestras viejas", deleted)
        except Exception:
            logger.exception("exit shadow capture fallo; soft-fail")

    def _ml_gate(self, paper_trade: dict) -> tuple[bool, bool]:
        """v2.9.0: señal ML adicional para el order_send a demo. Devuelve
        (allow, low_confidence). Soft-fail: si el ML no esta activo/entrenado, no
        tiene muestra suficiente (n<ml_gate_min_samples), o falla, devuelve
        (True, False) = SIN CAMBIOS. SOLO filtra hacia abajo: se invoca despues de
        que las reglas aprobaron, asi que jamas habilita un order_send bloqueado."""
        pred = self._ml_predictor
        if pred is None or not self.settings.enable_ml_predictor:
            return True, False
        try:
            from app.learning.feature_extractor import extract_features
            from app.learning.ml_dataset_builder import build_live_features
            from app.learning.ml_predictor import ml_gate_decision, should_consult_ml

            if not should_consult_ml(pred, self.settings.ml_gate_min_samples):
                return True, False  # ML dormido (muestra insuficiente): sin cambios

            macro = self.repository.fetch_latest_macro_snapshot()
            alert_feats: list[str] = []
            detail = self.repository.fetch_alert_full_detail(
                int(paper_trade.get("alert_id") or -1)
            )
            if detail and detail.get("alert"):
                alert_feats = extract_features(detail["alert"])
            features = build_live_features(paper_trade, macro, alert_feats)
            conf = pred.predict(features)
            allow, low, reason = ml_gate_decision(
                conf, self.settings.ml_conf_pass, self.settings.ml_conf_low
            )
            if not allow:
                logger.info(
                    "ML gate: paper-only strategy=%s symbol=%s %s",
                    paper_trade.get("strategy_name"), paper_trade.get("symbol"), reason,
                )
            elif low:
                logger.info(
                    "ML gate: lot reducido strategy=%s symbol=%s %s",
                    paper_trade.get("strategy_name"), paper_trade.get("symbol"), reason,
                )
            self._record_ml_decision(
                "blocked" if not allow else ("low" if low else "passed")
            )
            return allow, low
        except Exception:
            logger.exception("ML gate fallo; soft-fail (sin cambios)")
            return True, False

    def _llm_ensemble_gate(self, paper_trade: dict) -> bool:
        """v3.0.0: veto del ensemble LLM (modelo primario + 2da opinion). Devuelve
        True=proceder, False=veto (el trade baja a paper-only). Soft-fail: si el flag
        esta off, no hay Ollama, o algo falla -> True (sin cambios). DOWNWARD-ONLY: se
        invoca DESPUES de que reglas + gates aprobaron, asi que jamas habilita un
        order_send bloqueado; lo unico que puede hacer es vetar."""
        if not getattr(self.settings, "enable_llm_ensemble", False):
            return True
        try:
            from app.intelligence.ensemble_gate import ensemble_veto

            macro = self.repository.fetch_latest_macro_snapshot() or {}
            context = {
                "symbol": paper_trade.get("symbol"),
                "direction": paper_trade.get("direction"),
                "strategy_name": paper_trade.get("strategy_name"),
                "entry": paper_trade.get("entry_price"),
                "stop": paper_trade.get("stop_loss"),
                "tp": paper_trade.get("take_profit_1"),
                "session": session_of(paper_trade.get("opened_at")),
                "rsi": paper_trade.get("rsi_entry"),
                "atr": paper_trade.get("atr_value"),
                "vix": macro.get("vix_value"),
            }
            veto, reason = ensemble_veto(self.settings, context, self.claude_processor)
            if veto:
                logger.info(
                    "LLM ensemble: paper-only (veto) strategy=%s symbol=%s %s",
                    paper_trade.get("strategy_name"),
                    paper_trade.get("symbol"),
                    reason,
                )
                return False
            return True
        except Exception:
            logger.exception("LLM ensemble gate fallo; soft-fail (sin cambios)")
            return True

    def _calendar_gate(self, paper_trade: dict) -> bool:
        """v3.5.0: True = permitir order_send. Bloquea si hay un evento high-impact de
        la(s) moneda(s) del simbolo dentro de calendar_buffer_minutes. SOLO baja a
        paper-only (downward-only); soft-fail = permitir. Requiere ambos flags
        (enable_calendar_gate + enable_economic_calendar, que llena la tabla)."""
        if not getattr(self.settings, "enable_calendar_gate", False):
            return True
        if not getattr(self.settings, "enable_economic_calendar", False):
            return True  # sin colector no hay eventos: el gate seria un no-op enganoso
        try:
            from app.intelligence.calendar_filter import is_safe_window

            safe, reason = is_safe_window(
                str(paper_trade.get("symbol") or ""),
                utc_now(),
                self.repository,
                int(getattr(self.settings, "calendar_buffer_minutes", 30)),
            )
            if not safe:
                logger.info(
                    "Calendar gate: paper-only symbol=%s reason=%s",
                    paper_trade.get("symbol"), reason,
                )
            return safe
        except Exception:
            logger.exception("Calendar gate fallo; soft-fail -> permitir")
            return True

    def _usd_exposure_gate(self, paper_trade: dict) -> bool:
        """v3.5.0: True = permitir order_send. Bloquea si abrir el candidato dejaria la
        exposicion neta USD (de los abiertos YA ejecutados a MT5) mas alla del cap.
        SOLO bloquea concentracion adicional (downward-only); soft-fail = permitir."""
        if not getattr(self.settings, "enable_usd_exposure_cap", False):
            return True
        try:
            from app.risk.exposure import would_exceed_cap

            open_executed = [
                t for t in self.repository.fetch_open_positions_full()
                if str(t.get("category") or "") == "forex"
                and t.get("id") is not None
                and self.repository.has_successful_demo_order(int(t["id"]))
            ]
            blocked, reason = would_exceed_cap(
                open_executed,
                str(paper_trade.get("symbol") or ""),
                str(paper_trade.get("direction") or "long"),
                int(getattr(self.settings, "max_net_usd_exposure", 3)),
            )
            if blocked:
                logger.info(
                    "USD exposure gate: paper-only symbol=%s reason=%s",
                    paper_trade.get("symbol"), reason,
                )
            return not blocked
        except Exception:
            logger.exception("USD exposure gate fallo; soft-fail -> permitir")
            return True

    def _regime_gate(self, paper_trade: dict) -> bool:
        """v3.8.0: True = permitir order_send. Baja a paper si el trade va CONTRA
        el regimen D1 del simbolo (long en regimen 'down' / short en 'up'). Aligned,
        'flat' o sin historia D1 suficiente -> permitir. Downward-only, soft-fail.
        Solo forex/gold (lo unico que ejecuta a demo). Defensivo: NO crea edge,
        deja de pelear la tendencia (el slicing mostro longs -0.57R vs shorts +1.29R)."""
        if not getattr(self.settings, "enable_regime_gate", False):
            return True
        if str(paper_trade.get("category") or "") not in ("forex", "gold"):
            return True
        try:
            from app.brokers.mt5_symbol_map import yahoo_to_mt5
            from app.intelligence.regime_filter import (
                SMA_TREND_PERIOD,
                TREND_SLOPE_LOOKBACK,
                classify,
            )

            raw = str(paper_trade.get("symbol") or "")
            mt5_sym = yahoo_to_mt5(
                raw, getattr(self.settings, "mt5_broker_profile", "icmarkets")
            ) or raw.upper().replace("=X", "")
            candles = self._d1_candles_for_regime(mt5_sym)
            if len(candles) < SMA_TREND_PERIOD + TREND_SLOPE_LOOKBACK:
                return True  # sin historia D1 suficiente -> no gate (soft)
            regime = classify(candles).regime_trend
            direction = str(paper_trade.get("direction") or "long")
            counter = (regime == "up" and direction == "short") or (
                regime == "down" and direction == "long"
            )
            if counter:
                logger.info(
                    "Regime gate: paper-only symbol=%s dir=%s regime=%s",
                    raw, direction, regime,
                )
                return False
            return True
        except Exception:
            logger.exception("Regime gate fallo; soft-fail -> permitir")
            return True

    def _vwap_gate(self, paper_trade: dict) -> bool:
        """v3.12.0: True = permitir order_send. Baja a paper si el trade pelea
        el VWAP SEMANAL del simbolo: long con precio claramente BAJO el VWAP /
        short claramente SOBRE (umbral vwap_gate_min_dist_pct). Mismo molde que
        el regime gate: downward-only, opt-in OFF, soft-fail, solo forex/gold.
        VWAP del cache D1 de MT5 (tick_volume) — Yahoo-forex no trae volumen,
        por eso NO se usan los campos vwap_* persistidos del trade aca.
        Defensivo: NO crea edge; no pelear el lado de valor de la semana."""
        if not getattr(self.settings, "enable_vwap_gate", False):
            return True
        if str(paper_trade.get("category") or "") not in ("forex", "gold"):
            return True
        try:
            from app.brokers.mt5_symbol_map import yahoo_to_mt5
            from app.indicators.vwap import weekly_vwap

            raw = str(paper_trade.get("symbol") or "")
            mt5_sym = yahoo_to_mt5(
                raw, getattr(self.settings, "mt5_broker_profile", "icmarkets")
            ) or raw.upper().replace("=X", "")
            candles = self._d1_candles_for_regime(mt5_sym)  # guard de frescura incluido
            if not candles:
                return True  # sin cache D1 -> no gate (soft)
            reading = weekly_vwap(candles)
            if (
                reading.vwap is None
                or reading.distance_pct is None
                or reading.bars_used < 2
            ):
                return True  # sin volumen / semana recien empezada -> soft-allow
            threshold = float(
                getattr(self.settings, "vwap_gate_min_dist_pct", 0.5) or 0.0
            )
            direction = str(paper_trade.get("direction") or "long")
            fighting = (
                direction == "long" and reading.distance_pct < -threshold
            ) or (direction == "short" and reading.distance_pct > threshold)
            if fighting:
                logger.info(
                    "VWAP gate: paper-only symbol=%s dir=%s dist_semanal=%.2f%%",
                    raw, direction, reading.distance_pct,
                )
                return False
            return True
        except Exception:
            logger.exception("VWAP gate fallo; soft-fail -> permitir")
            return True

    def _d1_candles_for_regime(self, mt5_symbol: str) -> list[dict]:
        """Velas D1 del cache historico (mt5_historical_cache) para clasificar el
        regimen. Vacio si no hay -> el gate hace soft-fail (permite). El cache se
        refresca con el stock/historical loader o el walk-forward."""
        try:
            candles = self.repository.fetch_mt5_cache_window(
                mt5_symbol, 1440, 0, 9_999_999_999
            )
        except Exception:
            return []
        # M1 fix: guard de frescura. El cache D1 NO lo refresca el loop vivo (solo los
        # loaders de backtest/walk-forward). Si la ultima vela es > 10 dias vieja,
        # clasificar el regimen sobre ella esta mal -> tratar como sin historia (el gate
        # hace soft-allow) y avisar, en vez de gatear con data caduca.
        max_age_days = 10
        if candles:
            try:
                last_t = float(candles[-1].get("time") or 0)
                age_days = (utc_now().timestamp() - last_t) / 86400.0
                if age_days > max_age_days:
                    logger.warning(
                        "Regime gate: cache D1 de %s stale (%.0f dias) -> soft-allow; "
                        "refresca el cache (loader/walk-forward)",
                        mt5_symbol, age_days,
                    )
                    return []
            except Exception:
                pass
        return candles

    def _try_prepare_demo_order(self, paper_trade: dict) -> None:
        """Phase 5: create a pending MT5 demo order request.

        Phase 5.5 v2.5.4: si enable_auto_confirm_demo=True, la request se
        ejecuta automáticamente vía _auto_execute_demo_request en lugar de
        esperar /confirm_demo_trade por Telegram. Real-money sigue bloqueado.

        v3.13.0: con ENABLE_AI_AGENT=true, los candidatos forex/gold los decide el
        agente IA (_ai_agent_path) en lugar de la cadena de filtros de edge.
        """
        if getattr(self.settings, "enable_ai_agent", False) and str(
            paper_trade.get("category") or ""
        ).lower() in {"forex", "gold"}:
            self._ai_agent_path(paper_trade)
            return
        if not self.settings.enable_mt5_demo_trading:
            return
        if not self.settings.demo_order_require_confirmation:
            logger.warning("Demo trading requires manual confirmation; skipping request")
            return
        if self.repository.get_state("demo_trading_halted", "false") == "true":
            return
        if str(paper_trade.get("category") or "").lower() not in {"forex", "gold"}:
            return

        # v2.7.0 promotion gate: no manda order_send a MT5 si la estrategia tiene
        # edge negativo PROBADO (avg_r<=umbral con n>=min_samples). El paper_trade
        # ya quedó creado: queda en shadow/paper-only. Real-money sigue bloqueado.
        # v2.8.0: si enable_sliced_promotion_gate, además chequea el slice (sesión +
        # dirección del trade). El slicing solo puede mover a SHADOW, nunca promover.
        if self.settings.enable_strategy_promotion_gate:
            strat = str(paper_trade.get("strategy_name") or "")
            cat = str(paper_trade.get("category") or "")
            perf = self.repository.fetch_strategy_performance_for(strat, cat)
            if self.settings.enable_sliced_promotion_gate:
                sess = session_of(paper_trade.get("opened_at"))
                direction = (
                    "short"
                    if str(paper_trade.get("direction") or "long") == "short"
                    else "long"
                )
                slice_rows = self.repository.fetch_sliced_performance_for(
                    strat, cat, [sess, direction]
                )
                ok_live, gate_reason = should_execute_live_sliced(
                    strat,
                    cat,
                    perf,
                    slice_rows,
                    self.settings.strategy_promotion_min_samples,
                    self.settings.strategy_promotion_min_expectancy_r,
                )
            else:
                ok_live, gate_reason = should_execute_live(
                    strat,
                    cat,
                    perf,
                    self.settings.strategy_promotion_min_samples,
                    self.settings.strategy_promotion_min_expectancy_r,
                )
            if not ok_live:
                logger.info(
                    "Promotion gate: paper-only (sin order_send MT5) strategy=%s symbol=%s reason=%s",
                    strat,
                    paper_trade.get("symbol"),
                    gate_reason,
                )
                return

        # v2.9.0 ML gate: señal adicional. Soft-fail; SOLO filtra hacia abajo.
        ml_allow, ml_low = self._ml_gate(paper_trade)
        if not ml_allow:
            return  # ML manda a paper-only (sin order_send a MT5)

        # v3.0.0 LLM ensemble veto: dos modelos buscan red flags en el trade ya
        # aprobado. Soft-fail; SOLO veta (downward-only). No toca mt5_demo_trader.
        if not self._llm_ensemble_gate(paper_trade):
            return  # el ensemble veta -> paper-only (sin order_send a MT5)

        # v3.5.0 calendar gate: no ejecutar a MT5 con un evento high-impact de la
        # moneda del par dentro del buffer (el 10-jun abrio USDCAD 18 min antes del
        # BOC que estaba en su propia DB). Downward-only + soft-fail.
        if not self._calendar_gate(paper_trade):
            return  # evento cerca -> paper-only (sin order_send a MT5)

        # v3.5.0 cap de exposicion USD: no concentrar mas la apuesta al dolar (el
        # 10-jun 7 posiciones eran 1 sola apuesta long-USD y un movimiento las barrio
        # juntas). Downward-only + soft-fail.
        if not self._usd_exposure_gate(paper_trade):
            return  # concentraria la apuesta USD -> paper-only (sin order_send)

        # v3.8.0: regime gate. Si el trade pelea la tendencia D1 (long en 'down' /
        # short en 'up'), queda paper-only. Defensivo: el slicing mostro que los
        # longs sangran contra el regimen. Downward-only + soft-fail.
        if not self._regime_gate(paper_trade):
            return  # contra-regimen -> paper-only (sin order_send a MT5)

        # v3.12.0: VWAP gate. Si el trade pelea el VWAP semanal (long claramente
        # bajo / short claramente sobre), queda paper-only. Downward-only + soft-fail.
        if not self._vwap_gate(paper_trade):
            return  # pelea el VWAP semanal -> paper-only (sin order_send a MT5)

        from app.brokers.mt5_demo_trader import MT5DemoTrader

        trader = MT5DemoTrader(self.settings, self.mt5_reader)
        open_positions = 0
        try:
            open_positions = len(trader.positions())
            result = trader.prepare_from_paper_trade(paper_trade, open_positions)
        except Exception:
            logger.exception("Demo order preparation failed")
            return
        if not result.ok or result.draft is None:
            logger.info(
                "Demo order candidate skipped: %s symbol=%s",
                result.reason,
                paper_trade.get("symbol"),
            )
            return

        now = utc_now()
        expires_at = now + timedelta(
            minutes=self.settings.demo_trade_request_ttl_minutes
        )
        draft = result.draft
        if ml_low:
            halved = round(draft.volume / 2.0, 2)
            if halved >= 0.01:
                logger.info(
                    "ML low confidence: reduzco lot %.2f -> %.2f", draft.volume, halved
                )
                # v3.13.0 fix: DemoOrderDraft es frozen -> `draft.volume = x` lanzaba
                # FrozenInstanceError (latente: el ML esta OFF).
                from dataclasses import replace as _dc_replace

                draft = _dc_replace(draft, volume=halved)
        request_id = self.repository.create_demo_trade_request(
            {
                "paper_trade_id": paper_trade["id"],
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

        # Phase 5.5 v2.5.4: auto-confirm path (opt-in)
        if self.settings.enable_auto_confirm_demo:
            try:
                self._auto_execute_demo_request(trader, request_id, open_positions)
            except Exception:
                logger.exception(
                    "Auto-confirm demo order failed for request %s", request_id
                )
            return

        # Manual confirm path (Phase 5 original)
        try:
            self.notifier.send_message(
                "Orden demo MT5 lista para confirmar\n"
                f"ID: {request_id}\n"
                f"{draft.request_summary}\n"
                f"Estrategia: {draft.strategy_name or '?'}\n"
                f"Confirmar: /confirm_demo_trade {request_id}\n"
                f"Expira en {self.settings.demo_trade_request_ttl_minutes} min."
            )
        except Exception:
            logger.exception("Demo order request notification failed")

    def _auto_execute_demo_request(
        self,
        trader,
        request_id: int,
        open_positions: int,
        magic: int | None = None,
        comment: str | None = None,
        label: str = "Auto-orden demo",
    ) -> None:
        """Phase 5.5 v2.5.4: ejecuta send_prepared_request sin pasar por Telegram.

        Solo se invoca cuando enable_auto_confirm_demo=True. Validaciones
        demo-only y mandatory SL siguen aplicando dentro de mt5_demo_trader.
        Real-money trading sigue bloqueado por enable_real_trading=False.
        v3.13.0: el agente IA lo usa con su magic/comentario/etiqueta propios.
        """
        request = self.repository.fetch_demo_trade_request(request_id)
        if not request:
            logger.error(
                "Auto-confirm: request #%s not found after creation", request_id
            )
            return
        try:
            if magic is None and comment is None:
                result = trader.send_prepared_request(request, open_positions)
            else:
                result = trader.send_prepared_request(
                    request, open_positions, magic=magic, comment=comment
                )
        except Exception:
            logger.exception(
                "Auto-confirm send_prepared_request raised for #%s", request_id
            )
            return

        now_iso = utc_now().isoformat()
        try:
            self.repository.update_demo_trade_request(
                request_id,
                {
                    "status": result.status,
                    "confirmed_at": now_iso,
                    "sent_at": now_iso if result.status == "sent" else None,
                    "result_message": (result.result_summary or result.reason),
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
                    "result_summary": (result.result_summary or result.reason),
                    "sent_at": now_iso,
                }
            )
            # v2.6.8: Corregir paper_trade.size_notional con notional MT5 real.
            # Sin esto, /aprendizaje y realized_pnl_today usan el sizing teórico
            # (basado en ACCOUNT_STARTING_BALANCE=1M) en vez del 0.1 lot real,
            # inflando stats 100-1000× y disparando kill switch falsos.
            if result.ok and result.price:
                self._correct_paper_trade_notional(
                    trader,
                    paper_trade_id=int(request["paper_trade_id"]),
                    symbol=str(request["symbol"]),
                    volume=float(request["volume"]),
                    entry_price=float(result.price),
                )
        except Exception:
            logger.exception(
                "Auto-confirm DB persist failed for request #%s", request_id
            )

        try:
            volume_str = f"{float(request['volume']):g}"
            if result.ok:
                self.notifier.send_message(
                    f"{label} enviada #{request_id}\n"
                    f"{str(request['direction']).upper()} {request['symbol']} "
                    f"{volume_str} lot\n"
                    f"Order: {result.order_ticket or '?'} | "
                    f"Deal: {result.deal_ticket or '?'}\n"
                    f"Retcode: {result.retcode}\n"
                    f"Estrategia: {request.get('strategy_name') or '?'}"
                )
            else:
                self.notifier.send_message(
                    f"{label} FALLIDA #{request_id}\n"
                    f"{str(request['direction']).upper()} {request['symbol']}\n"
                    f"Motivo: {result.reason}\n"
                    f"Detalle: {result.result_summary or 'sin detalle'}"
                )
        except Exception:
            logger.exception(
                "Auto-confirm Telegram notification failed for #%s", request_id
            )

    # ------------------------------------------------------------------ #
    # v3.13.0 — Agente IA en sandbox demo
    # ------------------------------------------------------------------ #
    def _ai_agent_path(self, paper_trade: dict) -> None:
        """Decide EJECUTAR o NO OPERAR un candidato forex/gold y, si ejecuta y
        ningún límite lo frena, manda la orden a MT5 demo con magic propio.
        Registra SIEMPRE la decisión (aprende de todos los candidatos). Soft-fail:
        cualquier error = sin orden, el bot sigue."""
        try:
            from app.ai_agent.agent import AiAgent
            from app.ai_agent.features import build_features

            if paper_trade.get("id") is None:
                return
            agent = AiAgent(self.settings, self.repository)
            regime, vwap_week = self._ai_agent_context(paper_trade)
            x = build_features(paper_trade, regime, vwap_week)
            model = agent.load_model()
            mean, sd, sampled, intended = agent.decide(model, x, int(paper_trade["id"]))
            block = None
            if intended == "execute":
                block = self._ai_agent_block_reason(agent, paper_trade)
            decision_id = self.repository.create_ai_agent_decision(
                {
                    "paper_trade_id": int(paper_trade["id"]),
                    "created_at": utc_now().isoformat(),
                    "symbol": paper_trade.get("symbol"),
                    "category": paper_trade.get("category"),
                    "strategy_name": paper_trade.get("strategy_name"),
                    "direction": paper_trade.get("direction"),
                    "features_json": json.dumps(x),
                    "mean_r": mean,
                    "std_r": sd,
                    "sampled_r": sampled,
                    "intended": intended,
                    "executed": False,
                    "block_reason": block,
                    "model_n": model.n,
                }
            )
            logger.info(
                "Agente IA: %s %s %s -> %s (R esperado %+.2f ± %.2f, muestra %+.2f)%s",
                paper_trade.get("strategy_name"), paper_trade.get("symbol"),
                paper_trade.get("direction"), intended, mean, sd, sampled,
                f" BLOQUEADO: {block}" if block else "",
            )
            if decision_id is None or intended != "execute" or block:
                return
            try:
                request_id, ok, reason = self._ai_agent_execute(paper_trade)
            except Exception as exc:
                logger.exception("Agente IA: la ejecución falló; sin orden")
                request_id, ok, reason = None, False, f"error: {type(exc).__name__}"
            self.repository.update_ai_agent_decision(
                decision_id,
                {"executed": int(ok), "demo_request_id": request_id,
                 "block_reason": None if ok else reason},
            )
        except Exception:
            logger.exception("Agente IA fallo; soft-fail (sin orden)")

    def _ai_agent_context(self, paper_trade: dict) -> tuple[str | None, float | None]:
        """(régimen D1 'up'/'down'/'flat', distancia % al VWAP semanal) del cache D1
        de MT5, igual que los gates. (None, None) si no hay data. Soft-fail."""
        try:
            from app.brokers.mt5_symbol_map import yahoo_to_mt5
            from app.indicators.vwap import weekly_vwap
            from app.intelligence.regime_filter import (
                SMA_TREND_PERIOD,
                TREND_SLOPE_LOOKBACK,
                classify,
            )

            raw = str(paper_trade.get("symbol") or "")
            mt5_sym = yahoo_to_mt5(
                raw, getattr(self.settings, "mt5_broker_profile", "icmarkets")
            ) or raw.upper().replace("=X", "")
            candles = self._d1_candles_for_regime(mt5_sym)
            regime = None
            if len(candles) >= SMA_TREND_PERIOD + TREND_SLOPE_LOOKBACK:
                regime = classify(candles).regime_trend
            vwap = None
            if candles:
                reading = weekly_vwap(candles)
                if reading.distance_pct is not None and reading.bars_used >= 2:
                    vwap = float(reading.distance_pct)
            return regime, vwap
        except Exception:
            logger.exception("Agente IA: contexto D1 fallo; sigue sin régimen/VWAP")
            return None, None

    def _ai_agent_block_reason(self, agent, paper_trade: dict) -> str | None:
        """Límites que frenan una ejecución del agente (riesgo, no edge)."""
        if not self.settings.enable_mt5_demo_trading:
            return "ENABLE_MT5_DEMO_TRADING=false (decide en sombra)"
        if self.repository.get_state("demo_trading_halted", "false") == "true":
            return "demo trading en halt"
        own = agent.guardrail_block()
        if own:
            return own
        if not self._calendar_gate(paper_trade):
            return "evento económico de alto impacto cerca"
        if not self._usd_exposure_gate(paper_trade):
            return "cap de exposición USD"
        return None

    def _ai_agent_execute(self, paper_trade: dict) -> tuple[int | None, bool, str | None]:
        """Prepara (lote achicado al riesgo del agente) y envía con AGENT_MAGIC."""
        from app.brokers.mt5_demo_trader import MT5DemoTrader

        trader = MT5DemoTrader(self.settings, self.mt5_reader)
        open_positions = len(trader.positions())
        result = trader.prepare_from_paper_trade(
            paper_trade, open_positions,
            risk_cap_pct=float(self.settings.ai_agent_risk_pct),
        )
        if not result.ok or result.draft is None:
            return None, False, f"preparación: {result.reason}"
        draft = result.draft
        now = utc_now()
        request_id = self.repository.create_demo_trade_request(
            {
                "paper_trade_id": paper_trade["id"],
                "symbol": draft.symbol,
                "direction": draft.direction,
                "volume": draft.volume,
                "entry_price": draft.entry_price,
                "stop_loss": draft.stop_loss,
                "take_profit": draft.take_profit,
                "risk_pct": draft.risk_pct,
                "strategy_name": f"ai_agent/{draft.strategy_name or '?'}",
                "status": "pending",
                "reason": f"Agente IA: {draft.reason}",
                "request_summary": draft.request_summary,
                "created_at": now.isoformat(),
                "expires_at": (
                    now + timedelta(minutes=self.settings.demo_trade_request_ttl_minutes)
                ).isoformat(),
            }
        )
        self._auto_execute_demo_request(
            trader, request_id, open_positions,
            magic=MT5DemoTrader.AGENT_MAGIC, comment="TradingAlertAI agent",
            label="Agente IA: orden demo",
        )
        request = self.repository.fetch_demo_trade_request(request_id) or {}
        ok = str(request.get("status") or "") == "sent"
        return request_id, ok, None if ok else f"envío: {request.get('result_message')}"

    def _maybe_ai_agent_learn(self) -> None:
        """v3.13.0: el agente aprende de los candidatos cuyo paper trade cerró.
        Corre cada ciclo (barato: solo decisiones pendientes). Soft-fail."""
        if not getattr(self.settings, "enable_ai_agent", False):
            return
        try:
            from app.ai_agent.agent import AiAgent

            learned = AiAgent(self.settings, self.repository).learn()
            if learned:
                logger.info("Agente IA: aprendió de %d trades cerrados", learned)
        except Exception:
            logger.exception("Agente IA: aprendizaje fallo; soft-fail")

    def _correct_paper_trade_notional(
        self,
        trader,
        paper_trade_id: int,
        symbol: str,
        volume: float,
        entry_price: float,
    ) -> None:
        """v2.6.8: Después de demo_order exitoso, actualiza paper_trade.size_notional
        con el notional MT5 real (volume × contract_size × price si quote=USD).

        Esto reemplaza el sizing teórico del position_sizer (basado en
        ACCOUNT_STARTING_BALANCE=1M) por la exposure verdadera de MT5 demo
        (0.1 lot × contract × price ≈ $10-50k). Crítico para que
        realized_pnl_today reporte drawdown real, no 100-1000× inflado.

        Soft-fail: si MT5 no responde con symbol_info, no actualiza
        (paper_trade queda con sizing teórico, pero no crashea).
        """
        try:
            actual_notional = trader.compute_actual_notional_usd(
                symbol, volume, entry_price
            )
            if actual_notional is None or actual_notional <= 0:
                logger.debug(
                    "v2.6.8: compute_actual_notional_usd returned None/zero "
                    "for paper_trade=%s symbol=%s — keeping theoretical",
                    paper_trade_id, symbol,
                )
                return
            actual_units = trader.actual_units(symbol, volume)
            updates: dict[str, Any] = {"size_notional": actual_notional}
            if actual_units is not None and actual_units > 0:
                updates["size_units"] = actual_units
            self.repository.update_paper_trade(paper_trade_id, updates)
            logger.info(
                "v2.6.8: corrected paper_trade=%s size_notional -> %.2f USD "
                "(MT5 actual via volume=%g × contract × price=%g)",
                paper_trade_id, actual_notional, volume, entry_price,
            )
        except Exception:
            logger.exception(
                "v2.6.8: failed to correct paper_trade=%s notional",
                paper_trade_id,
            )
