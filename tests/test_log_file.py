"""v3.17.1 — log del bot a archivo (opt-in) + secretos enmascarados también en tracebacks."""

from __future__ import annotations

import logging
import re
from dataclasses import replace

import pytest

from app.utils import logging_config as lc
from app.utils.log_redactor import RedactingFormatter, install_log_redactor, redact_text
from app.utils.logging_config import SafeRotatingFileHandler, log_file_path, setup_file_logging
from tests.test_score import _settings

TOKEN = "1234567890:" + "A" * 35            # forma de un token de bot de Telegram
PASSWORD = "SuperSecretMt5Pass"


@pytest.fixture
def clean_root():
    """Deja el root logger como estaba (handlers, filtros y nivel)."""
    root = logging.getLogger()
    saved = (list(root.handlers), list(root.filters), root.level)
    root.handlers = []
    root.filters = []
    root.setLevel(logging.INFO)
    yield root
    for h in root.handlers:
        if h not in saved[0]:
            h.close()
    root.handlers, root.filters = saved[0], saved[1]
    root.setLevel(saved[2])


def _on(tmp_path, **kw):
    base = {"log_to_file": True, "sqlite_path": tmp_path / "bot.db",
            "telegram_bot_token": TOKEN, "mt5_password": PASSWORD}
    return replace(_settings(), **{**base, **kw})


def test_off_by_default_adds_nothing(clean_root, tmp_path) -> None:
    assert _settings().log_to_file is False
    assert setup_file_logging(replace(_settings(), sqlite_path=tmp_path / "x.db")) is None
    # (pytest agrega sus propios handlers al root: se mira solo que no haya uno de archivo)
    assert not any(isinstance(h, SafeRotatingFileHandler) for h in clean_root.handlers)
    assert not (tmp_path / "logs").exists()


def test_writes_utc_lines_next_to_the_db_and_is_idempotent(clean_root, tmp_path) -> None:
    s = _on(tmp_path)
    path = setup_file_logging(s)
    assert path == log_file_path(s) == tmp_path / "logs" / "bot.log"
    assert setup_file_logging(s) == path                       # no duplica el handler
    assert sum(isinstance(h, SafeRotatingFileHandler) for h in clean_root.handlers) == 1
    logging.getLogger("prueba").info("ciclo completo, señal rara: ñ")
    for h in clean_root.handlers:
        h.flush()
    text = path.read_text(encoding="utf-8")
    assert "Log a archivo: logs/bot.log (rota a los 10 MB, guarda 5)" in text
    line = [ln for ln in text.splitlines() if "ciclo completo" in ln][0]
    assert re.match(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d UTC \| INFO \| MainThread \| prueba \| ", line)
    assert line.endswith("señal rara: ñ")
    assert str(tmp_path) not in text                           # no la ruta completa


def test_secrets_are_masked_in_messages_and_tracebacks(clean_root, tmp_path) -> None:
    s = _on(tmp_path)
    path = setup_file_logging(s)
    install_log_redactor(s)
    log = logging.getLogger("prueba.secretos")
    log.warning("fallo Telegram: url /bot%s/sendMessage", TOKEN)
    try:
        raise ConnectionError(f"Max retries with url: /bot{TOKEN}/getUpdates pass={PASSWORD}")
    except ConnectionError:
        log.exception("el comando se cayo")
    for h in clean_root.handlers:
        h.flush()
    text = path.read_text(encoding="utf-8")
    assert TOKEN not in text and PASSWORD not in text
    assert "Traceback" in text and "<redacted" in text and "el comando se cayo" in text


def test_console_tracebacks_are_masked_too(clean_root, tmp_path) -> None:
    import io

    buf = io.StringIO()
    console = logging.StreamHandler(buf)
    console.setFormatter(logging.Formatter("%(levelname)s | %(message)s"))
    clean_root.addHandler(console)
    install_log_redactor(_on(tmp_path))
    assert isinstance(console.formatter, RedactingFormatter)
    try:
        raise RuntimeError(f"token {TOKEN}")
    except RuntimeError:
        logging.getLogger("prueba.consola").exception("boom")
    out = buf.getvalue()
    assert out.startswith("ERROR | boom") and TOKEN not in out and "<redacted" in out
    install_log_redactor(_on(tmp_path))                        # no envuelve dos veces
    assert not isinstance(console.formatter.inner, RedactingFormatter)


def test_redact_text_known_values_and_token_shape() -> None:
    assert redact_text(f"a {PASSWORD} b", [PASSWORD]) == "a <redacted> b"
    assert redact_text(f"x {TOKEN} y", []) == "x <redacted-token> y"
    assert redact_text("limpio", [PASSWORD]) == "limpio"


def test_rotation_keeps_size_bounded(clean_root, tmp_path) -> None:
    path = tmp_path / "logs" / "bot.log"
    path.parent.mkdir()
    h = SafeRotatingFileHandler(path, maxBytes=2000, backupCount=2, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(message)s"))
    log = logging.getLogger("prueba.rotacion")
    log.addHandler(h)
    log.propagate = False
    try:
        for i in range(300):
            log.info("linea %04d %s", i, "x" * 40)
    finally:
        log.removeHandler(h)
        log.propagate = True
        h.close()
    files = sorted(p.name for p in path.parent.iterdir())
    assert files == ["bot.log", "bot.log.1", "bot.log.2"]
    assert all(p.stat().st_size <= 2100 for p in path.parent.iterdir())


def test_rotation_failure_on_windows_keeps_logging(clean_root, tmp_path, monkeypatch) -> None:
    """Si otro programa tiene el archivo abierto, renombrar falla: no se rompe, sigue
    escribiendo en el mismo archivo y no reintenta hasta `retry_seconds`."""
    path = tmp_path / "bot.log"
    h = SafeRotatingFileHandler(path, maxBytes=500, backupCount=2, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(message)s"))
    calls = []

    def _locked(source, dest):
        calls.append(dest)
        raise PermissionError("archivo en uso por otro proceso")

    monkeypatch.setattr(h, "rotate", _locked)
    errors = []
    monkeypatch.setattr(h, "handleError", lambda record: errors.append(record))
    log = logging.getLogger("prueba.bloqueado")
    log.addHandler(h)
    log.propagate = False
    try:
        for i in range(100):
            log.info("linea %04d %s", i, "y" * 30)
    finally:
        log.removeHandler(h)
        log.propagate = True
        h.close()
    assert errors == [] and len(calls) == 1                   # un intento, sin ruido
    text = path.read_text(encoding="utf-8")
    assert "linea 0000" in text and "linea 0099" in text      # no perdió líneas


def test_cannot_open_file_soft_fails(clean_root, tmp_path, monkeypatch) -> None:
    def _boom(self, *a, **k):
        raise OSError("disco lleno")

    monkeypatch.setattr(lc.SafeRotatingFileHandler, "__init__", _boom)
    assert setup_file_logging(_on(tmp_path)) is None           # sigue solo con consola
    assert not any(isinstance(h, SafeRotatingFileHandler) for h in clean_root.handlers)
