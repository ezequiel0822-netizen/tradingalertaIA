"""Helpers para path safety: bloquea traversal y valida files opcionales.

Read-only modules — no escriben, solo validan.
"""

from pathlib import Path


def safe_resolve_within(candidate: Path, root: Path) -> Path | None:
    """Resuelve candidate y verifica que vive bajo root.

    Devuelve None si escapa via .. o symlinks; sino el path resuelto.
    """
    try:
        resolved = candidate.expanduser().resolve()
        root_resolved = root.expanduser().resolve()
        resolved.relative_to(root_resolved)
        return resolved
    except (ValueError, OSError, RuntimeError):
        return None


def safe_optional_file(path_str: str | None) -> Path | None:
    """Para paths opcionales del .env (ej. MT5_PATH).

    Valida que es archivo absoluto existente. None si invalido.
    No sigue symlinks ciegamente (resolve los normaliza primero).
    """
    if not path_str:
        return None
    p = Path(path_str).expanduser()
    if not p.is_absolute():
        return None
    try:
        resolved = p.resolve()
    except (OSError, RuntimeError):
        return None
    try:
        if not resolved.is_file():
            return None
    except OSError:
        return None
    return resolved
