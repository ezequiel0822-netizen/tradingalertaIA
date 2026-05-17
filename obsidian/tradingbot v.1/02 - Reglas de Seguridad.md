# Reglas de Seguridad

## Prohibiciones absolutas

El sistema NO debe:

- comprar
- vender
- conectar wallets
- conectar brokers
- firmar transacciones
- ejecutar ordenes
- pedir seed phrase
- pedir private keys
- guardar secretos en codigo
- imprimir tokens en consola

## Secretos

Los secretos solo deben vivir en `.env`.

`.env.example` debe estar limpio y contener valores vacios.

## Telegram

El asistente de Telegram solo debe responder al `TELEGRAM_CHAT_ID` autorizado.

## IA basica y Signal Quality

La IA v1.5 sigue siendo basica, local y read-only:

- no usa OpenAI API
- no usa modelos externos
- responde desde reglas y SQLite
- no puede ejecutar acciones de trading
- agrupa alertas para mandar menos mensajes
- usa filtros anti-hype y cupos por categoria

## Recomendacion operativa

Si alguna vez un token real queda en `.env.example`, README, logs o memoria, regenerarlo en BotFather o proveedor correspondiente.
