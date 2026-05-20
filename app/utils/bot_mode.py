"""Resolucion del modo activo del bot.

Orden de prioridad:
1. CLI flag (`python main.py --mode X`) — override absoluto para la sesion.
2. `bot_state.bot_mode_active` — persistido via comando Telegram `/mode X`.
3. Setting `bot_mode` (del `.env`).
4. Default `"trader"`.

Modos validos:
- `trader`: bot decide y abre paper trades automaticamente. Comportamiento default.
- `alerts_only`: solo alerta por Telegram. Strategy router skipped. Lifecycle manager
  sigue gestionando posiciones ABIERTAS (no abandona trades existentes).
- `hybrid`: en v2.4.0 se comporta como `trader`. Phase 5+ agregara confirmacion
  manual Telegram antes de abrir.

Read-only: solo lee settings + bot_state. No modifica nada.
"""

from typing import Any


VALID_MODES = frozenset({"trader", "alerts_only", "hybrid"})

DEFAULT_MODE = "trader"


def resolve_bot_mode(
    settings: Any,
    repository: Any,
    cli_override: str | None = None,
) -> str:
    """Devuelve el modo activo segun el orden de prioridad documentado."""
    # 1. CLI flag
    if cli_override:
        normalized = cli_override.strip().lower()
        if normalized in VALID_MODES:
            return normalized

    # 2. bot_state persistido
    try:
        persisted = repository.get_state("bot_mode_active") or ""
    except Exception:
        persisted = ""
    if persisted and persisted.strip().lower() in VALID_MODES:
        return persisted.strip().lower()

    # 3. setting del .env
    setting_value = getattr(settings, "bot_mode", "") or ""
    normalized_setting = setting_value.strip().lower()
    if normalized_setting in VALID_MODES:
        return normalized_setting

    # 4. default
    return DEFAULT_MODE


def is_valid_mode(value: str | None) -> bool:
    if not value:
        return False
    return value.strip().lower() in VALID_MODES


def normalize_mode(value: str | None) -> str | None:
    if not value:
        return None
    candidate = value.strip().lower()
    return candidate if candidate in VALID_MODES else None
