# RESUMEN COMPLETO — Trading Alert AI (todo el proyecto en un documento)

> **Actualizado: 2026-06-11.** Este documento es autocontenido: leyéndolo, cualquier
> persona (o cualquier sesión nueva de Claude, con el modelo que sea) entiende QUÉ es
> el proyecto, DÓNDE está, POR QUÉ está así, y QUÉ sigue. Para profundizar:
> `CONTEXTO_MAESTRO_v3.5.0.md` (arquitectura), `CHANGELOG.md` (historia por versión),
> `PROXIMOS_PASOS.md` (roadmap + reglas), `GO_LIVE_RUNBOOK.md` (camino a real-money),
> `HANDOFF.md` (migración de máquina).

---

## 1. Qué es

**Bot de trading algorítmico local y gratis** (Python 3.12, Windows, Lenovo del user).
Detecta oportunidades (memecoins / acciones US / forex / oro), decide con un **strategy
router** (5 estrategias swing + 2 scalping), hace **paper trades** y ejecuta órdenes a
**MT5 demo**. Tiene capas de IA local (Ollama, ML XGBoost) que son siempre
**SUBTRACTIVAS**: vetan, explican, registran, proponen — **jamás abren una orden**.

**Real-money está BLOQUEADO por diseño (HARDCODED)** y así sigue hasta que los gates de
`/readiness` estén verdes. El user lo pidió varias veces (incluso "solo 300 MXN"); la
respuesta acordada es el `GO_LIVE_RUNBOOK.md`, no el flag. Razones: el dinero real no
entrena mejor que el demo (misma data, mismos outcomes), el apalancamiento hace que
"300 pesos" no sea la pérdida máxima, y no hay edge probado.

## 1.5 Qué hace, paso a paso (el ciclo, cada ~2-3 minutos)

1. **Recolecta**: precios y datos de memecoins (DexScreener/GeckoTerminal), acciones US,
   forex y oro (Yahoo/MT5), noticias, filings SEC, contexto macro (VIX/DXY) y el
   calendario económico (eventos high-impact).
2. **Analiza y puntúa**: cada candidato pasa por análisis técnico (RSI, ATR, MACD,
   patrones), scoring (0-100), chequeos de seguridad (para memecoins: honeypot, liquidez)
   y los pesos aprendidos de resultados pasados.
3. **Alerta**: lo mejor del ciclo te llega por Telegram (con caps por categoría y dedup
   para no spamear).
4. **Decide trades**: el strategy router elige la estrategia (breakout, mean reversion,
   session breakout, etc.) y abre **paper trades** (apuestas simuladas que registran
   todo: entrada, stop, target, features técnicos al momento de entrar).
5. **Ejecuta a MT5 demo** SOLO los paper trades de forex que sobreviven TODA la cadena
   de gates (§5). Memecoins y acciones quedan paper-only siempre.
6. **Gestiona lo abierto**: cada ciclo revisa las posiciones (trailing, breakeven
   post-TP1, salida por tiempo, por invalidación), reconcilia contra MT5 (cierra
   huérfanas, sincroniza stops) y registra el camino de R (exit shadow).
7. **Aprende**: al cerrar trades mide el R realizado neto de costos (excluyendo
   artifacts), refresca la expectancy por estrategia y por slice (sesión/dirección),
   ajusta pesos, y reentrenaría el ML si hubiera muestra (≥400).
8. **Reporta**: resumen diario al cierre NY, avisos de apertura/cierre, y responde
   tus comandos de Telegram en cualquier momento.

En una frase: **observa los mercados, apuesta en simulado, ejecuta a demo solo lo que
pasa todos los filtros, gestiona y mide cada posición con honestidad brutal, y aprende
de los resultados — sin tocar jamás dinero real.**

## 2. Estado EXACTO al 11-jun-2026

| Qué | Estado |
|---|---|
| Versión | **v3.5.0**, todo mergeado a `main` y deployado |
| Tests | **572 verdes** |
| Bot | Corriendo en la Lenovo vía **`.\start_bot.ps1`** (con contraseña, opt-in) |
| Balance demo | ~$88,8xx (cuenta MetaQuotes-Demo) |
| Protecciones activas (`.env` del user) | calendar gate ✓, cap USD \|3\| ✓, cooldown 60 min ✓, exit shadow ✓ (~6.000 muestras) |
| Data hacia Fase D | **~70/400** trades limpios con features técnicos |
| Real-money | BLOQUEADO; `/readiness` = NO LISTO |
| Seguridad | Auditoría 2026-06-11 **limpia** (ver §7) |

## 2.5 Serie v3.6.0 — Backtest Replay Harness — EN CURSO (actualizado 2026-06-14)

