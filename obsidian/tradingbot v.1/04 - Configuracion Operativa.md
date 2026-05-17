# Configuracion Operativa

## Variables importantes

Agregar al `.env` normal, no solo a `.env.example`:

```env
APP_VERSION=v1.5
ENABLE_TELEGRAM_ASSISTANT=true
TELEGRAM_ASSISTANT_MAX_UPDATES=10
ENABLE_ADVANCED_MARKET_INTEL=true
ENABLE_NEWS_INTEL=true
MAX_CHART_ANALYSES_PER_RUN=6
MAX_NEWS_PER_SYMBOL=5
ENABLE_OBSIDIAN_MEMORY=true
OBSIDIAN_VAULT_PATH=obsidian/tradingbot v.1
```

## Cupos recomendados

```env
MEMECOIN_MAX_ALERTS_PER_24H=5
STOCK_MAX_ALERTS_PER_24H=5
MEMECOIN_MAX_ALERTS_PER_RUN=2
STOCK_MAX_ALERTS_PER_RUN=2
ALERT_CAP_WINDOW_HOURS=24
```

## Umbrales recomendados

```env
MIN_ESTIMATED_GAIN_PCT=500
MIN_ESTIMATE_CONFIDENCE=45
MIN_STOCK_ESTIMATED_GAIN_PCT=8
MIN_STOCK_ESTIMATE_CONFIDENCE=55
```

## Comandos

Instalar:

```powershell
python -m pip install -r requirements.txt
```

Correr monitor:

```powershell
python main.py
```

Dashboard:

```powershell
streamlit run app/dashboard/streamlit_app.py
```
