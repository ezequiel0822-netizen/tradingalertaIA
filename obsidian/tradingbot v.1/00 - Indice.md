---
tags: [indice, navegacion, proyecto/trading-alert-ai]
version: v2.7.1
updated: 2026-06-03
---

# Trading Alert AI - Indice del Vault

> [!info] Version actual
> **v2.7.1** | main = origin/main = `fd59478` | 402 tests verdes | Balance MT5 $88,635 USD

> [!quote] Identidad del proyecto
> Bot de trading algoritmico LOCAL en Python 3.12. Detecta oportunidades en memecoins / acciones US / forex / oro, decide con strategy router (5 swing + 2 scalping), opera paper trades simulados y envia ordenes a MT5 demo (MetaQuotes-Demo). Real-money trading **bloqueado por design**.

---

## Mapa por area

### Fundamentos

- [[01 - Cerebro del Proyecto]] - identidad, objetivo, flujo mental
- [[02 - Reglas de Seguridad]] - lo inamovible
- [[14 - Estado Actual v2.7.0]] - version, balance, git, bot_state

### Configuracion y operacion

- [[04 - Configuracion Operativa]] - todas las env vars + defaults v2.7.0
- [[12 - Guia de Uso]] - como arrancar, validar, debugear
- [[22 - Setup y Operacion]] - comandos PowerShell, pytest, queries SQL

### Telegram

- [[06 - Telegram Assistant]] - overview del asistente
- [[13 - Comandos Telegram]] - referencia completa de los 40+ comandos

### Inteligencia y aprendizaje

- [[05 - Alertas y Scoring]] - sistema de scoring + filtros
- [[10 - Learning Engine]] - outcomes, lessons, weights, gate
- [[17 - Promotion Gate y Cost Model]] - v2.7.0 protege capital
- [[18 - Realized R y Aprendizaje Honesto]] - Fase 2b (learning sobre P&L real)
- [[08 - Bitacora de Aprendizaje]] - hallazgos crudos del usuario

### Estrategias

- [[15 - Estrategias]] - 5 swing + 2 scalping + stats reales

### Arquitectura

- [[19 - Arquitectura del Sistema]] - file structure + modulos + data flow
- [[20 - Schema de Base de Datos]] - 18 tablas + indexes + migraciones
- [[21 - Decisiones Arquitectonicas]] - por que las decisiones

### Historia

- [[03 - Versiones y Cambios]] - evolucion v1.0 -> v2.7.0
- [[16 - Bugs Resueltos]] - saga del 27-may, root causes y fixes

### Donde estamos y donde vamos

- [[23 - Fases del Proyecto]] - **mapa visual completo + AQUI ESTAS marker**
- [[07 - Ideas y Proximos Pasos]] - roadmap detallado
- Phase 6+ requiere data limpia + ≥1 strategy con R positivo

### Auto-generado por el bot (no editar)

- [[09 - Memoria Automatica]] - resumenes de ciclos
- [[11 - Reporte Semanal]] - reporte semanal

---

## Regla de oro

> [!danger] Lo que NUNCA va en este vault
> - tokens de Telegram
> - chat IDs reales
> - API keys
> - seed phrases
> - private keys
> - passwords
> - credenciales
>
> Los secretos viven SOLO en `.env`.

---

## Quick links externos

- Master context tecnico completo: `C:\Users\xxxv4\iCloudDrive\tradingalertaIA\CONTEXTO_MAESTRO_v2.7.0.md` (incluye delta v2.7.1 al final, seccion 11)
- CHANGELOG codigo: `C:\Users\xxxv4\iCloudDrive\tradingalertaIA\CHANGELOG.md`
- GitHub: https://github.com/ezequiel0822-netizen/tradingalertaIA
