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

## Reglas de la tanda

1. Los scripts (`scripts/cot_price_study.py`, `scripts/seasonality_study.py`) corren
   sobre un SNAPSHOT read-only de la DB viva. No tocan el bot.
2. El resultado se documenta gane o pierda (CHANGELOG research + memoria).
3. **Holdout:** los últimos 2 años de data NO entran en la exploración de la familia
   A (se cortan del sample). Si H-A1 pasa en exploración, tiene UN único tiro sobre
   el holdout antes de considerarse candidata.
4. Contador de la tanda: k=6. Un "pase" aislado con k=6 al 5% tiene ~26% de
   probabilidad por puro azar — por eso el umbral es Bonferroni, no p<0.05 suelto.
