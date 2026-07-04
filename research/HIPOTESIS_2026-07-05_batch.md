# Pre-registro — tanda 2026-07-05: equities (Stooq) + COT smart-money

> Anti-data-dredging: commiteado ANTES de correr. **k=3 hipótesis** (denominador
> propio). Lo que no pase, MUERE (sin re-cortes ni ajustes post-hoc). Un pase solo
> habilita una regla congelada para el harness §11 → paper → gates; NADA prende
> flags vivos ni toca real-money. Umbral t con Bonferroni k=3: **t ≥ 2.40**.

## Familia E — anomalías de índices de acciones (data nueva: Stooq D1)

Data: SPY/QQQ/IWM D1 de Stooq (gratis, sin throttle), en research_rates.db. Estas
son las anomalías con MÁS soporte académico que un retail puede expresar, y no las
pudimos testear antes (SPY nunca entró al cache por el 429 de Yahoo).

**E1 — Turn-of-month (McConnell & Xu 2008):** el retorno diario en la ventana
[último día hábil del mes, +3 primeros del siguiente] > el resto de los días.
- Regla: long índice esos días. Test por índice + pool.
- Umbral: media(ToM) − media(resto) > 0, positiva en AMBAS mitades, ≥60% de años,
  t-Welch ≥ 2.40.

**E2 — Overnight vs intraday (Cooper et al; Lachance):** casi todo el retorno de
los índices ocurre OVERNIGHT (close→open), no intraday (open→close). Es de las
anomalías más robustas que existen.
- Medición: retorno overnight = ln(open[t]/close[t−1]); intraday = ln(close[t]/open[t]).
- Umbral (para "pasa"): media overnight > 0 con t ≥ 2.40 **Y** overnight > intraday.
  Tradeabilidad: comprar al close, vender al open (hold nocturno). Caveat declarado:
  2× spread/comisión diario se come mucho — el pase es de EXISTENCIA; la
  tradeabilidad neta va a §11 aparte si pasa.

## Familia F — COT lado "smart money" (data existente: cot_snapshots 40yr + precio)

Testeamos el lado ESPECULADOR (non-commercial, momentum) → murió (H-A1). Los
**commercials** (hedgers) son el otro lado, la "smart money" del folklore COT: la
hipótesis económica es que cuando los commercials están extremadamente LONG,
el precio tiende a SUBIR (ellos toman la otra punta de los specs que se equivocan).

**F1 — Índice COT de commercials → retorno forward:** índice Williams sobre
`net_comm` (ventana 156 sem, mín 52), as-of con lag de 7 días (igual que H-A1).
Bucket ALTO (idx≥0.8) − bucket BAJO (idx≤0.2) del retorno forward del par
(orientado al par: XXXUSD +1, USDXXX −1, GOLD +1), a 5/10/20 días.
- Umbral: spread > 0 en los 3 horizontes, ambas mitades, ≥60% años, t ≥ 2.40.
- Prior HONESTO: bajo (el COT ya falló una vez por el lado specs; los commercials
  son el espejo, así que si specs es ruido, commercials probablemente también).

## Predicción declarada (antes de correr)

- **E1 (ToM):** el ToM en índices es de lo más sólido de la familia estacional →
  ~50/50 que pase el t≥2.40 (Bonferroni es duro); probablemente positivo pero al
  borde. Tradeabilidad neta de costos: fina (efecto ~10-20 bps en ~4 días).
- **E2 (overnight):** probable que overnight >> intraday (es robustísimo), PERO
  neto del doble spread diario probablemente no sea tradeable retail. "Real, no
  tradeable" otra vez es el resultado más probable.
- **F1 (commercials):** probable NO PASA (mismo destino que specs).

## RESULTADOS (corrida 2026-07-05)

Nota de data: Stooq quedó detrás de un challenge JS → SPY/QQQ/IWM se bajaron con
el loader Yahoo del proyecto (`scripts/equity_backfill.py`, backoff anti-429):
SPY 1993→2026 (8413), QQQ 1999→, IWM 2000→.

**E1 — Turn-of-month: NO PASA.** ToM positivo pero débil: SPY +7.4 vs +3.1 bps/día
(t=1.30), QQQ +9.2 vs +2.5 (t=1.20), IWM t=0.08 (2ª mitad negativa). Pool t=1.48.
El efecto existe pero no cruza Bonferroni t≥2.40. Muere.

**F1 — COT commercials: NO PASA.** Spread ALTO−BAJO NEGATIVO (−5.8/−9.7/−21.5 bps,
o sea commercials-long → precio baja) pero no significativo (t=−1.14/−0.15/−0.75).
Ruido, espejo de los specs (H-A1). La familia COT queda definitivamente cerrada
por ambos lados. Muere.

**E2 — Overnight vs intraday: PASA EXISTENCIA, fuerte y limpio.** Casi todo el
retorno de los índices es overnight (close→open); el intraday es ~0/negativo:
- SPY: overnight +3.78 bps/día (~+9.5%/año, **t=5.17**), intraday +0.30 bps.
- QQQ: overnight +5.16 bps/día (~+13%/año, t=4.75), intraday −1.08 bps.
- IWM: overnight +4.98 bps/día (~+12.5%/año, t=4.82), intraday −1.61 bps.
Los 3 índices, t muy por encima de 2.40. **Es la 1ª hipótesis del proyecto que
cruza claramente la barra de existencia.**

### E2 — test de tradeabilidad (`overnight_tradeability.py`, el gate pre-registrado)

A diferencia de TODO lo anterior, **sobrevive costos realistas** (sensibilidad,
sin elegir el costo): SPY neto ~+7%/año @1bp, ~+4.5% @2bp; QQQ +10.5%/+8%; IWM
+10%/+7.5%. 79-85% de años positivos. **PERO caveats duros (declarados):**
1. **El bot NO puede tradearlo** — US equities + órdenes MOC/MOO, fuera del
   universo MT5-forex demo. No accionable acá sin infra nueva.
2. **Sharpe ~0.7, maxDD ~35-45%** — real pero modesto; parecido a buy-and-hold del
   índice con caídas brutales.
3. **Crítica Lachance 2021**: el precio de apertura puede NO ser ejecutable (el
   auction limpia el desbalance nocturno; un comprador sistemático lo mueve). El
   efecto puede encogerse mucho con ejecución real.
4. Es archi-conocido → probablemente **compensación por riesgo overnight**, no
   plata gratis; por eso persiste.

**Veredicto E2:** REAL, robusto, sobrevive costos idealizados — el mejor resultado
del proyecto — PERO no accionable para este bot y con ejecución real contestada.
NO es luz verde a tradear; es "genuino, entenderlo, ojos abiertos". Cualquier
intento serio = proyecto aparte (broker de acciones + MOC/MOO), con los caveats
1-4 sobre la mesa. NO se prende nada vivo.

**Score tanda 2026-07-05 (k=3): E1 muere, F1 muere, E2 real+no-accionable.**

## Reglas

1. Scripts read-only sobre snapshot de la DB viva + research_rates.db.
2. Resultado documentado gane o pierda. Holdout: últimos 2 años excluidos de E1/F1.
3. k=3, Bonferroni t≥2.40. Todo positivo se reporta con el denominador.
4. Un pase → regla congelada §11, NUNCA directo a vivo.
