# ESPEC — Backtest Replay Harness v1 (propuesta v3.6.0)

> **Estado: PROPUESTA — pendiente de implementación.** Preparado el 2026-06-12 entre
> el user y Claude. Este documento es la fuente de verdad para implementar el harness
> de backtesting por replay: reproducir la historia de mercado barra por barra, aplicar
> las estrategias REALES del bot, y medir R neto de costos con honestidad brutal — para
> que el backtest descubra y el demo confirme. Se implementa en Claude Code siguiendo
> el plan de sesiones del §15. El prompt de arranque está en el §19.

---

## 0. Cómo usar este documento

1. Guardar este archivo en la raíz del repo como `ESPEC_BACKTEST_REPLAY_v1.md` (junto a
   `RESUMEN_COMPLETO.md` y los demás docs maestros).
2. Abrir una sesión nueva de Claude Code y pegar el prompt del §19.
3. La sesión implementa en el orden del §15 (S1 → S5), con gate de verificación al
   final de cada sesión. No se avanza de sesión sin gate verde + merge del user.
4. Idioma: docs y mensajes de cara al user en español; identificadores de código en
   inglés (convención del repo).
5. Ante cualquier conflicto entre este doc y las reglas inamovibles del proyecto
   (`RESUMEN_COMPLETO.md` §9), ganan las reglas del proyecto.

## 1. Objetivo — y qué NO es

**Qué es:** un motor que reproduce la historia de MT5 barra por barra y le pregunta a
las estrategias REALES del bot (el mismo código que corre en vivo) qué habrían hecho;
simula cada trade con reglas pesimistas, le resta costos, y reporta R neto sliceado por
símbolo / sesión / dirección / año / régimen. Propósito: **invertir el descubrimiento**
— el backtest descarta en horas lo que el demo tardaría meses; la data viva pasa a
confirmar en vez de descubrir.

**Qué NO es:**

- NO cuenta para `/readiness` ni para los 400 trades de la Fase D (esos son vivos, con
  features reales capturados al entry).
- NO toca la ejecución viva: ni `mt5_demo_trader.py`, ni `mt5_reconciler.py`, ni flags
  de estrategias vivas.
- NO escribe en `paper_trades`, `strategy_performance`, `strategy_performance_sliced`
  ni ninguna tabla viva.
- NO promueve nada automáticamente: sus resultados informan una decisión humana, y aun
  aprobada, la estrategia entra al pipeline normal (paper → demo → gates vivos).
- NO es un oráculo: un backtest nunca prueba edge; solo filtra con confianza lo que no
  lo tiene.

## 2. Reglas inamovibles del harness

| # | Regla |
|---|---|
| R1 | **Reuso del código real:** el harness importa las estrategias desde `app/strategies/` y las llama por el mismo Protocol con un `StrategyContext` real. Prohibido reimplementar "versiones parecidas" — si no, se backtestea una estrategia distinta a la que corre en vivo y nada transfiere. |
| R2 | **Cero look-ahead:** en la barra N solo existe información ≤ N. Convenciones B1–B13 (§6), cada una con test propio. |
| R3 | **Pesimismo por diseño:** ante cualquier ambigüedad, la interpretación que EMPEORA el resultado. |
| R4 | **Determinista y offline:** misma data + misma config ⇒ mismo output bit a bit. Sin red, sin LLM, sin aleatoriedad dentro del loop de replay. |
| R5 | **Tablas separadas:** todo resultado vive en `backtest_*` (§5). Cero contaminación de la medición viva. |
| R6 | **Opt-in OFF + soft-fail:** `ENABLE_BACKTEST_HARNESS=false` por default; si falta data o falla algo, el bot vivo corre idéntico. |
| R7 | **Contabilidad de intentos:** cada run y cada config probada queda registrada (anti data-dredging, §10). |
| R8 | **Tests verdes siempre:** 572 actuales + ~40 nuevos ⇒ objetivo ≥ 610, verificado por CONTEO (no por exit code). |
| R9 | **Versionado:** toda la serie entra como v3.6.0 en el merge final (no bumpear por sesión parcial). |

