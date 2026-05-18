# Trading Alert AI v1.5.2

Sistema local read-only para monitorear cripto, memecoins y bolsa. Observa datos publicos, guarda historial en SQLite, estima posible subida/caida, revisa riesgo, analiza patrones/noticias/filings SEC, aprende de resultados historicos y simula setups en papel.

## Que hace

- Detecta tokens nuevos, boosted y pools trending.
- Analiza volumen, liquidez, precio, patrones, noticias y filings SEC.
- Calcula una lectura IA Pro con setup, sesgo, confianza, riesgos y checklist.
- Aprende de sus señales pasadas con `signal_outcomes` y `strategy_lessons`.
- Crea paper trades simulados para medir preparacion sin operar real.
- Estima subida, caida y confianza.
- Guarda tokens, alertas y seguridad en SQLite.
- Envia Telegram solo con los mejores candidatos.
- Responde comandos basicos por Telegram.
- Escribe memoria diaria en Obsidian.

## Que NO hace

- No compra ni vende.
- No conecta wallets ni brokers.
- No firma transacciones.
- No ejecuta ordenes.
- No pide seed phrase ni private keys.

## Instalar

```powershell
python -m pip install -r requirements.txt
```

## Configurar `.env`

Copia `.env.example` como referencia y pon los valores reales solo en `.env`.

```env
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
APP_VERSION=v1.5.2
ENABLE_TELEGRAM_ASSISTANT=true
ENABLE_PRO_INTELLIGENCE=true
ENABLE_SEC_FILINGS_INTEL=true
ENABLE_LEARNING_ENGINE=true
ENABLE_PAPER_TRADING=true
ENABLE_OBSIDIAN_MEMORY=true
OBSIDIAN_VAULT_PATH=obsidian/tradingbot v.1
```

No subas `.env` a GitHub.

## Probar Telegram

```powershell
python test_telegram.py
```

## Correr el monitor

```powershell
python main.py
```

Para detenerlo: presiona `Ctrl + C` en la terminal donde esta corriendo.

## Abrir dashboard

```powershell
streamlit run app/dashboard/streamlit_app.py
```

## Comandos Telegram

```text
/help
/status
/cupos
/top
/top_memecoins
/top_stocks
/alertas
/descartes
/aprendizaje
/paper
/entrenar
/analiza NVDA
/noticias NVDA
/filings NVDA
/patron NVDA
/pro NVDA
/pausar
/reanudar
/config
```

## Control de ruido v1.5.1

- Memecoins: por defecto maximo 5 candidatos enviados por 24h.
- Bolsa: por defecto maximo 5 candidatos enviados por 24h.
- Por ciclo: maximo 2 memecoins y 2 acciones dentro de mensajes agrupados.
- Las memecoins necesitan subida estimada de 500% o mas y confianza minima.
- El filtro anti-hype penaliza boosts/trending con baja liquidez, seguridad unknown o subidas ya exageradas.

## IA Pro

- Indicadores: RSI, medias, MACD, Bollinger, ATR, volumen relativo, soporte y resistencia.
- Catalizadores: titulares de noticias, earnings, revenue, guidance, conferencias, upgrades/downgrades.
- SEC: filings recientes para acciones cuando la SEC tenga datos publicos disponibles.
- Visualizacion rapida: sparkline de precio en Telegram para `/pro`.
- Salida: setup, sesgo, score, confianza, razones, riesgos y checklist manual.

## Learning Engine v1.5.2

- Evalua señales anteriores contra el precio actual guardado.
- Clasifica outcomes como `win`, `neutral` o `loss`.
- Extrae features: IA Pro, patrones, noticias, filings, volumen, liquidez, riesgo y anti-hype.
- Genera lecciones locales por feature y categoria.
- Abre paper trades simulados solo para setups A/B.
- Nunca envia ordenes reales.

## Carpetas

- `app/collectors`: datos publicos.
- `app/analyzers`: score, riesgo, patrones, noticias y estimacion.
- `app/alerts`: formato y envio Telegram.
- `app/database`: SQLite y repositorio.
- `app/scheduler`: ciclo principal.
- `app/dashboard`: Streamlit.
- `app/assistant`: respuestas por Telegram.
- `obsidian/tradingbot v.1`: memoria del proyecto.
- `tests`: pruebas basicas.

## Advertencia

No es recomendacion financiera. El sistema solo ayuda a filtrar candidatos para revision manual.
