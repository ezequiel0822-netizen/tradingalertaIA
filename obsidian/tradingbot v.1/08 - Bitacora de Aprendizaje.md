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

## 2026-05-18

- v1.6.0 shipped: aprendizaje por horizonte (1h/6h/24h/7d), MFE/MAE por ventana, backtester, reporte semanal Obsidian. 38 tests verdes.
- v1.7.0 shipped: paper trading con MFE/MAE en vivo, trailing stops, SL/TP por ATR. Pesos aprendidos (OFF por default), learning gate (OFF por default), foundation forex/oro. 64 tests.
- **Pivot importante**: el usuario decidio que el bot pase de "alerter" a "trader engine autonomo". Memecoins quedan como lab de aprendizaje (no Telegram, no paper trades). Telegram suma reporte + control + alertas. Version bump a v2.0.0. MT5 Python read-only adapter.
- v2.0.0 shipped: Phase 2.5 — strategy router con 4 estrategias (breakout/mean_reversion/momentum/news_catalyst), portfolio manager, risk manager con kill-switch, position sizer, macro context (sesiones FX), lifecycle manager (time exit + partial close + invalidation), trade reporter, comandos `/portfolio`, `/halt`, etc. 117 tests verdes.
- **Decision MT5**: el usuario va a conectar cuenta demo de MT5. Autorizado demo trading para Phase 5 (cuando llegue). Real-money sigue prohibido.

## 2026-05-19

- v2.1.0 shipped: Phase 2.6 security hardening. Audit del repo encontro 14 hallazgos (0 criticos, 2 altos, 6 medios, 6 bajos). Fixes aplicados: `Settings.__repr__` mascarado, `safe_path` helper, `LogRedactor`, `safe_json`, `init_db` resiliente, `/halt` clamp, position sizer cap, score sanitize negatives, deps pinneadas. 135 tests verdes.
- **Decision proximas fases**: el usuario pidio hacer Phase 3 (forex price-action) **y** Phase 3.5 (LLM integration con Claude API) **juntas**.
- **Concepto Phase 6**: el usuario propuso "evolucion natural" — si una estrategia pierde, muere; si gana, sobrevive. Aceptado conceptualmente, con protecciones contra overfitting/curve-fitting/regime change (no all-or-nothing, sample size minimo, periodos largos).
- v2.2.0 shipped: Phase 3 (forex price-action + macro/calendar/multi-tf + dashboard avanzado + alertas forex/gold) **y** Phase 3.5 (Claude API integration soft-fail con throttle/cache/cost-cap) ejecutadas juntas. Audit del worktree antes de empezar: 7 commits limpios, 129 archivos, 12 notas Obsidian sincronizadas. Decisiones del usuario: ForexFactory para calendario, Haiku 4.5 como modelo Claude, alertas forex/gold con learning gate forzado. 28 tests nuevos. Total 163 verdes.
- **Bug encontrado en smoke run post-v2.2.0**: macro_collector y economic_calendar_collector estaban con tests verdes pero NO wireados en `run_once`. Fix en commit `44c552f`. Lección: tests unitarios no detectan wiring missing — agregar tests de integración smoke en próximas fases.
- v2.3.0 shipped: Phase 4 (validación MT5 ICMarkets + walk-forward backtester out-of-sample + data quality monitor + CSV export). Cuenta demo ICMarkets confirmada lista por usuario el 2026-05-19. Decisiones del usuario: ICMarkets como broker, instalar MetaTrader5 + anthropic packages, walk-forward básico (sin parameter tuning — eso es Phase 6). 34 tests nuevos. Total 197 verdes.
- Packages instalados en `.venv`: MetaTrader5 5.0.5735, anthropic 0.103.1. Soft-fail mantenido por si user reinstala el venv.
- **Próximo: Phase 5** — `order_send` a demo MT5 con kill-switch + mandatory SL + 1% riesgo por trade.
- Pivot conceptual reforzado: el "AI" del nombre ahora es real cuando se enchufa la Claude API key — el bot razona sobre noticias y entiende preguntas naturales en Telegram. Sin la key, sigue siendo bot algoritmico con feedback estadistico (soft-fail completo).

## Lecciones importantes

- Si el bot manda demasiado, el problema no es detectar menos: es rankear mejor y limitar cupos.
- Memecoins y bolsa deben tener bandejas separadas.
- El asistente debe ser read-only y controlado por chat autorizado.
- La inteligencia avanzada debe seguir siendo read-only hasta que se autorice explicitamente trading demo.
- **Trading retail rentable NO viene de modelos ML profundos**, viene de risk management + estrategias robustas + disciplina + data de calidad.
- Cualquier backtest con yfinance miente (spreads ficticios). MT5 directo es la fuente real.
- Phase 2.5 cerro la deuda arquitectonica antes de que pese — sin portfolio/risk/sizing no se puede ir a demo trading.
- Cada nueva superficie (MT5 credentials en v2.0.0) requiere review de seguridad antes de seguir agregando (v2.1.0 hardening).
- "Evolucion" de estrategias es viable pero peligrosa: requiere min sample size (50+ trades), periodos largos (3+ meses), proteccion contra curve fitting.

## Pivots de identidad del proyecto

| Version | Identidad | Rol |
|---|---|---|
| v1.x | Alerter | Avisa oportunidades, humano opera |
| v2.0+ | Trader engine simulado | Decide entradas/salidas en paper |
| Phase 5 | Trader demo MT5 | Opera demo MT5 con risk controls |
| Futuro | Trader real? | Solo con autorizacion explicita nueva |
