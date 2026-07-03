# Pre-registro de hipótesis — tanda 2026-07-02

> Protocolo anti-data-dredging (auditoría 2026-07-02): este archivo se commitea
> ANTES de correr los tests. La tanda tiene **k=6 hipótesis** en 2 familias; todo
> resultado se reporta CON este denominador. Lo que no pase el umbral, MUERE (sin
> re-intentos ni ajustes post-hoc). Nada de esto prende flags vivos: un pase solo
> habilita diseñar una regla congelada para el harness (§11) → paper → gates.

## Familia A — COT × precio (event-study, hasta ~40 años, 8 mercados)

**H-A1 (única de la familia, 3 horizontes = k_A=3):** los extremos del índice COT
(Williams sobre `net_noncomm`, ventana trailing 156 semanas, mínimo 52) predicen el
retorno forward del par EN LA DIRECCIÓN del posicionamiento del especulador.

- **Regla exacta:** índice ≥ 0.8 = bucket ALTO; ≤ 0.2 = bucket BAJO. Retorno forward
  direction-adjusted (× signo del par: XXXUSD=+1, USDXXX=−1, GOLD=+1; USD index se
  excluye) a **5, 10 y 20 días hábiles** desde la primera barra D1 con
  `time ≥ available_from`.
- **Anti-lookahead:** `available_from = report_date + 7 días calendario` (más
  conservador que el lag real martes→viernes; cubre festivos CFTC).
- **Umbral de pase (pre-fijado):** spread (media ALTO − media BAJO) > 0 en los 3
  horizontes en el POOL de mercados, con (a) spread positivo en AMBAS mitades del
  período, (b) ≥60% de los años con spread positivo, (c) t-stat Welch ≥ 2.39
  (≈Bonferroni k=3, p<0.017) calculada sobre muestras DECIMADAS no-solapadas
  (horizonte h → 1 observación cada ceil(h/5) semanas).
- Si pasa: siguiente paso = regla congelada en el harness con costos ×1.25. Si no
  pasa: la familia COT-legacy-extremos muere; NO se re-corta hasta que haya una
  hipótesis nueva pre-registrada (p.ej. TFF).

## Familia B — Estacionalidad sobre el cache propio (k_B=3)

**H-B1 — Turn-of-month en SPY (D1):** el retorno diario medio en la ventana
[último día hábil del mes, +3 primeros del siguiente] > resto de los días.
(McConnell & Xu 2008.) Si no hay data de SPY en el cache → "no testeable hoy",
no se sustituye por otro símbolo post-hoc.

**H-B2 — Viernes del oro (XAUUSD D1):** retorno medio de los viernes ≠ resto
(dirección esperada: positivo, "weekend effect" del oro).

**H-B3 — Estacionalidad mensual del oro (XAUUSD D1):** retorno diario medio en
agosto+septiembre > resto del año.

- **Umbral de pase (cada una):** diferencia de medias en la dirección esperada,
  positiva en AMBAS mitades del período, ≥60% de los años consistentes, t-stat
  Welch ≥ 2.39 (Bonferroni k=3).

## RESULTADOS (corrida 2026-07-02, mismo día del pre-registro)

> Backfill previo: COT extendido a ~40 años (15,633 filas, 1986→2026).

**H-A1 (COT × precio) — NO PASA. La familia COT-legacy-extremos MUERE.**
36 años, 12,689 semanas-evento (8 mercados), holdout 2 años excluido. Spreads
direction-adjusted ALTO−BAJO: +3.8/+8.1/+19.9 bps (5/10/20d) — positivos pero:
**la 2ª mitad del período es NEGATIVA en los 3 horizontes** (+7.3/−1.2,
+15.4/−1.9, +41.6/−5.2), años positivos solo 43-49%, t(decimada) ≤ 1.17. Lo que
había era viejo y se desvaneció. Esto **supersede y explica el 0.607 del
experimento de junio** (COT-sobre-trades-vivos, n=178): era ruido. NO se
re-corta esta familia; una hipótesis TFF/Disaggregated requeriría pre-registro
nuevo.

**H-B1 (ToM SPY) — NO TESTEABLE HOY**: el cache no tiene SPY D1 (el run de
acciones sigue pendiente por el 429). No se sustituyó símbolo (regla).

**H-B2 (viernes del oro) — PASA exploración**: +10.08 bps/día viernes vs resto
(n=1116/4537, XAUUSD D1 2004→2026), mitades +15.65/+4.48, 65% de 23 años,
t=+2.64 ≥ 2.39. **Caveats honestos antes de entusiasmarse:** (a) t=2.64 queda
EXACTAMENTE en el borde del Bonferroni de la tanda completa (k=6 → t≈2.64);
(b) la familia B no tenía holdout pre-registrado — gap del protocolo, se declara;
(c) +10 bps/día contra ~3-5 bps de costo round-trip en oro = margen fino.
**Siguiente gate (pre-registrado): regla congelada en el harness §11 con costos
×1.25 → si pasa, paper. NO prende nada vivo.**

**H-B3 (ago+sep oro) — NO PASA. MUERE.** diff −0.17 bps/día, 50% años, t=−0.04.

**Score de la tanda: 5 corridas de k=6 → 1 pase borderline, 3 muertas, 1 no
testeable.** Con k=6 al 5%, la probabilidad de ≥1 falso positivo por azar es
~26% — por eso H-B2 no es un hallazgo hasta que sobreviva el harness §11.

## Reglas de la tanda

1. Los scripts (`scripts/cot_price_study.py`, `scripts/seasonality_study.py`) corren
   sobre un SNAPSHOT read-only de la DB viva. No tocan el bot.
2. El resultado se documenta gane o pierda (CHANGELOG research + memoria).
3. **Holdout:** los últimos 2 años de data NO entran en la exploración de la familia
   A (se cortan del sample). Si H-A1 pasa en exploración, tiene UN único tiro sobre
   el holdout antes de considerarse candidata.
4. Contador de la tanda: k=6. Un "pase" aislado con k=6 al 5% tiene ~26% de
   probabilidad por puro azar — por eso el umbral es Bonferroni, no p<0.05 suelto.