> El 12-jun se decidió una rama nueva: el **Backtest Replay Harness** (reproduce
> la historia de MT5 barra por barra con las estrategias REALES, mide R neto con
> honestidad brutal — para que el backtest DESCUBRA y el demo CONFIRME). Fuente de
> verdad: `ESPEC_BACKTEST_REPLAY_v1.md` (el cómo, sesiones S1→S5) y
> `MAPA_DE_EDGE_Y_RUTA.md` (el porqué + la ruta v3.6→v3.8). Esto NO toca el bot
> vivo, NO cuenta para `/readiness` ni para los 400 de Fase D, y vive en tablas
> `backtest_*` separadas.

| Sesión | Qué | Estado |
|---|---|---|
| **S1** | Tablas `backtest_*` + repository CRUD + `historical_loader` + tests | **HECHA y en `main`** (commit `caff8c1`) |
| **S2** | `context_builder` + `regime_filter` + canario anti-look-ahead + tests | **HECHA y en `main`** (commit `c6efe6b`; +21 tests) |
| **S3** | `trade_simulator` (long/short/gaps/costos/slippage, B1–B13) + tests | **HECHA y en `main`** (commit `307f5d3`; +21 tests, números dorados a mano) |
| **S4** | `replay_harness` + `report` + primer run Modo A real + tests | **HECHA y en `main`** (commit `c03c26e`; +9 tests) |
| **S5** | `trend_following_d1` + veredicto §11 + bump **v3.6.0** + CHANGELOG/README/.env | **HECHA en branch** (lista para merge; +13 tests) |

**Primer run Modo A real (S4, 14-jun)** — 4 estrategias existentes × 8 símbolos D1, **6.798 trades** simulados sobre décadas de historia en ~3 min. **Veredicto: las 3 que dispararon NO PASAN** (§11) — `mean_reversion` −0.123R (PF 0.60, n=1026), `momentum` −0.004R (~plano, n=5757), `breakout` +0.043R pero n=15. `forex_session_breakout` no disparó (en D1 `macro=None`, B11). Exactamente para lo que existe el harness: **descartó en minutos lo que el demo tardaría meses**, y confirmó que el edge no está en estas estrategias sobre D1. El reporte vive en `exports/backtest_1/` (gitignored).

**Profundidad histórica REAL medida el 14-jun** (loader corrido contra MT5 demo,
cache en SQLite): D1 con décadas — EURUSD/USDCHF/USDJPY **desde 1971**, AUDUSD/
GBPUSD/USDCAD/NZDUSD desde 1993-94, XAUUSD desde 2004 (5.654–14.300 barras). H1
**topado en 50.000 barras** por símbolo (~desde may-2018; es el límite del broker,
no truncamiento). **Caveat de honestidad:** el D1 pre-1999 de EUR es sintético
(el euro no existía); tratar esa franja con escepticismo (el ×1.25 de costos ya
empuja a lo conservador). El motor D1 (trend-following) tiene la profundidad que
necesita; el régimen-slicing va a poder responder si el +R del session breakout
era estructura o coyuntura.

**Veredicto S5 — `trend_following_d1` (hipótesis congelada Donchian D1):** avg **+4.7R**
que **parece edge enorme pero es un ARTEFACTO** — un solo trade de **+3724R** sobre data
sintética pre-1999 de USDCHF carga el **91% del P&L** (mediana real −1.03R; GBPUSD −0.26R).
El veredicto §11 lo **RECHAZA** bien (drawdown 57.5R > 25R; consistencia 58% < 60%) y la
nueva métrica de **concentración** del reporte lo grita. **NO PASA. NO va a Modo B.**
Es justo lo que el harness existe para hacer: atrapar el falso positivo seductor en vez
de creerle. Conclusión de la serie: **el edge no está en estas estrategias sobre D1.** El
camino sigue (COT, instrumentos descorrelacionados) en `MAPA_DE_EDGE_Y_RUTA.md`.

**Tests:** 572 (v3.5.0) → 593 (S1) → 614 (S2) → 635 (S3) → 644 (S4) → **657 (S5)**, todos verdes por conteo.

## 3. La verdad de fondo (la filosofía del proyecto)

1. **El cuello de botella es DATA, no código.** No hay edge probado: el único +R agregado
   (`forex_session_breakout` +0.38R, n=86) lo carga **el lado short de un régimen** (shorts
   +1.81R vs longs −0.31R) — se da vuelta cuando el mercado gira. Quedó demostrado en vivo:
   el 9-jun ganó +$312 y el 10-jun el mismo libro perdió.
2. **El −11% histórico del demo fue un BUG, no estrategia**: el feedback-loop/instant-kill
   de mayo (~746 artifacts, corregidos en v2.6.7–v2.7.1). Limpio de artifacts: ~−2% desde
   el inicio; desde el baseline 2026-06-03, ~plano (+0.17%). `/performance` lo mide.
