from pathlib import Path
from uuid import uuid4

from app.assistant.command_handler import BasicTelegramAssistant
from app.database.db import init_db
from app.database.models import AlertRecord, EstimateResult, SecuritySummary, TokenSnapshot
from app.database.repository import Repository
from tests.test_score import _settings


def _repo() -> Repository:
    db_dir = Path.cwd() / ".test_dbs"
    db_dir.mkdir(exist_ok=True)
    db_path = db_dir / f"assistant_{uuid4().hex}.db"
    init_db(db_path)
    return Repository(db_path)


def test_assistant_status_and_pause() -> None:
    settings = _settings()
    repo = _repo()
    assistant = BasicTelegramAssistant(settings, repo)

    status = assistant.handle("/status")
    assert "Alertas automaticas: activas" in status

    paused = assistant.handle("/pausar")
    assert "Alertas pausadas" in paused
    assert repo.alerts_paused() is True

    resumed = assistant.handle("/reanudar")
    assert "Alertas reanudadas" in resumed
    assert repo.alerts_paused() is False


def test_assistant_can_analyze_saved_symbol() -> None:
    settings = _settings()
    repo = _repo()
    snapshot = TokenSnapshot(
        chain="stock",
        token_address="NVDA",
        category="stock",
        symbol="NVDA",
        name="NVIDIA",
        source="test",
        price=100,
        liquidity_usd=1_000_000,
    )
    estimate = EstimateResult(
        estimated_gain_pct=12,
        estimated_loss_pct=20,
        confidence=70,
        label="high-conviction-stock",
        reasons=["test"],
        eligible_for_gain_alert=True,
    )
    repo.upsert_token(snapshot, score=80, risk_level="orange", estimate=estimate)
    assistant = BasicTelegramAssistant(settings, repo)

    reply = assistant.handle("/analiza NVDA")

    assert "Analisis basico" in reply
    assert "NVDA" in reply
    assert "Subida estimada: 12.00%" in reply


def test_assistant_cupos_and_descartes() -> None:
    settings = _settings()
    repo = _repo()
    snapshot = TokenSnapshot(
        chain="base",
        token_address="0xaaa",
        category="memecoin",
        symbol="AAA",
        name="AAA Token",
        source="test",
        price=0.01,
        liquidity_usd=50_000,
    )
    estimate = EstimateResult(
        estimated_gain_pct=300,
        estimated_loss_pct=50,
        confidence=60,
        label="watch-only",
        reasons=["test"],
        eligible_for_gain_alert=False,
    )
    token_id = repo.upsert_token(snapshot, score=70, risk_level="yellow", estimate=estimate)
    repo.insert_alert(
        AlertRecord(
            token_id=token_id,
            alert_type="WATCHLIST_MOVEMENT",
            snapshot=snapshot,
            app_version=settings.app_version,
            category="memecoin",
            score=70,
            risk_level="yellow",
            reasons=["test"],
            security=SecuritySummary(raw_summary="unknown"),
            estimate=estimate,
            sent_to_telegram=False,
        )
    )
    assistant = BasicTelegramAssistant(settings, repo)

    cupos = assistant.handle("/cupos")
    descartes = assistant.handle("/descartes")

    assert "Memecoins" in cupos
    assert "Bolsa" in cupos
    assert "Mejores candidatos NO enviados" in descartes
    assert "AAA" in descartes


# --------------------------------------------------------------------------- #
# v3.9.4 — bug A1 (poison message) + trigger /analiza NULL + chunking Telegram
# --------------------------------------------------------------------------- #
from dataclasses import replace  # noqa: E402

from app.alerts.telegram_notifier import split_message  # noqa: E402
from app.assistant.telegram_assistant import TelegramAssistantPoller  # noqa: E402
from app.database.db import get_connection  # noqa: E402


class _RecordingNotifier:
    def __init__(self) -> None:
        self.sent: list[str] = []

    def send_message(self, text: str, chat_id: str | None = None) -> bool:
        self.sent.append(text)
        return True


def test_poison_command_does_not_brick_poller() -> None:
    """v3.9.4 (bug A1): un comando que crashea NO envenena el poller — el offset
    avanza igual (finally) y el resto del batch se sigue procesando. Antes, la
    excepcion impedia persistir el offset y Telegram re-entregaba el MISMO update
    cada ciclo -> bot muerto/sordo hasta que el update expirara (~24h)."""
    settings = replace(_settings(), telegram_bot_token="t", telegram_chat_id="123")
    repo = _repo()
    notifier = _RecordingNotifier()
    poller = TelegramAssistantPoller(settings, repo, notifier)

    class _CrashingHandler:
        def handle(self, text: str) -> str:
            raise TypeError("poison")

    poller.handler = _CrashingHandler()
    updates = [
        {"update_id": 41, "message": {"chat": {"id": 123}, "text": "/analiza X"}},
        {"update_id": 42, "message": {"chat": {"id": 123}, "text": "/status"}},
    ]
    poller._get_updates = lambda: updates  # sin red

    poller.process_updates()

    assert repo.get_state("telegram_last_update_id") == "42"  # el offset avanzo
    assert len(notifier.sent) == 2  # respondio (con mensaje de error) a ambos
    assert "sigue vivo" in notifier.sent[0]


def test_analiza_with_null_gain_does_not_crash() -> None:
    """v3.9.4 (trigger concreto del A1): /analiza sobre una fila legacy con
    latest_estimated_gain_pct NULL no lanza TypeError (None >= float)."""
    settings = _settings()
    repo = _repo()
    snapshot = TokenSnapshot(
        chain="stock",
        token_address="NVDA",
        category="stock",
        symbol="NVDA",
        name="NVIDIA",
        source="test",
        price=100,
        liquidity_usd=1_000_000,
    )
    estimate = EstimateResult(
        estimated_gain_pct=12,
        estimated_loss_pct=20,
        confidence=70,
        label="high-conviction-stock",
        reasons=["test"],
        eligible_for_gain_alert=True,
    )
    repo.upsert_token(snapshot, score=80, risk_level="orange", estimate=estimate)
    # simular fila legacy (columna agregada por _ensure_column quedo NULL)
    with get_connection(repo.db_path) as connection:
        connection.execute("UPDATE tokens SET latest_estimated_gain_pct = NULL")
        connection.commit()
    assistant = BasicTelegramAssistant(settings, repo)

    reply = assistant.handle("/analiza NVDA")

    assert "Analisis basico" in reply
    assert "watchlist" in reply  # NULL -> 0.0 -> no llega al umbral


def test_split_message_short_text_single_chunk() -> None:
    assert split_message("hola") == ["hola"]


def test_split_message_chunks_long_text_at_newlines() -> None:
    """v3.9.4 (M5): mensajes >4096 se parten en chunks validos (antes Telegram
    devolvia 400 y la respuesta entera se perdia, ej. /edge con muchos slices)."""
    lines = [f"linea {i} " + "x" * 80 for i in range(100)]
    text = "\n".join(lines)
    chunks = split_message(text)

    assert len(chunks) > 1
    assert all(0 < len(c) <= 4096 for c in chunks)
    assert "\n".join(chunks) == text  # corta en saltos de linea -> nada se pierde
