# Plan de Mejoras — Trading Alert AI → v3.17.0 (propuesta)

> Objetivo: subir la **calidad** de las señales y la selectividad,  
> no inventar edge mágico. Apuntar a win-rate ≥ 58-65 % con expectancy ≥ +0.10R  
> mediante menos operaciones, pero mejores.

Fecha de propuesta: 2026-10-10  
Basado en: v3.16.0 + ledger de 27 familias (0 operables) + análisis completo del repo.

---

## Principios de esta mejora

1. **No se toca real-money** (sigue hardcodeado bloqueado).
2. **Todo nuevo es opt-in + soft-fail**.
3. **Downward-only**: los nuevos filtros solo pueden bajar a paper o descartar, nunca habilitar más operaciones.
4. **Menos es más**: el problema actual es ruido + costos, no falta de señales.
5. **Datos limpios primero**: arreglar integridad de precio y cache antes de optimizar estrategias.

---

## Mejoras priorizadas (orden de impacto)

### P0 — Críticas (hacer YA, 1-2 días)

| # | Mejora | Por qué | Archivos afectados |
|---|--------|---------|--------------------|
| 1 | Activar `PAPER_PRICE_FROM_MT5=true` + warm-start limpio del agente | Elimina R falsos de oro y forex mezclado | `.env` + script warmstart |
| 2 | Subir `STRATEGY_MIN_CONFIDENCE` de 60 → 72-75 | Menos señales basura | `.env` / settings |
| 3 | Subir `ALERT_SCORE_THRESHOLD` y readiness | Menos alertas de baja calidad | `.env` |
| 4 | Activar todos los gates de protección (calendar, regime, VWAP, USD cap, exit shadow) | Ya existen, solo estaban OFF | `.env` |
| 5 | Bajar `MAX_OPEN_TRADES_TOTAL` a 3-4 | Forzar selectividad | `.env` |

### P1 — Alto valor (esta semana)

| # | Mejora | Descripción |
|---|--------|-------------|
| 6 | **News Web Enhancer** (nuevo módulo) | Busca noticias frescas + sentimiento simple (sin API de pago). Mejora el filtro de `news_catalyst` y el score de acciones. |
| 7 | **Quality Gate** (nuevo) | Capa extra antes de paper/MT5: exige confluencia mínima (régimen + score + noticias + ATR razonable). |
| 8 | Completar `requirements.txt` | Añadir dependencias soft que el código ya usa (yfinance, ta, etc.) para evitar ImportError silenciosos. |
| 9 | Fix `realized_pnl_today` (ignora TP1 parcial) | Hacer que el P&L del día cuente la mitad cobrada en TP1. |
| 10 | Defaults más conservadores en settings | Cambiar defaults de confianza/score hacia arriba (backward-compatible con env). |

### P2 — Medio plazo (2-4 semanas)

| # | Mejora | Descripción |
|---|--------|-------------|
| 11 | Refresh del cache D1 de MT5 | Script + lógica para que el loop vivo refresque D1 (actualmente congelado desde 2026-06-15). |
| 12 | Trailing stop específico para forex/oro | Los params actuales son de memecoin (+50 % activación). Crear params propios. |
| 13 | Modo "Strict / High-Quality" | Un solo flag `ENABLE_STRICT_MODE=true` que active todos los filtros P0+P1 de una vez. |
| 14 | Mejor logging de descartes | Saber exactamente por qué se descarta cada candidato (útil para aprender). |
| 15 | Limpieza de código memecoin/scalping | Mover a carpeta `legacy/` o eliminar paths muertos para reducir ruido mental. |

### P3 — Research (no tocar bot todavía)

- No re-abrir las 27 familias cerradas.
- Esperar checkpoint COT (2026-12-07) y evaluaciones del agente/Kronos (2027).
- Si se quiere probar algo nuevo: **solo** hipótesis con pre-registro + datos no vistos + t ≥ 2.50.

---

## Meta de performance realista

| Métrica | Actual (aprox.) | Objetivo v3.17+ |
|---------|-----------------|-----------------|
| Win rate paper | ~45-50 % (estimado) | ≥ 58-65 % |
| Expectancy neta | ≤ 0 o negativa | ≥ +0.10R a +0.20R |
| Trades / semana | Muchos | Menos (calidad > cantidad) |
| Max DD diario | Controlado | Mantener < 3 % |

---

## Cómo aplicar este plan

1. Copia los archivos de `config/`, `new_modules/` y `patches/` a tu repo.
2. Aplica el `.env` recomendado (archivo `config/env_recomendado_calidad.txt`).
3. Reinicia el bot con `.\start_bot.ps1`.
4. Observa 1-2 semanas solo paper/demo.
5. Mide con `/expectancy`, `/edge`, `/agente`, `/performance`.

---

## Qué NO se hace en esta mejora

- No se desbloquea real-money.
- No se inventan estrategias nuevas sin pre-registro.
- No se sube el riesgo por trade.
- No se activa ML ni learned weights todavía (siguen sin edge demostrado).