3. **El LLM/ML no crean edge** — filtran, explican y protegen. La "potencia" tipo
   IA-grande no compra rentabilidad: un bot simple CON edge le gana siempre a un bot
   genio SIN edge. El edge sale de data + research, validado fuera de muestra.
4. **Todo se mide antes de creerse** (anti-autoengaño): gates que solo degradan a paper,
   shadow modes que simulan antes de activar, exclusión de artifacts a query-time.

## 4. Qué se construyó (serie v3 — sesiones 8 al 11 de junio de 2026)

| Versión | Qué | Estado |
|---|---|---|
| v3.2.0 | **Fase C — ContinuousLearner**: lección LLM por trade cerrado → tabla `trade_lessons`; agrupa repetidas y PROPONE por Telegram (no aplica) | Código sano; **OFF en la Lenovo por hardware** |
| v3.3.0 | **`/performance`** (rendimiento desde baseline limpio post-bug, no falsea el balance) + **`/readiness`** (los 5 gates hacia real-money, veredicto honesto) | Activo |
| v3.3.1 | Caché TTL + cooldown 429 para GeckoTerminal (mata el spam de rate-limit) | Activo |
| v3.4.0 | **Exit shadow**: registra el camino de R de cada trade abierto (`trade_r_samples`) y **`/exit_analysis`** simula un trailing sobre el camino REAL (arma en +1R, excluye scalps/partial/mid-life) vs la salida real. Hallazgo: forex/oro NO tienen trailing efectivo (usan params de memecoin, activación +50% inalcanzable) | **Registrando** (~6k muestras) |
| v3.5.0 | **Calendar gate** (conecta `is_safe_window` que estaba HUÉRFANO — bug real: el 10-jun abrió USDCAD 18 min antes del BOC que estaba en su propia DB) + **cap de exposición USD** (`/exposicion`; el 10-jun 7 posiciones eran UNA apuesta long-USD y un movimiento las barrió juntas) | **Activos** |
| — | `GO_LIVE_RUNBOOK.md` (camino a real-money) + `start_bot.ps1` (contraseña de arranque) + auditoría de seguridad | Hecho |

Antes de esta serie (resumen): v2.7.0 midió honesto (realized-R + promotion gate),
v2.8.0 edge slicing, v2.9.0 capa ML XGBoost (dormida hasta 400 trades), v2.10–v3.1
la capa LLM local completa (asesor, veto ensemble, resumen diario).

## 5. Cadena de seguridad de una orden (cómo NO se pierde plata por un bug)

Una orden a MT5 demo solo sale si pasa TODO esto (cada gate solo puede DEGRADAR a paper):
```
reglas de estrategia → risk manager (caps, cooldown 60min) → promotion gate
(expectancy probada) → ML gate (dormido <400) → ensemble LLM veto (off) →
calendar gate (evento high-impact cerca → paper) → cap USD (concentración → paper)
→ mt5_demo_trader (ÚNICO archivo con order_send, validaciones demo-only)
```
Más: kill-switch diario, reconciler de huérfanas, dedup, y real-money hardcoded OFF.

## 6. Operación diaria (lo que hace el user)

- **Arrancar**: `cd C:\Users\LENOVO\tradingalertaIA` → `.\start_bot.ps1` (pide contraseña).
- **Una sola máquina a la vez** contra la cuenta MT5 demo.
- **Comandos Telegram**: `/health` (versión), `/performance` (cuenta limpia),
  `/readiness` (gates a real-money), `/exit_analysis` (¿trailing ayuda?), `/exposicion`
  (apuestas al dólar abiertas), `/expectancy`, `/edge`, `/market` (LLM, ~50s), `/porque_perdi`.
- **El LLM local es LENTO en esta máquina** (~50s/respuesta, corre en CPU): es normal,
  no es un bug. Por eso ContinuousLearner está OFF acá.

## 7. Seguridad (auditoría 2026-06-11)

✅ Telegram autoriza por chat_id exacto (nadie más puede dar comandos) · `.env` JAMÁS
commiteado · `LogRedactor` enmascara el token en logs · SQL 100% parametrizado · sin
eval/exec/shell=True · timeouts en toda la red · repo privado · contraseña de arranque
(SHA-256 en `.env`, opt-in). Menores aceptados: email personal en un doc de obsidian
(repo privado); `pickle.load` de modelos locales. La protección real de los secretos:
contraseña de Windows + BitLocker.

## 8. Roadmap — qué sigue y sus GATES (no negociables)

