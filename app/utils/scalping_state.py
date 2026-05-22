"""Resolucion del estado activo del scalping engine — v2.6.0 Phase 5.5 Bloque B.

Orden de prioridad (mas alto gana):
1. CLI flag (`python main.py --scalping on|off`) — override absoluto para la sesion.
2. `bot_state.scalping_active` — persistido via comando Telegram `/scalping_on|off`.
3. Setting `ENABLE_SCALPING_ENGINE` del `.env`.
4. Default `False`.

Espejo del patron de `app/utils/bot_mode.py::resolve_bot_mode`. Read-only:
solo lee settings + bot_state, no modifica nada.
"""

from typing import Any


TRUE_VALUES = frozenset({"true", "1", "on", "yes", "si", "sí"})
FALSE_VALUES = frozenset({"false", "0", "off", "no"})

DEFAULT_STATE = False


def _normalize_bool(raw: str | None) -> bool | None:
    """Convierte string a bool. Devuelve None si no es interpretable."""
    if raw is None:
        return None
    value = str(raw).strip().lower()
    if value in TRUE_VALUES:
        return True
    if value in FALSE_VALUES:
        return False
    return None


def resolve_scalping_state(
    settings: Any,
    repository: Any,
    cli_override: str | None = None,
) -> bool:
    """Devuelve si el scalping engine debe correr en este boot.

    Args:
        settings: Settings cargado del .env (`enable_scalping_engine` field).
        repository: Repository con acceso a `bot_state`.
        cli_override: string opcional del CLI flag `--scalping`.

    Returns:
        True si el engine debe arrancar, False si queda apagado.
    """
    # 1. CLI flag (override absoluto)
    cli = _normalize_bool(cli_override)
    if cli is not None:
        return cli

    # 2. bot_state persistido (toggle Telegram)
    try:
        persisted = repository.get_state("scalping_active")
    except Exception:
        persisted = None
    persisted_bool = _normalize_bool(persisted)
    if persisted_bool is not None:
        return persisted_bool

    # 3. setting del .env
    setting_value = getattr(settings, "enable_scalping_engine", None)
    if setting_value is True or setting_value is False:
        return setting_value

    # 4. default conservador
    return DEFAULT_STATE


def is_scalping_halted(repository: Any) -> bool:
    """Kill-switch especifico de scalping (independiente del kill switch global).

    Lo activa `/scalping_halt`, lo libera `/scalping_resume`. Coexiste con el
    kill switch global del swing engine (`kill_switch_active_until`).
    """
    try:
        raw = repository.get_state("scalping_halted")
    except Exception:
        return False
    return _normalize_bool(raw) is True
