"""
Parche para app/config/settings.py — v3.17
-----------------------------------------
Añade los nuevos campos al dataclass Settings y a load_settings().

INSTRUCCIONES:
1. Abre app/config/settings.py
2. Dentro de la clase Settings (el @dataclass), añade los campos nuevos
   (cerca de los otros enable_*).
3. Dentro de load_settings(), lee los nuevos valores con _get_bool / _get_int / _get_float
   y pásalos al constructor de Settings.

Campos nuevos:
"""

# === Añadir al dataclass Settings ===
#
#     # v3.17 — Quality Gate + Web News Enhancer
#     enable_quality_gate: bool
#     quality_min_confluence: int
#     enable_web_news_enhancer: bool
#     web_news_max_age_hours: float

# === Añadir dentro de load_settings() (ejemplo) ===
#
#     enable_quality_gate=_get_bool("ENABLE_QUALITY_GATE", False),
#     quality_min_confluence=_get_int("QUALITY_MIN_CONFLUENCE", 2),
#     enable_web_news_enhancer=_get_bool("ENABLE_WEB_NEWS_ENHANCER", False),
#     web_news_max_age_hours=_get_float("WEB_NEWS_MAX_AGE_HOURS", 18.0),

# También sincronizar en tests/test_score.py y tests/test_alert_rules.py
# las funciones _settings() helper si existen (regla del proyecto).
