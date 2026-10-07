# Adenda 1 al pre-registro del agente IA v2 — precio mezclado del oro (2026-10-07)

> **Commiteada ANTES del código del fix (v3.14.1) y antes de encenderlo.** La motiva un
> error de DATOS con mecanismo verificado, no un resultado: la t de v2 no se calculó
> (no se calcula antes del 2027-01-11). Pre-registro original:
> `AGENTE_IA_V2_PREREGISTRO_2026-10-06.md`.

## 1. El bug (medido el 2026-10-07, todo en solo lectura)

- **Mecanismo.** Los paper trades de oro se ABREN con `signal.entry`, calculado con
  velas de Yahoo `GC=F` (futuro COMEX), en `jobs._try_open_paper_trades`. Se MARCAN y
  CIERRAN con el tick de MT5 `XAUUSD` (spot) en `lifecycle_manager._fresh_price` cuando
  MT5 está conectado. El otro updater (`training_engine._update_paper_trades`) los marca
  con Yahoo, así que las dos fuentes se alternan. Para el oro difieren en la prima del
  futuro.
- **Evidencia puntual.** El 2026-10-06 a las 13:39 UTC, GC=F daba 4190.0 y el M1 de
  XAUUSD ~4160; a las 23:11 UTC, 4190.7 contra 4165.3. Los paper trades 2085 (long
  breakout) y 2097 (long mean_reversion) se marcaron "stopped" en 1-2 min con R −3.52 y
  −5.10. La exploración #22 del agente fue rechazada por MT5 ("long order requires SL
  below entry/current price"): el SL de la señal quedaba por encima del precio real.
- **Dataset completo.** 305 de los 311 paper trades de oro (2026-05-22 → 2026-10-06)
  tienen precio spot de MT5 en el minuto de apertura (velas M1/M5, hora del servidor →
  UTC).
  - Entrada − spot: mediana **+$21.2** (p10 −2.7, p90 +36.5).
  - En el **53 %** de los trades el desfase es mayor o igual a una distancia de stop
    entera.
  - Longs no-artifact (n = 56): R medio **−1.68**, del que −1.75R es el efecto
    instantáneo de la fuente.
  - Shorts (n = 40): R medio **+0.64**, del que +1.55R es la fuente.
  - Control con forex (822 trades): desfase medio +0.03R, sin problema comparable.
- **Consecuencias para v2:**
  - (a) ~100 de las 593 muestras del warm start son oro mezclado;
  - (b) el modelo aprendió "long de oro ≈ −1R": las decisiones #19 y #22 tenían media
    −0.97 y −1.12;
  - (c) la feature `strat_recent_r` promedia esos R;
  - (d) en las 10 primeras decisiones v2, −8.6R de los −12.9R de "ejecutar todo" son
    esos dos trades.

## 2. El fix (v3.14.1, opt-in `PAPER_PRICE_FROM_MT5=true`; con el flag apagado, todo igual que antes)

- **Paper trades forex/oro:**
  - Al abrir, los niveles de la señal (entrada, SL, TP1, TP2) se trasladan al precio de
    MT5 de ese momento (ask para long, bid para short), conservando las distancias.
  - El trade guarda `price_source = 'mt5'` y, en `source_entry_price`, la entrada
    original de Yahoo.
  - Solo lo marca el lifecycle con MT5, sin caer a Yahoo; el updater de Yahoo lo saltea.
  - Si MT5 no responde al abrir, o el desfase supera el 3 % (feed equivocado), se
    queda con los niveles de Yahoo, `price_source = 'yahoo'`, y se marca SOLO con Yahoo.
  - Cada paper trade queda con una sola fuente de punta a punta.
- **Forex:** el fix también aplica. La entrada pasa a ser el ask o bid de MT5, así que
  el paper paga el spread completo (más realista; ≈ −0.01 a −0.05R por trade).
- **"Oro mezclado"** = paper trade de oro con `price_source` NULL: todos los anteriores
  al fix, y los abiertos con el flag apagado.
- **Agente, con el flag ON:**
  - no aprende de oro mezclado;
  - lo excluye del ajuste de realismo ĝ y de `strat_recent_r`.
- **Stats por estrategia** (`strategy_performance`, slices y lecciones de features):
  también lo excluyen con el flag ON.
- **Modelo v2:** se RECONSTRUYE sin oro mezclado con
  `scripts/ai_agent_warmstart.py --version 2 --mt5-d1 --exclude-mixed-gold --apply --force`
  (bot apagado). Queda marcado con `excludes_mixed_gold` en su estado.

## 3. Qué cambia en la evaluación (§1.5, §2 y §3 del pre-registro v2)

- **Tag evaluado:** `v2|eps0.20|xr0.10|r0.50|thr0.05|pv0.25|nv1.00|xmax3|xstop2.0|px1`.
  Son los mismos parámetros + `PAPER_PRICE_FROM_MT5=true` + modelo reconstruido sin oro
  mezclado. Si el flag está ON pero el modelo no se reconstruyó, el tag termina en `|px0`
  y NO cuenta.
- **Decisiones con el tag original** (2026-10-06 13:01 UTC → despliegue del fix): se
  reportan aparte y NO deciden; las tomó un modelo contaminado por el bug.
- **Oro mezclado:** en cualquier tag, se excluye de la medición toda decisión de oro
  cuyo paper trade sea oro mezclado (con `px1` no debería haber ninguna). Se reporta
  cuántas se excluyeron.
- **Sin cambios:** fechas (desde el 2027-01-11 con ≥ 200 decisiones con R; tope
  2027-04-12 con baja potencia), criterios 1-5 y predicción (**NO PASA**). Las 200 se
  cuentan solo con el tag `px1`.
- **`/agente` y el reporte:** muestran la medición SIN el oro mezclado, siempre (es
  medición, no comportamiento).

## 4. Qué NO cambia

- Los parámetros (ε, riesgos, umbral, prior, ruido, límites, semilla) y las reglas de
  decisión y exploración.
- Las features, salvo la exclusión del §2 en `strat_recent_r`.
- Real-money sigue bloqueado por código; un PASA no lo cambia.

## 5. Por qué esto no es un re-corte

- El motivo es un error de datos con mecanismo reproducido, no el desempeño. La
  evidencia es el desfase entre fuentes en el minuto de apertura, no el R.
- Se fija antes de mirar cualquier t. Lo que sale de la evaluación es exactamente lo
  contaminado: oro mezclado y decisiones de un modelo que lo aprendió.
- Nada se elige por resultado, y lo excluido se sigue reportando aparte.
- Las decisiones del tag original eran 10 al detectarse el bug. Con ~10 candidatos por
  día, `px1` llega a 200 mucho antes del 2027-01-11.

Firmado (protocolo): esta adenda queda fija desde este commit; el código del fix va en
el commit siguiente.
