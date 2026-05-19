"""Helpers para HTTP safety: parsing JSON defensivo."""

import logging
from typing import Any

import requests


logger = logging.getLogger(__name__)


def safe_json(response: requests.Response, default: Any = None) -> Any:
    """Parsea response.json() devolviendo default si falla.

    Captura JSON invalido sin crashear el collector.
    """
    try:
        return response.json()
    except (ValueError, requests.JSONDecodeError) as exc:
        logger.warning("JSON parsing failed: %s", exc.__class__.__name__)
        return default
