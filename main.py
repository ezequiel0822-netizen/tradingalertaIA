import argparse
import logging

from app.config.settings import load_settings
from app.scheduler.jobs import TradingAlertJob
from app.utils.log_redactor import LogRedactor
from app.utils.logging_config import setup_logging


logger = logging.getLogger(__name__)


def _install_log_redactor(settings) -> None:
    """Agrega un filter al root logger para enmascarar tokens y secretos conocidos."""
    secrets = [
        settings.telegram_bot_token or "",
        settings.telegram_chat_id or "",
        settings.mt5_password or "",
        settings.mt5_server or "",
    ]
    redactor = LogRedactor(secret_values=secrets)
    root = logging.getLogger()
    root.addFilter(redactor)
    for handler in root.handlers:
        handler.addFilter(redactor)


def main() -> int:
    parser = argparse.ArgumentParser(description="Trading Alert AI local monitor")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one monitoring cycle and exit.",
    )
    parser.add_argument(
        "--mode",
        default=None,
        choices=["trader", "alerts_only", "hybrid"],
        help=(
            "Override bot mode for this run. Priority: CLI > Telegram /mode "
            "persisted > .env BOT_MODE > default trader."
        ),
    )
    args = parser.parse_args()

    setup_logging()
    settings = load_settings()
    _install_log_redactor(settings)
    job = TradingAlertJob(settings, cli_mode_override=args.mode)

    # Phase 5.5 Bloque B v2.6.0: arrancar ScalpingEngine en thread separado
    # si el flag esta activo (via setting, bot_state o CLI futuro).
    scalping_engine = None
    try:
        from app.utils.scalping_state import resolve_scalping_state

        if resolve_scalping_state(settings, job.repository):
            from app.scheduler.scalping_engine import ScalpingEngine

            scalping_engine = ScalpingEngine(
                settings,
                job.repository,
                job.notifier,
                job.mt5_reader,
            )
            scalping_engine.start()
    except Exception:
        logger.exception("ScalpingEngine failed to start; main loop continues")

    try:
        if args.once:
            job.run_once()
            return 0
        job.run_forever()
    except KeyboardInterrupt:
        logger.info("Trading Alert AI stopped by user")
        return 0
    finally:
        if scalping_engine is not None and scalping_engine.is_running():
            scalping_engine.stop(timeout=10.0)


if __name__ == "__main__":
    raise SystemExit(main())