## 3. Alcance v1 — qué estrategias entran y por qué

**DENTRO (backtesteables con honestidad — solo usan precio/volumen/técnicos):**

| Estrategia | Notas |
|---|---|
| `forex_session_breakout` | La sesión se deriva del timestamp UTC (no es look-ahead). Es la estrategia del hallazgo régimen-short: el slicing por régimen (§8) va a mostrar si su +R era estructura o coyuntura. |
| `breakout` | Técnica pura. |
| `mean_reversion` | Técnica pura. |
| `momentum` | Técnica pura (MACD + SMA + RSI). Está deshabilitada en vivo; acá se mide igual — el backtest es para saber, no para operar. |
| `trend_following_d1` | NUEVA (§9). La hipótesis con mejor prior académico. |

**FUERA (con la razón honesta):**

| Excluida | Razón |
|---|---|
| `news_catalyst` | No existe archivo histórico de noticias. Reconstruirlo "más o menos" es fabricar un backtest mentiroso. |
| Scalping M1 (`scalping_*`) | Historia M1 corta en el broker, el spread domina el resultado, y el camino intrabar en M1 no se puede simular con honestidad desde candles. |
| Memecoins | Sesgo de supervivencia fatal: los tokens muertos desaparecen de las APIs; el backtest solo vería sobrevivientes. |
| Todo lo que dependa de `learned_weights`, `ia_pro`, LLM o `news_score` | Sin registro histórico ⇒ esos campos van `None` en el contexto (B11). |

## 4. Arquitectura — archivos nuevos y reuso obligatorio

Paquete nuevo `app/backtest/` (separado de `app/learning/` a propósito: NADA de este
paquete corre en el ciclo vivo):

| Archivo | Responsabilidad |
|---|---|
| `app/backtest/__init__.py` | — |
| `app/backtest/historical_loader.py` | Extiende `mt5_historical` para traer profundidad MÁXIMA de D1 (y H1 si hay) por símbolo, cachear en SQLite y reportar el rango real disponible por símbolo. Nunca asumir profundidad: se mide y se imprime. |
| `app/backtest/context_builder.py` | Construye el `StrategyContext` en la barra N usando los módulos reales (`technical_patterns`, etc.) con ventanas que terminan en N. Campos no reconstruibles ⇒ `None` + reporte de completitud (B11). |
| `app/backtest/trade_simulator.py` | Simula la vida completa del trade según §6 (SL/TP/trailing/time-exit, gaps, dirección-aware). |
| `app/backtest/replay_harness.py` | Orquestador del run: recorre barras, llama estrategias, abre/gestiona trades simulados, escribe tablas. CLI: `python -m app.backtest.replay_harness --config <json>`. |
| `app/backtest/report.py` | Genera el reporte sliceado + veredicto contra los criterios (§11, §12). |
| `app/intelligence/regime_filter.py` | Clasificador de régimen (§8). Función pura, importable por el bot vivo a futuro. |
| `app/strategies/trend_following_d1.py` | Estrategia nueva (§9), mismo Protocol que las demás. |

**Reuso obligatorio (no duplicar):** `session_of()` de `trade_outcomes`;
`_cost_map_from_settings` de `training_engine`; el Protocol y `StrategyContext` de
`strategies/base.py`; los cálculos de `technical_patterns.py`; el patrón
`_ensure_column`/migraciones de `db.py`; el patrón repository.

**Se modifican:** `db.py` (3 tablas nuevas, mismo patrón de siempre), `repository.py`
(CRUD backtest), `settings.py` (§13 + sync de `_settings()` en `test_score` Y
`test_alert_rules` en el mismo commit), `CHANGELOG.md` / `README.md` / `.env.example`
(en S5).

