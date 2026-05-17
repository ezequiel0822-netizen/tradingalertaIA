import argparse
import logging

from app.config.settings import load_settings
from app.scheduler.jobs import TradingAlertJob
from app.utils.logging_config import setup_logging


logger = logging.getLogger(__name__)


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
