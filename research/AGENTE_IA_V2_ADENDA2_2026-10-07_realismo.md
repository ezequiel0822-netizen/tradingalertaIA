# Adenda 2 al pre-registro del agente IA v2 — ajuste de realismo solo con fuente única (2026-10-07)

> **Commiteada ANTES del cambio de código** y antes de que exista una decisión del tag
> evaluado `...|px1`. La motiva un dato verificado (la orden real de MT5), no un
> resultado: la t de v2 no se calculó. Va con la adenda 1
> (`AGENTE_IA_V2_ADENDA_2026-10-07_oro.md`) y con el pre-registro
> `AGENTE_IA_V2_PREREGISTRO_2026-10-06.md` (§1.2, ajuste de realismo ĝ).

## 1. Qué pasó (verificado en `demo_trade_requests` / `ai_agent_decisions`, solo lectura)

- **NZDUSD, decisión #26** (exploración long del 2026-10-07 06:19 UTC):
  - Paper (precio de Yahoo): entrada 0.5605, SL 0.56024778 (**2.5 pips**), TP1 0.56075222.
  - La orden de MT5 (request 493, 0.1 lot) entró a **0.56029**, 2.1 pips por debajo de
    Yahoo, con el SL y el TP del paper. Stop real de **0.4 pips** y TP de 4.6 pips: un
    trade 11:1 en vez de 1:1.
  - Llegó al TP: +4.60 USD = **R_mt5 +10.95** contra **R_paper +1.69**.
- **Las otras dos ejecuciones v2** también tenían la entrada de MT5 corrida respecto de
  Yahoo:
  - EURUSD #20: 2.4 pips; stop real 7.7 pips contra 10.1 del paper; R_mt5 +1.05 contra
    +0.57.
  - USDCAD #23: 0.5 pips; R_mt5 −0.99 contra −1.01.
- **Efecto en ĝ:** ĝ = Σ(R_mt5 − R_paper)/(n + 5) = (0.48 + 0.01 + 9.26)/8 = 1.22,
  recortado a **+0.25**. Desde #26 el agente suma +0.25R a cada puntaje: ejecuta si el
  muestreo supera −0.20R en vez de +0.05R. Eso no es realismo: es la misma mezcla de
  fuentes de la adenda 1, ahora en forex y en la orden real. Con stops de 2-3 pips, un
  desfase de 1-2 pips entre Yahoo y MT5 cambia el trade entero.

## 2. Cambio (solo con `PAPER_PRICE_FROM_MT5=true`, la configuración `px1`)

- ĝ usa **solo** ejecuciones v2 cuyo paper trade tiene fuente única de precio
  (`price_source` no NULL), forex u oro.
- Las ejecuciones previas al fix (las tres de arriba) quedan fuera, así que ĝ vuelve a 0
  hasta que haya ejecuciones con fuente única.
- Con fuente única, la orden de MT5 y el paper comparten entrada y distancias (v3.14.1).
  R_mt5 − R_paper vuelve a medir lo que debía: slippage, spread, swap y comisión.
- **Sin cambios:** la fórmula (n + 5), el recorte [−1, +0.25], los parámetros, el tag
  evaluado (`px1`), las fechas, los criterios y la predicción (NO PASA).
- **Con el flag apagado:** todo como antes, incluido el ĝ inflado. Esa configuración no se
  evalúa (adenda 1 §3).

## 3. Reporte y `/agente`

- "Real − paper" se muestra solo con las ejecuciones de fuente única; las previas al fix
  se cuentan aparte.
- El P&L en USD de MT5 se sigue mostrando completo: es dinero de la demo, no una
  medición.

## 4. Por qué esto no es un re-corte

- El motivo es un mecanismo verificado en la orden real (entrada de MT5 ≠ entrada del
  paper, con el SL/TP del paper), no el desempeño.
- No toca la medición del agente, que sigue siendo R_paper sobre `px1`: solo saca de una
  entrada de la DECISIÓN un dato roto.
- Se fija antes de la primera decisión `px1`.

Firmado (protocolo): fija desde este commit; el código va en el commit siguiente.
