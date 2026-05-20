# Reglas de Seguridad

## Prohibiciones absolutas

El sistema NO debe:

- comprar
- vender
- conectar wallets reales
- conectar brokers reales
- firmar transacciones
- ejecutar ordenes en cuenta real
- pedir seed phrase
- pedir private keys
- guardar secretos en codigo
- imprimir tokens en consola o logs

## Excepciones autorizadas (desde v2.0.0)

- **MT5 demo trading** queda autorizado para Fase 5. Solo cuenta demo, nunca real.
- Esta excepcion se aplica unicamente a la cuenta MT5 demo configurada en el `.env` del usuario.
- Real-money trading sigue prohibido sin nueva autorizacion explicita.
- **2026-05-19**: usuario confirma cuenta demo **ICMarkets** lista. Phase 4 (validación + walk-forward + data quality + CSV) shipped en v2.3.0. **Phase 5 está autorizada para arrancar** (`order_send(action=demo)` con kill-switch + mandatory SL + 1% riesgo por trade).

## Secretos

Los secretos solo deben vivir en `.env`:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `MT5_LOGIN`, `MT5_PASSWORD`, `MT5_SERVER`, `MT5_PATH` (desde v2.0.0)

`.env.example` siempre tiene valores vacios. Defensas adicionales en v2.1.0:

- `Settings.__repr__` enmascara campos secretos con `<redacted>`.
- `LogRedactor` filter del root logger borra tokens y valores conocidos antes de escribir log.
- `safe_path` rechaza traversal (`../`) en `OBSIDIAN_VAULT_PATH` y archivos invalidos en `MT5_PATH`.
- `init_db` no loguea path absoluto de la DB si ocurre corruption.

## Telegram

El asistente solo responde al `TELEGRAM_CHAT_ID` autorizado.

Comandos sensibles tienen clamps duros desde v2.1.0:

- `/halt N` → N se clampa a [1, 168] horas.
- `RISK_PER_TRADE_PCT` → safety cap a 10% (rechaza configs accidentales).

## Trader engine (v2.0.0+)

El bot opera **solo en paper trades simulados**:

- Strategy router pregunta a 4 estrategias (breakout, mean_reversion, momentum, news_catalyst).
- Risk manager bloquea apertura si:
  - kill_switch activo (manual `/halt` o auto por max drawdown)
  - max_open_trades_total alcanzado
  - max_total_risk_pct excedido
  - daily P&L < -max_daily_drawdown_pct
- Position sizer calcula tamaño por `% cuenta x distancia stop`.
- Lifecycle manager cierra trades por time horizon o por strategy invalidation.

Sin esto, ningun paper trade se abre.

## Memecoins en v2.0.0+

Memecoins quedan como **lab de aprendizaje**:

- Alimentan `strategy_lessons` y `alert_outcome_horizons` para entrenar el motor.
- NO van a Telegram salvo que `ENABLE_MEMECOIN_TELEGRAM=true`.
- NO se operan en MT5 (los instrumentos no existen ahi).

## Dependencias (v2.1.0)

`requirements.txt` con versiones pinneadas exactas. Defensa contra cadena suministro maliciosa.

## Recomendacion operativa

Si alguna vez un token real queda en `.env.example`, README, logs o memoria, regenerarlo en BotFather o proveedor correspondiente.
