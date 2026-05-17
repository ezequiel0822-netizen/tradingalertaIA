# Trading Alert AI v1.5

Sistema local read-only para monitorear cripto, memecoins y bolsa. Observa datos publicos, guarda historial en SQLite, estima posible subida/caida, revisa riesgo, analiza patrones/noticias y manda pocas alertas agrupadas por Telegram.

## Que hace

- Detecta tokens nuevos, boosted y pools trending.
- Analiza volumen, liquidez, precio, patrones y noticias.
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
APP_VERSION=v1.5
ENABLE_TELEGRAM_ASSISTANT=true
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
/analiza NVDA
/noticias NVDA
/patron NVDA
/pausar
/reanudar
/config
```

## Control de ruido v1.5

- Memecoins: por defecto maximo 5 candidatos enviados por 24h.
- Bolsa: por defecto maximo 5 candidatos enviados por 24h.
- Por ciclo: maximo 2 memecoins y 2 acciones dentro de mensajes agrupados.
- Las memecoins necesitan subida estimada de 500% o mas y confianza minima.
- El filtro anti-hype penaliza boosts/trending con baja liquidez, seguridad unknown o subidas ya exageradas.

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