1. **AHORA (dos frentes en paralelo):** (a) **dejar correr** el libro vivo — la data
   (70→400) es lo único que destraba Fase D; (b) **serie v3.6.0 — Backtest Replay
   Harness** (ver §2.5): el código activo, para que el backtest descubra/descarte
   en horas lo que el demo tardaría meses. Van juntos sin pisarse: el harness no
   toca el ciclo vivo.
2. **En días**: `/exit_analysis` con muestra → si delta +R robusto, activar trailing de
   forex CON evidencia (cambiar los params de `lifecycle_manager` para forex).
3. **Fase D — AdvancedPredictor** (LightGBM+RF+calibración sobre el XGBoost): GATE ≥400
   trades limpios con features. EXTENDER `ml_predictor.py`, no reemplazar.
4. **Fase E — StrategyMutator** (auto-evolución: propone variante, paper ≥5 días,
   promueve solo si gana): GATE ≥1 estrategia R+ neto + 3 meses de data.
5. **Real-money**: `GO_LIVE_RUNBOOK.md` — 5 gates verdes en `/readiness` + broker
   micro + sizing reconstruido + audit del camino real + decisión explícita del user.

## 9. Reglas inamovibles (para cualquier sesión futura)

- `ENABLE_REAL_TRADING=false` **HARDCODED**. No desbloquear aunque el user lo pida
  directo — mostrar `/readiness` y el runbook. (Ya lo pidió 3+ veces; está en la
  memoria de Claude con el razonamiento completo.)
- `order_send` SOLO en `mt5_demo_trader.py`. No tocar ese archivo ni `mt5_reconciler.py`.
- LLM/ML **SUBTRACTIVOS**: vetan/degradan, jamás fuerzan ni habilitan.
- Todo lo nuevo: **opt-in OFF + soft-fail** (apagado o roto = bot idéntico).
- **572 tests verdes siempre**. Settings nuevos → sincronizar `_settings()` de
  `test_score` Y `test_alert_rules`. Cada módulo nuevo trae su test file.
- **Versionado**: patch (v3.5.1) para fixes, minor (v3.6.0) solo features reales,
  sin saltar números.
- Nunca leer/mostrar el `.env` real. Nada de LLM en el hot path del ciclo (hardware).

## 10. Lecciones de proceso de esta sesión (para no repetir errores)

- PowerShell 5.1 lee `.ps1` sin BOM como ANSI → scripts en **ASCII puro** (sin ñ/—).
- `pytest | tail` enmascara el exit code → verificar el **conteo**, no el exit.
- Archivos de mensaje de commit van **FUERA** del repo (`$TEMP`) — `git add -A` los coló 2 veces.
- El user mergea con `git merge claude/<branch>` + `git push origin main` (no usa PRs web).
- Los "techos optimistas" (mfe/mae) mienten: simular sobre el camino real, con activación
  y exclusiones, o el análisis recomienda cambios equivocados.

## 11. Prompt para arrancar un chat nuevo (copiá/pegá)

```
Retomamos Trading Alert AI (bot de trading algorítmico LOCAL, Python 3.12, Windows).
Estado: v3.5.0, main, 572 tests verdes, corriendo en esta máquina (Lenovo) vía
.\start_bot.ps1. Protecciones activas: calendar gate, cap USD, exit shadow registrando.

Leé en este orden ANTES de tocar nada: RESUMEN_COMPLETO.md (todo el proyecto en uno),
PROXIMOS_PASOS.md (qué sigue + reglas), CONTEXTO_MAESTRO_v3.5.0.md (arquitectura),
CHANGELOG.md, y GO_LIVE_RUNBOOK.md (camino a real-money).

Reglas inamovibles: real-money BLOQUEADO (ENABLE_REAL_TRADING=false HARDCODED) hasta
que /readiness esté verde; order_send solo en mt5_demo_trader.py; LLM/ML SUBTRACTIVOS;
todo opt-in OFF + soft-fail; mantener 572 tests verdes; sincronizar los _settings() de
test_score y test_alert_rules al tocar Settings; versionado patch/minor sin saltos.
Hardware: GPU chica, nada de LLM en el hot path (~50s/gen).

La verdad de fondo: el cuello de botella es DATA (70/400), no código. El único +R es
régimen-short, no edge durable. Dejar correr; Fase D/E solo con sus gates.

Decime qué querés hacer: (A) revisar la data (/performance, /readiness, /exit_analysis,
/exposicion); (B) si /exit_analysis da delta +R robusto, activar el trailing de forex
con evidencia; (C) Fase D si llegamos a 400; (D) otra cosa.
```

---

*Construido entre el user y Claude, con una regla por encima de todas: medir antes de
creer, proteger antes de arriesgar, y decir la verdad aunque no sea la respuesta que
se quiere escuchar.*
