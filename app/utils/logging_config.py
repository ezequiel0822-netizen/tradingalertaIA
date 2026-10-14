import logging
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_FILE_NAME = "bot.log"
LOG_FILE_FORMAT = "%(asctime)s UTC | %(levelname)s | %(threadName)s | %(name)s | %(message)s"


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    logging.getLogger("urllib3").setLevel(logging.WARNING)


class SafeRotatingFileHandler(RotatingFileHandler):
    """v3.17.1: rotación por tamaño que no rompe en Windows. Si renombrar el archivo
    falla (otro programa lo tiene abierto), sigue escribiendo en el mismo archivo y
    reintenta la rotación recién a los `retry_seconds`, en vez de fallar en cada línea."""

    retry_seconds = 300.0

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._retry_at = 0.0

    def shouldRollover(self, record: logging.LogRecord) -> bool:  # noqa: N802 (stdlib)
        if time.monotonic() < self._retry_at:
            return False
        return bool(super().shouldRollover(record))

    def doRollover(self) -> None:  # noqa: N802 (stdlib)
        try:
            super().doRollover()
        except OSError:
            self._retry_at = time.monotonic() + self.retry_seconds
            if self.stream is None:          # la rotación lo cerró antes de renombrar
                self.stream = self._open()


def log_file_path(settings) -> Path:
    """`<carpeta de la DB>/logs/bot.log` (con la DB por defecto: trading_data/logs/)."""
    return Path(settings.sqlite_path).parent / "logs" / LOG_FILE_NAME


def setup_file_logging(settings) -> Path | None:
    """v3.17.1: además de la consola, guarda el log en un archivo que rota por tamaño
    (LOG_FILE_MAX_MB × LOG_FILE_BACKUPS como máximo en disco), con la hora en UTC (la
    misma base que la DB) y el nombre del hilo. Así, si el bot se cae o se congela,
    queda rastro para revisar después.

    Opt-in LOG_TO_FILE (OFF). Soft-fail: si no se puede abrir, sigue solo con la
    consola. Idempotente. Llamarlo ANTES de install_log_redactor: así el archivo hereda
    el enmascarado de secretos (mensajes y tracebacks)."""
    if not getattr(settings, "log_to_file", False):
        return None
    root = logging.getLogger()
    for handler in root.handlers:
        if isinstance(handler, SafeRotatingFileHandler):
            return Path(handler.baseFilename)
    log = logging.getLogger(__name__)
    try:
        path = log_file_path(settings)
        path.parent.mkdir(parents=True, exist_ok=True)
        max_mb = max(1, int(getattr(settings, "log_file_max_mb", 10)))
        backups = max(1, int(getattr(settings, "log_file_backups", 5)))
        handler = SafeRotatingFileHandler(
            path, maxBytes=max_mb * 1024 * 1024, backupCount=backups, encoding="utf-8"
        )
        formatter = logging.Formatter(LOG_FILE_FORMAT, datefmt="%Y-%m-%d %H:%M:%S")
        formatter.converter = time.gmtime
        handler.setFormatter(formatter)
        handler.setLevel(logging.INFO)
        root.addHandler(handler)
        # Solo el nombre de la carpeta y del archivo (no la ruta completa).
        log.info(
            "Log a archivo: %s/%s (rota a los %d MB, guarda %d)",
            path.parent.name, path.name, max_mb, backups,
        )
        return path
    except Exception:
        log.exception("No pude abrir el log a archivo; sigo solo con la consola")
        return None