**NO se modifican:** `mt5_demo_trader.py`, `mt5_reconciler.py`, `jobs.py` (v1 no
integra nada al ciclo vivo), `main.py` (el CLI es del módulo), `scalping_engine.py`.

**Paridad con vivo:** el harness aplica el mismo `STRATEGY_MIN_CONFIDENCE` que el
router vivo, para que "señal" signifique exactamente lo mismo en backtest y en
producción.

## 5. Esquema de datos (3 tablas nuevas)

- **`backtest_runs`** — una fila por corrida: `id` PK, `created_at_utc`, `git_commit`,
  `mode` (A|B), `timeframe`, `symbols` (csv), `strategies` (csv), `data_ranges_json`
  (rango REAL por símbolo), `config_json` (params completos por estrategia — los runs
  quedan autodescritos), `cost_multiplier`, `n_configs_tested`, `notes`.
- **`backtest_trades`** — una fila por trade simulado: `id` PK, `run_id` FK,
  `config_id`, `strategy`, `symbol`, `category`, `direction` (long|short),
  `signal_bar_utc`, `entry_utc`, `entry_price`, `sl_initial`, `tp_initial`, `exit_utc`,
  `exit_price`, `exit_reason` (sl|tp|trail|time|gap_sl), `bars_held`, `r_gross`,
  `cost_r`, `r_net`, `mfe_r`, `mae_r`, `session`, `regime_trend`, `regime_vol`, `year`.
- **`backtest_walkforward`** — una fila por ventana de test (solo Modo B): `run_id` FK,
  `config_id`, `train_from`, `train_to`, `test_from`, `test_to`, `strategy`, `n`,
  `avg_r_net`, `median_r_net`, `win_rate`, `max_dd_r`, `profit_factor`.

Índices: `backtest_trades(run_id)`, `backtest_trades(strategy, symbol)`. **Cero
foreign keys hacia tablas vivas.**

## 6. Convenciones de simulación (anti-look-ahead y pesimismo) — B1 a B13

Estas reglas son el corazón del harness. Cada una tiene test propio (§14).

- **B1 — Información:** la decisión en la barra N usa solo barras ≤ N. Todo indicador
  se calcula con ventanas que TERMINAN en N.
- **B2 — Entrada:** la señal se evalúa al CLOSE de N; la entrada se ejecuta al OPEN de
  N+1.
- **B3 — Intrabar ambiguo:** si una barra toca SL y TP a la vez ⇒ se asume SL primero
  (pesimista). Vale para long y short con la geometría invertida.
- **B4 — Gaps asimétricos:** si el open salta MÁS ALLÁ del SL ⇒ fill al open real
  (pérdida mayor que el SL), `exit_reason=gap_sl`. Si el open salta más allá del TP a
  favor ⇒ fill al PRECIO DEL TP (el extra NO se acredita). Pesimismo asimétrico,
  siempre.
- **B5 — Trailing solo en closes:** si el run activa trailing, se evalúa SOLO al close
  de cada barra y solo puede APRETAR (tighten-only, igual que el reconciler). Lección
  pagada del proyecto: los techos intrabar (mfe/mae) mienten.
- **B6 — Salida por tiempo:** a los K bars (param por estrategia): señal al close,
  ejecución al open siguiente (B2).
- **B7 — Dirección-aware en TODO:** para short, SL arriba / TP abajo y todos los
  chequeos invertidos. Test obligatorio que reproduce el bug histórico de shorts
  corregido en v2.7.0.
- **B8 — Costos:** `r_net = r_gross − cost_r(categoría) × BACKTEST_COST_MULTIPLIER`
  (§7), consistente con la medición viva de v2.7.0.
- **B9 — Slippage de SL:** los fills de SL (incluido gap_sl) se empeoran en
  `BACKTEST_SL_SLIPPAGE_ATR × ATR14` adicional.
- **B10 — Determinismo offline:** el replay corre solo contra el cache local; doble
  corrida con la misma config ⇒ resultados idénticos.
