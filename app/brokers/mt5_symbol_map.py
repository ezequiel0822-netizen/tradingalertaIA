"""Symbol mapping Yahoo Finance ↔ MT5 broker.

Por defecto perfil ICMarkets (simbolos limpios). Otros brokers pueden tener
sufijos (.m, .r, .raw) — agregar el mapping al diccionario y configurar
MT5_BROKER_PROFILE en el .env.
"""


_YAHOO_TO_MT5_BY_BROKER: dict[str, dict[str, str]] = {
    "icmarkets": {
        "EURUSD=X": "EURUSD",
        "GBPUSD=X": "GBPUSD",
        "USDJPY=X": "USDJPY",
        "USDCHF=X": "USDCHF",
        "AUDUSD=X": "AUDUSD",
        "USDCAD=X": "USDCAD",
        "NZDUSD=X": "NZDUSD",
        "GC=F": "XAUUSD",
        "XAUUSD=X": "XAUUSD",
    },
    "metaquotes": {
        "EURUSD=X": "EURUSD",
        "GBPUSD=X": "GBPUSD",
        "USDJPY=X": "USDJPY",
        "USDCHF=X": "USDCHF",
        "AUDUSD=X": "AUDUSD",
        "USDCAD=X": "USDCAD",
        "NZDUSD=X": "NZDUSD",
        "GC=F": "XAUUSD",
    },
    # Add other brokers (FBS, Exness, OANDA) here with their suffix conventions.
}


def yahoo_to_mt5(yahoo_symbol: str, broker_profile: str = "icmarkets") -> str | None:
    """Mapea simbolo Yahoo a simbolo MT5 segun el broker.

    Si el broker no esta en el mapa, intenta el ICMarkets default.
    Si el simbolo no esta en el mapa, retorna None.
    """
    if not yahoo_symbol:
        return None
    table = _YAHOO_TO_MT5_BY_BROKER.get(
        broker_profile.lower(), _YAHOO_TO_MT5_BY_BROKER["icmarkets"]
    )
    upper = yahoo_symbol.upper()
    return table.get(upper)


def mt5_to_yahoo(mt5_symbol: str, broker_profile: str = "icmarkets") -> str | None:
    """Inverso: MT5 → Yahoo. Util para joinear data MT5 con outcomes Yahoo.

    Si hay multiples Yahoo para el mismo MT5 (caso XAUUSD: GC=F + XAUUSD=X),
    retorna la primera entrada.
    """
    if not mt5_symbol:
        return None
    table = _YAHOO_TO_MT5_BY_BROKER.get(
        broker_profile.lower(), _YAHOO_TO_MT5_BY_BROKER["icmarkets"]
    )
    target = mt5_symbol.upper()
    for yahoo, mt5sym in table.items():
        if mt5sym.upper() == target:
            return yahoo
    return None


def supported_brokers() -> list[str]:
    return sorted(_YAHOO_TO_MT5_BY_BROKER.keys())
