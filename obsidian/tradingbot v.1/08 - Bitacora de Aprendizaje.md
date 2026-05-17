# Bitacora de Aprendizaje

## 2026-05-17

Se aclaro que:

- las variables `APP_VERSION`, `ENABLE_TELEGRAM_ASSISTANT` y `TELEGRAM_ASSISTANT_MAX_UPDATES` deben ir en `.env` normal
- `.env.example` es solo plantilla sin valores reales
- el usuario quiere una memoria tipo Obsidian para clasificar decisiones importantes
- la memoria no debe guardar secretos
- la boveda correcta esta en `obsidian/tradingbot v.1`
- el usuario quiere v1.4 con mas red y analisis de patrones, noticias, conferencias, ventas y eventos reales
- el usuario aprobo v1.5 para reducir ruido con alertas agrupadas, cupos, descartes, anti-hype y memoria automatica

## Lecciones importantes

- Si el bot manda demasiado, el problema no es detectar menos: es rankear mejor y limitar cupos.
- Memecoins y bolsa deben tener bandejas separadas.
- El asistente debe ser read-only y controlado por chat autorizado.
- La inteligencia avanzada debe seguir siendo read-only y no convertirse en ejecucion de operaciones.