- **B11 — Contexto honesto:** campos del `StrategyContext` sin registro histórico
  (news, ia_pro, learned_weights, macro en v1) ⇒ `None`. El run emite un "context
  completeness report" con qué % de campos estuvo poblado. Prohibido inventar valores
  históricos.
- **B12 — Una posición por símbolo por estrategia.** Sin piramidación en v1.
- **B13 — Timestamps UTC en todo;** `session_of()` reusado de `trade_outcomes`.

## 7. Modelo de costos

- **Base:** el cost map por categoría de `training_engine._cost_map_from_settings` —
  el MISMO que usa la medición viva, para que `/expectancy` y el backtest hablen el
  mismo idioma (R, fracción del riesgo inicial).
- **Multiplicador de pesimismo:** `BACKTEST_COST_MULTIPLIER=1.25` (los spreads de 2016
  no son los de hoy; mejor pasarse de conservador).
- **Stress obligatorio:** el reporte recalcula todo a ×1.5. Si el edge muere a ×1.5,
  queda anotado en el veredicto — un edge que no sobrevive costos pesimistas no es
  edge.

## 8. Filtro de régimen — `regime_filter.py`

API: `classify(candles_d1_hasta_N) -> RegimeTags`

- `regime_trend`: `up` si `close(N) > SMA200(N)` y `SMA200(N) > SMA200(N−20)`; `down`
  espejo; `flat` en cualquier otro caso.
- `regime_vol`: percentil del ATR14(N) contra los 252 bars previos ⇒ terciles
  `low | mid | high`.
- Todo con datos ≤ N (B1). Función pura sobre el array de velas, sin estado oculto.

**Doble uso:**

1. Gate de `trend_following_d1` (§9): solo opera alineada al régimen.
2. Dimensión de slicing para TODAS las estrategias en el reporte (§12): acá se responde
   la pregunta que dejó abierta el hallazgo shorts +1.81R / longs −0.31R — si el +R de
   `forex_session_breakout` era régimen o era edge.

Mínimo de muestra por slice: 30 (misma filosofía que `EDGE_SLICE_MIN_SAMPLES`).

## 9. Estrategia nueva: `trend_following_d1` — hipótesis CONGELADA

La hipótesis se declara acá, ANTES de mirar la data (anti data-dredging). Es
deliberadamente aburrida: trend-following tipo Donchian, la familia con más evidencia
académica multi-activo y multi-década. Si ni esto muestra señal en la historia, es
información valiosísima.

- **Universo:** EURUSD, GBPUSD, USDJPY, USDCHF, AUDUSD, USDCAD, NZDUSD, XAUUSD —
  timeframe D1.
- **Long:** `regime_trend == up` ∧ `close(N) > max(high de los 55 bars previos)` ⇒
  señal al close, entrada al open de N+1.
- **Short:** espejo (`regime_trend == down` ∧ `close(N) < min(low de los 55 bars
  previos)`).
- **SL inicial:** 2.0 × ATR14 desde la entrada.
- **Sin TP fijo** (dejar correr al ganador — es la esencia del trend following).
- **Salida trailing Donchian:** long sale cuando `close(N) < min(low de los 20 bars
  previos)`; short espejo. Señal al close, ejecución al open siguiente. El SL duro
  sigue activo intrabar todo el tiempo.
- **Time exit:** 120 bars.
- **Confianza emitida:** constante 70 cuando hay señal (paridad con
  `STRATEGY_MIN_CONFIDENCE`).
- **Params Modo A (congelados):** SMA=200, entry=55, exit=20, ATRmult=2.0, ATRper=14.
- **Grid Modo B permitido (máx 9 configs):** entry {40, 55, 70} × ATRmult {1.5, 2.0,
  2.5}. Nada más.

## 10. Protocolo de evaluación — Modo A y Modo B

