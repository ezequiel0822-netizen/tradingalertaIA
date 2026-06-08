---
tags: [fundamentos, identidad, vision]
version: v2.7.0
updated: 2026-05-30
---

# Cerebro del Proyecto

> [!quote] Esencia
> Sistema local de monitoreo, aprendizaje y trading controlado en demo. Vigila memecoins, cripto, bolsa US, forex y oro.

---

## Identidad

Trading Alert AI es un bot algoritmico que corre **local en Windows** (Python 3.12 + PowerShell + venv). El usuario lo opera desde Telegram y monitorea via consola + dashboard Streamlit.

## Objetivo

Detectar eventos interesantes, filtrar ruido, guardar historial, mandar pocas alertas de alta calidad por Telegram, **medir su propio desempeno en P&L realizado neto de costos**, y probar estrategias en paper trades + MT5 demo bajo reglas estrictas.

## Principio central

> [!danger] La linea no se cruza
> El sistema **no debe actuar en mercados reales** bajo ningun escenario. Puede simular paper trades y operar MT5 demo bajo reglas estrictas. Real-money trading sigue **PROHIBIDO** y bloqueado por design (`ENABLE_REAL_TRADING=false` HARDCODED).

## Flujo mental del sistema

1. **Recolectar** datos publicos (9 collectors paralelos)
2. **Normalizar** candidatos
3. **Evaluar** riesgo (GoPlus, scoring, IA Pro)
4. **Calcular** score
5. **Estimar** posible subida y caida
6. **Guardar** historial
7. **Rankear** candidatos
8. **Enviar** solo lo mejor segun cupos
9. **Responder** preguntas basicas por Telegram (40+ comandos)
10. **Evaluar** resultados historicos (horizonts 1h/6h/24h/7d)
11. **Aprender** que features ayudan o perjudican (drift + realized-R)
12. **Simular** setups en papel sin operar real
13. **Preparar y ejecutar** ordenes en MT5 demo solo si pasan los controles (incluye promotion gate v2.7.0)
14. **Separar** aprendizaje swing vs scalping
15. **Reconciliar** posiciones MT5 (cierra huerfanas, sync SL) cada ciclo
16. **Frenar** estrategias con edge negativo PROBADO (shadow mode)

---

## Capacidades actuales (v2.7.0)

### Deteccion y analisis

- Memecoins y tokens nuevos (incluye early pools)
- Pools trending y tokens boosted
- Riesgo de contrato con GoPlus (cripto)
- Bolsa con watchlist ampliada de acciones/ETF (22 simbolos)
- Forex/oro con MT5 reader + validacion de simbolos
- Dashboard Streamlit (9 secciones)
- Asistente Telegram con 40+ comandos
- Analisis tecnico OHLCV (RSI, MACD, ATR, Bollinger, S/R, multi-tf M15+H1)
- Noticias/eventos publicos (Yahoo RSS)
- IA Pro (setup, sesgo, confianza, riesgos, checklist)
- Filings SEC recientes (acciones)

### Aprendizaje

- Learning Engine: outcomes + lecciones + paper trades + horizonts
- Separacion swing vs scalping
- Realized-R neto de costos por estrategia (v2.7.0)
- Tabla `strategy_performance` refrescada cada ciclo
- Learned weights aplicados a scoring
- Learning gate (gate por feature, ahora activable sobre realized-R en Fase 2b)

### Trading

- Trader engine swing con portfolio, risk manager, kill-switch, lifecycle
- MT5 demo execution con confirmacion manual O auto-confirm opt-in
- Promotion gate (v2.7.0): no manda a MT5 estrategias con edge negativo probado
- MT5 Reconciler (v2.6.7): cierra huerfanas + sync SL post-trailing
- Scalping engine M1 en thread dedicado (opt-in, kill-switch propio)
- Multi-strategy scalping: breakout + mean_reversion (v2.6.6)
- size_notional con MT5 real (v2.6.8)
- Per-symbol cooldown anti-feedback-loop (v2.6.8)
- Cierre total demo desde Telegram (`/demo_close_all`)
- Salud operativa (`/health`)
- Expectancy real por strategy (`/expectancy`)
- Learning gate preview (`/gate_preview`)

### Infra

- DB local fuera de iCloud (v2.7.0)
- Memoria Obsidian automatica
- CSV export
- Macro context (VIX/DXY/SPY + regime + sesion FX)
- Calendar economic (ForexFactory)

---

## Lo que NO hace (deliberado)

- **No** ejecuta en real-money (HARDCODED off)
- **No** trade memecoins en MT5 (solo paper/lab)
- **No** modifica `.env` por su cuenta
- **No** usa ML profundo (LSTM, transformers) — sobre-ingenieria
- **No** usa Reinforcement Learning — fragil para trading
- **No** integra con TradingView (duplica data)
- **No** activa learning_gate sin data limpia (preview reveló bloquearia ~todo)

---

## Estado actual

Ver [[14 - Estado Actual v2.7.0]] para snapshot completo (version, git, balance, bot_state).

Resumen: **v2.7.0**, main en `0cc27d6`, 397 tests verdes, balance MT5 ~$88,585, DB fuera de iCloud, kill switch CLEAR.

---

## Links relacionados

- [[02 - Reglas de Seguridad]] - lo inamovible
- [[03 - Versiones y Cambios]] - como llegamos aca
- [[19 - Arquitectura del Sistema]] - como esta estructurado
- [[07 - Ideas y Proximos Pasos]] - donde vamos
