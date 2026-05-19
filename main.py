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
    args = parser.parse_args()

    setup_logging()
    settings = load_settings()
    _install_log_redactor(settings)
    job = TradingAlertJob(settings)

    if args.once:
        job.run_once()
        return 0

    try:
        job.run_forever()
    except KeyboardInterrupt:
        logger.info("Trading Alert AI stopped by user")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