**Modo A (default, primero SIEMPRE):** parámetros congelados, 1 config por estrategia,
historia completa, CERO optimización. Reporte sliceado por año / sesión / dirección /
régimen. Como la hipótesis se fijó antes de mirar la data, la historia completa
funciona como evaluación honesta.

**Modo B (solo si Modo A es prometedor):** walk-forward con grid acotado:

- Train 24 meses → Test 6 meses, rolling de a 6. Los params se eligen SOLO en train;
  se mide SOLO en test; la concatenación de ventanas test es la curva OOS.
- Tope duro: `BACKTEST_MAX_CONFIGS_PER_RUN=9`.

**Contabilidad de honestidad:** el reporte muestra SIEMPRE `n_configs_tested` junto al
mejor resultado. 9 configs probadas con 1 ganadora NO es lo mismo que 1 hipótesis
confirmada.

Prohibido re-correr Modo B con grids nuevos sin documentar el porqué en
`backtest_runs.notes` — el historial de intentos es parte de la evidencia.

## 11. Criterios de aceptación para ganarse PAPER (defaults; ajustables solo POR ESCRITO antes de correr)

Una estrategia/config gana el derecho a encenderse en paper vivo si, en evaluación OOS:

| Criterio | Umbral |
|---|---|
| Muestra | n ≥ 150 trades |
| Expectancy | avg R neto ≥ +0.10 con costos ×1.25 |
| Stress de costos | avg R neto ≥ 0 con costos ×1.5 |
| Consistencia temporal | ≥ 60% de los años positivos Y positiva en ambas mitades del período |
| Drawdown | max DD ≤ 25R |
| Profit factor | ≥ 1.15 |
| Robustez de vecindad | con ±1 paso en cada knob del grid, el avg R neto NO cambia de signo |

Si pasa todo ⇒ decisión humana de encender su flag de paper (OFF→ON). Después siguen
los gates vivos normales — **el backtest abre la puerta de paper, nunca la de MT5.** Si
NO pasa ⇒ se documenta el veredicto y listo. **Prohibido "ajustar hasta que pase".**

## 12. Reporte de salida

Por run, en `exports/backtest_<run_id>/` (carpeta ya gitignored):

- **`report.md`**: resumen del run (rango REAL de data por símbolo, configs, costos),
  tabla global por estrategia, slices por símbolo / sesión / dirección / año /
  regime_trend / regime_vol (marca `[OK]` solo slices con n ≥ 30), context
  completeness, y bloque VEREDICTO por estrategia contra los criterios del §11
  (PASA / NO PASA, criterio por criterio).
- **`trades.csv`**: todos los trades simulados (mismas columnas que `backtest_trades`).
- **`equity_r.csv`**: curva de R acumulado por estrategia/config.

## 13. Settings nuevos (defaults conservadores)

```
# Backtest Replay Harness — v3.6.0 (todo opt-in / soft-fail)
ENABLE_BACKTEST_HARNESS=false
BACKTEST_TIMEFRAME=D1
BACKTEST_SYMBOLS=EURUSD,GBPUSD,USDJPY,USDCHF,AUDUSD,USDCAD,NZDUSD,XAUUSD
BACKTEST_COST_MULTIPLIER=1.25
BACKTEST_STRESS_COST_MULTIPLIER=1.5
BACKTEST_SL_SLIPPAGE_ATR=0.05
BACKTEST_INTRABAR_RULE=pessimistic
BACKTEST_MAX_CONFIGS_PER_RUN=9
BACKTEST_WF_TRAIN_MONTHS=24
BACKTEST_WF_TEST_MONTHS=6
```

Los parámetros de estrategia NO van a Settings: viven en el `config_json` del run.
Cada corrida queda autodescrita y Settings no se infla.

Regla de la casa: al tocar Settings, sincronizar `_settings()` de `tests/test_score.py`
Y `tests/test_alert_rules.py` EN EL MISMO COMMIT.

## 14. Tests requeridos (~40 nuevos; objetivo ≥ 610 verdes por CONTEO)

