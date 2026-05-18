import logging
import time

from app.alerts.alert_formatter import format_grouped_telegram_alert
from app.alerts.telegram_notifier import TelegramNotifier
from app.analyzers.alert_decision_engine import (
    ALERT_PRIORITY,
    candidate_for_security_check,
    choose_primary_alert,
    security_event_types,
    should_send_alert,
)
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
from app.collectors.dexscreener_collector import DexScreenerCollector
from app.collectors.geckoterminal_collector import GeckoTerminalCollector
from app.collectors.goplus_collector import GoPlusCollector
from app.collectors.news_collector import NewsCollector
from app.collectors.sec_collector import SECFilingsCollector
from app.collectors.stock_collector import StockCollector
from app.config.settings import Settings
from app.database.db import init_db
from app.database.models import AlertRecord, SecuritySummary, TokenSnapshot
from app.database.repository import Repository
from app.learning.training_engine import run_learning_cycle
from app.utils.dedup import should_send_deduped_alert
from app.utils.obsidian_memory import (
    write_daily_memory_if_needed,
    write_weekly_report_if_needed,
)
from app.utils.time_utils import minutes_ago


logger = logging.getLogger(__name__)


class TradingAlertJob:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        init_db(settings.sqlite_path)
        self.repository = Repository(settings.sqlite_path)
        self.dexscreener = DexScreenerCollector(settings)
        self.geckoterminal = GeckoTerminalCollector(settings)
        self.stocks = StockCollector(settings)
        self.news = NewsCollector(settings)
        self.sec = SECFilingsCollector(settings)
        self.goplus = GoPlusCollector(settings)
        self.notifier = TelegramNotifier(settings)
        self.assistant = TelegramAssistantPoller(
            settings,
            self.repository,
            self.notifier,
        )

    def run_forever(self) -> None:
        logger.info("Trading Alert AI started. Database: %s", self.settings.sqlite_path)
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
        handled = self.assistant.process_updates()
        if handled:
            logger.info("Telegram assistant handled %s message(s)", handled)

        snapshots = self._limit_snapshots(self._collect_snapshots())
        logger.info("Collected %s market snapshots", len(snapshots))

        records: list[AlertRecord] = []
        send_candidates: list[AlertRecord] = []
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
            intel_reasons, intel_rank_bonus, used_chart, used_sec = self._market_intelligence(
                snapshot,
                allow_chart,
                allow_sec,
                security,
            )
            if used_chart:
                chart_analyses += 1
            if used_sec:
                sec_analyses += 1
            events, event_reasons = self._detect_events(snapshot, previous, security)
            alert_type = choose_primary_alert(events)
            reasons = self._unique_reasons(
                event_reasons
                + intel_reasons
                + estimate.reasons
                + security_reasons(security)
                + score_result.reasons
            )

            token_id = self.repository.upsert_token(
                snapshot,
                score_result.score,
                score_result.risk_level,
                estimate,
            )
            if self.settings.enable_price_snapshots and snapshot.price:
                try:
                    self.repository.insert_price_snapshot(snapshot, token_id)
                except Exception:
                    logger.exception("Failed to insert price snapshot")
            self.repository.save_security_check(
                snapshot.chain, snapshot.token_address, security
            )

            should_send = should_send_alert(
                score_result.score,
                score_result.critical_risk,
                estimate,
                self.settings,
                snapshot.category,
            )

            alert_record = AlertRecord(
                token_id=token_id,
                alert_type=alert_type,
                snapshot=snapshot,
                app_version=self.settings.app_version,
                category=snapshot.category,
                score=score_result.score,
                risk_level=score_result.risk_level,
                reasons=reasons,
                security=security,
                estimate=estimate,
                intel_rank_bonus=intel_rank_bonus,
                sent_to_telegram=False,
            )
            records.append(alert_record)

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
                    score_result.score,
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
            self.repository.insert_alert(record)
        write_daily_memory_if_needed(
            self.settings,
            self.repository,
            records,
            sent_count,
        )
        if self.settings.enable_learning_engine:
            learning = run_learning_cycle(self.settings, self.repository)
            logger.info("Learning cycle complete. %s", learning.summary)

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

        if self.settings.enable_weekly_obsidian_report:
            try:
                write_weekly_report_if_needed(self.settings, self.repository)
            except Exception:
                logger.exception("Failed to write weekly Obsidian report")

        logger.info("Monitoring cycle complete. Telegram alerts sent: %s", sent_count)

    def _collect_snapshots(self) -> list[TokenSnapshot]:
        snapshots: list[TokenSnapshot] = []
        for collector_name, collector in (
            ("DEX Screener", self.dexscreener),
            ("GeckoTerminal", self.geckoterminal),
            ("Stocks", self.stocks),
        ):
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
        categories = ("memecoin", "stock")
        daily_caps = {
            "memecoin": self.settings.memecoin_max_alerts_per_24h,
            "stock": self.settings.stock_max_alerts_per_24h,
        }
        run_caps = {
            "memecoin": self.settings.memecoin_max_alerts_per_run,
            "stock": self.settings.stock_max_alerts_per_run,
        }

        ranked = sorted(candidates, key=self._alert_rank, reverse=True)
        for category in categories:
            sent_last_window = self.repository.sent_alert_count(
                category,
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
                record for record in ranked if record.category == category
            ][:slots]
            if not category_candidates:
                continue
            if sent_count >= self.settings.max_alerts_per_run:
                return sent_count

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
            rank_bonus += pro.score * 1.2
            reasons.append(
                f"IA Pro: {pro.label}, sesgo {pro.bias}, confianza {pro.confidence}/100."
            )
            reasons.append(f"Setup: {pro.setup}.")
            reasons.extend(pro.reasons[:3])
            reasons.extend([f"Riesgo pro: {risk}" for risk in pro.risks[:2]])

        return reasons[:12], rank_bonus, used_chart, used_sec

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
        ordered_memecoins = sorted(memecoins, key=self._snapshot_priority, reverse=True)
        ordered_stocks = sorted(stocks, key=self._snapshot_priority, reverse=True)
        limit = max(self.settings.max_snapshots_per_run, 1)
        if len(ordered_memecoins) > limit:
            logger.info(
                "Limiting memecoin snapshots from %s to %s for this cycle",
                len(ordered_memecoins),
                limit,
            )
        return ordered_memecoins[:limit] + ordered_stocks

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
