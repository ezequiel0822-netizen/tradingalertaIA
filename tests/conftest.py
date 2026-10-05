"""Configuración común de tests.

v3.13.1: los tests crean una DB SQLite por test en `.test_dbs/` y nunca la borraban
(el 2026-10-05 había ~400 MB acumulados en el checkout principal). Al terminar la
sesión se borra el contenido; lo que siga abierto (Windows) se reintenta la próxima.
"""

from __future__ import annotations

import gc
from pathlib import Path


def pytest_sessionfinish(session, exitstatus) -> None:  # noqa: ARG001
    gc.collect()                       # cierra conexiones sqlite3 sin referencias
    for f in (Path.cwd() / ".test_dbs").glob("*"):
        try:
            f.unlink()
        except OSError:
            pass