| Archivo | Casos clave |
|---|---|
| `test_backtest_loader.py` | Cache round-trip; reporte de profundidad real por símbolo; símbolo sin data ⇒ soft-fail con aviso claro. |
| `test_backtest_context_builder.py` | Canario anti-look-ahead: inyectar un spike artificial en N+5 y verificar que la señal en N es IDÉNTICA con y sin ese futuro. Ventanas terminan en N. Campos sin historia ⇒ `None`. Paridad de claves del contexto vs el contexto vivo. |
| `test_backtest_trade_simulator.py` | Long y short POR SEPARADO (referencia: bug de shorts de v2.7.0): geometría SL/TP correcta por dirección; B3 (barra toca ambos ⇒ SL); B4 (gap_sl al open; TP con gap ⇒ fill en TP exacto); B5 (trailing solo al close, tighten-only); B6 (time exit); B9 (slippage). Números dorados calculados a mano sobre fixtures sintéticas. |
| `test_backtest_harness.py` | Determinismo (doble corrida ⇒ output idéntico); B12 (1 posición por símbolo); escribe SOLO en tablas `backtest_*`; respeta `STRATEGY_MIN_CONFIDENCE`. |
| `test_regime_filter.py` | SMA200/slope/terciles de ATR sobre fixtures sintéticas con resultado conocido; función pura; solo datos ≤ N. |
| `test_trend_following_d1.py` | Fixture con tendencia fabricada ⇒ entra en el breakout 55 esperado, sale por Donchian 20 donde corresponde (calculado a mano); short espejo; respeta el regime gate. |
| `test_backtest_repository.py` | CRUD de las 3 tablas; índices; cero FKs a tablas vivas. |
| `test_backtest_report.py` | Slices con n<30 sin `[OK]`; veredicto criterio por criterio; stress ×1.5 presente en el reporte. |
| (sync) | `_settings()` actualizado en `test_score.py` y `test_alert_rules.py`. |

Principio de la casa: cada módulo nuevo trae su test file; no hay merge sin todo verde.

## 15. Plan de sesiones (Claude Code) — con gate de verificación

| Sesión | Entrega | Gate para cerrar la sesión |
|---|---|---|
| S1 | Tablas `backtest_*` + repository + `historical_loader` + sus tests | pytest verde por conteo; el loader imprime la profundidad REAL por símbolo. Si parece truncada: avisar al user que en MT5 → Herramientas → Opciones → Gráficos suba "Max bars" a Unlimited y re-descargar. |
| S2 | `context_builder` + `regime_filter` + canarios anti-look-ahead | pytest verde; el canario pasa; el completeness report funciona. |
| S3 | `trade_simulator` completo (long/short/gaps/costos/slippage) | pytest verde; los números dorados a mano coinciden exacto. |
| S4 | `replay_harness` + `report` + primer run Modo A real con las 4 estrategias existentes | pytest verde; `exports/backtest_<id>/report.md` generado; revisión humana del reporte antes de seguir. |
| S5 | `trend_following_d1` + run Modo A + veredicto contra §11; decidir si amerita Modo B | pytest verde; veredicto documentado; bump app_version a v3.6.0 + CHANGELOG + README + .env.example; merge final. |

Flujo git de la casa: branch `claude/<x>` → el user mergea con `git merge
claude/<branch>` + `git push origin main` (sin PRs web). Archivos de mensaje de commit
SIEMPRE fuera del repo (`$TEMP`).

## 16. Prohibiciones explícitas

- NO tocar `mt5_demo_trader.py` ni `mt5_reconciler.py` — el harness ni siquiera los
  importa.
- NO escribir en tablas vivas (`paper_trades`, `strategy_performance*`,
  `trade_lessons`, `demo_*`, `bot_state`).
- NO contar trades de backtest para `/readiness`, `/expectancy`, `/edge` ni los 400 de
  la Fase D.
- NO cambiar flags vivos desde el harness — la promoción a paper es SIEMPRE decisión
  humana.
