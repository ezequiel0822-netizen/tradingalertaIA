"""LogRedactor: filtra mensajes log para enmascarar tokens y secretos conocidos.

Layer defensiva. Si algun codigo accidentalmente loguea `settings.telegram_bot_token`
o el token aparece en una stacktrace, este filter lo reemplaza por <redacted>.

NO es la primera linea de defensa — la primera es no loguear secretos.
Esto es seguro contra desarrollos futuros que olviden la regla.
"""

import logging
import re


# Telegram bot token format: 9-12 digits, colon, 35+ chars [A-Za-z0-9_-]
_TG_TOKEN_RE = re.compile(r"\b\d{9,12}:[A-Za-z0-9_-]{35,}\b")


class LogRedactor(logging.Filter):
    def __init__(self, secret_values: list[str] | None = None) -> None:
        super().__init__()
        # Mantener solo valores no vacios; ordenar por longitud descendente
        # para evitar replacements parciales (ej. "abc" antes que "abcdef").
        cleaned = [s for s in (secret_values or []) if isinstance(s, str) and len(s) >= 8]
        self.secret_values = sorted(cleaned, key=len, reverse=True)

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True

        modified = False
        # 1. Valores exactos conocidos del .env
        for secret in self.secret_values:
            if secret in msg:
                msg = msg.replace(secret, "<redacted>")
                modified = True

        # 2. Patrones genericos (Telegram bot token shape)
        new_msg = _TG_TOKEN_RE.sub("<redacted-token>", msg)
        if new_msg != msg:
            msg = new_msg
            modified = True

        if modified:
            record.msg = msg
            record.args = ()
        return True


def redact_text(text: str, secret_values: list[str]) -> str:
    """Mismo enmascarado que LogRedactor, sobre un texto ya armado."""
    for secret in secret_values:
        if secret in text:
            text = text.replace(secret, "<redacted>")
    return _TG_TOKEN_RE.sub("<redacted-token>", text)


class RedactingFormatter(logging.Formatter):
    """v3.17.1: enmascara el texto YA formateado, incluido el traceback de
    `logger.exception`. El filtro (LogRedactor) solo ve el mensaje: si el texto de una
    excepción traía el token (p. ej. una URL de la API de Telegram), salía tal cual a
    la consola, y con el log a archivo habría quedado guardado en disco. Envuelve al
    formatter que ya tenía el handler (mismo formato)."""

    def __init__(self, inner: logging.Formatter | None, secret_values: list[str] | None = None):
        super().__init__()
        self.inner = inner or logging.Formatter()
        cleaned = [s for s in (secret_values or []) if isinstance(s, str) and len(s) >= 8]
        self.secret_values = sorted(cleaned, key=len, reverse=True)

    def format(self, record: logging.LogRecord) -> str:
        return redact_text(self.inner.format(record), self.secret_values)


def secret_values_from(settings) -> list[str]:
    return [
        str(getattr(settings, "telegram_bot_token", "") or ""),
        str(getattr(settings, "telegram_chat_id", "") or ""),
        str(getattr(settings, "mt5_password", "") or ""),
        str(getattr(settings, "mt5_server", "") or ""),
    ]


def install_log_redactor(settings) -> None:
    """Instala el LogRedactor en el root logger y sus handlers, con los secrets de
    settings. Compartido por main.py y el dashboard (cualquier entrypoint que loguee).
    v3.9.3. v3.17.1: además envuelve el formatter de cada handler en un
    RedactingFormatter (tracebacks). Llamarlo DESPUÉS de crear los handlers (el del
    log a archivo incluido): los que se agreguen después no quedan cubiertos."""
    secrets = secret_values_from(settings)
    redactor = LogRedactor(secret_values=secrets)
    root = logging.getLogger()
    root.addFilter(redactor)
    for handler in root.handlers:
        handler.addFilter(redactor)
        if not isinstance(handler.formatter, RedactingFormatter):
            handler.setFormatter(RedactingFormatter(handler.formatter, secrets))