- Sin LLM, sin red y sin aleatoriedad dentro del loop de replay (R4; el LLM local tarda
  ~50s/gen en esta máquina y rompería el determinismo).
- NO reimplementar estrategias: importar las reales (R1).
- Jamás leer/mostrar el `.env` real.
- `ENABLE_REAL_TRADING=false` sigue HARDCODED. Nada de este documento lo toca ni lo
  tocará.

## 17. Fuera de alcance v1 (diferido y documentado para v3.7+)

1. Backfill macro (VIX/DXY diario con regla estricta "solo close del día previo") para
   poblar el contexto macro histórico.
2. Collector de COT (CFTC, semanal, gratis) como primer input informacional que el
   precio no contiene.
3. Granularidad H1 para salidas de trades D1 (reduce la ambigüedad intrabar de B3/B4).
4. Fallback de data vía Yahoo (mezclar fuentes cambia precios; v1 = solo MT5).
5. Comando Telegram `/backtest_status` (v1 es CLI-only para mantener el ciclo vivo
   intacto).
6. Scalping M1 y memecoins: siguen fuera por las razones del §3 — y no es "todavía",
   es "probablemente nunca con honestidad".

## 18. Recordatorios de proceso (lecciones ya pagadas — no repetir)

- `pytest | tail` enmascara el exit code ⇒ verificar el CONTEO de tests, no el exit.
- Archivos de mensaje de commit FUERA del repo (`$TEMP`); `git add -A` ya los coló dos
  veces.
- Cualquier `.ps1` nuevo: ASCII puro, sin ñ ni rayas largas (PowerShell 5.1 sin BOM lee
  ANSI). Esta serie no debería necesitar ninguno.
- Los techos optimistas (mfe/mae intrabar) mienten ⇒ por eso B5 evalúa el trailing solo
  en closes.
- Una sola máquina a la vez contra la demo; el harness no abre posiciones, pero la
  regla sigue.

## 19. Prompt de arranque para Claude Code (copiá/pegá)

```
Retomamos Trading Alert AI (bot de trading algorítmico LOCAL, Python 3.12, Windows).
Estado: v3.5.0, main, 572 tests verdes. NO toques el bot vivo.

Objetivo de esta serie: implementar el Backtest Replay Harness v1 según
ESPEC_BACKTEST_REPLAY_v1.md — leelo COMPLETO antes de tocar nada; es la fuente
de verdad de la serie. Leé también RESUMEN_COMPLETO.md (en especial §9, reglas)
y PROXIMOS_PASOS.md.

Reglas inamovibles de la serie: real-money BLOQUEADO (ENABLE_REAL_TRADING=false
HARDCODED); order_send solo en mt5_demo_trader.py (el harness NI LO IMPORTA);
tablas backtest_* separadas de las vivas; el backtest NO cuenta para /readiness
ni para los 400 de Fase D; reuso del código REAL de estrategias (nada de
copias); cero look-ahead (convenciones B1-B13 de la espec, cada una con test);
pesimismo por diseño; determinista y offline (sin LLM ni red en el replay);
todo opt-in OFF + soft-fail; pytest verde por CONTEO (572 + nuevos, objetivo
>= 610); sincronizar _settings() de test_score y test_alert_rules al tocar
Settings; versionado: toda la serie entra como v3.6.0 en el merge final.

Empezá por la SESIÓN 1 del plan (§15 de la espec): tablas backtest_* +
repository + historical_loader + sus tests. Al terminar: mostrame el conteo de
pytest, la profundidad histórica REAL por símbolo que reportó el loader, y
esperá mi merge antes de seguir con la Sesión 2.
```

---

*Preparado el 2026-06-12 entre el user y Claude, bajo la regla que está por encima de
todas en este proyecto: el backtest existe para NO autoengañarse. Si una estrategia no
pasa los criterios, la respuesta correcta es documentarlo — nunca ajustar hasta que
pase.*
