# Pre-registro — tanda 2026-07-04: CARRY (diferenciales de tasa vía FRED)

> Protocolo anti-data-dredging: este archivo se commitea ANTES de correr. Tanda
> nueva, denominador propio (**k=3 hipótesis**). Lo que no pase, MUERE (sin
> re-cortes ni ajustes post-hoc). Un pase solo habilita una regla congelada para
> el harness §11 → paper → gates; NADA prende flags vivos ni toca real-money.

## Por qué el carry (y por qué podría ser distinto a lo anterior)

El carry trade (comprar la divisa de tasa alta, vender la de tasa baja) es de las
POCAS anomalías FX con soporte académico multi-década (Fama 1984 "forward premium
puzzle"; Lustig-Verdelhan). A diferencia del COT (posicionamiento, que el precio
digiere) o de patrones técnicos (ya en el precio), el diferencial de tasas es un
flujo ESTRUCTURAL: pagás/cobrás swap cada noche por tenerlo. La pregunta honesta
no es "¿existe el carry?" (existe) sino "¿sobrevive neto del swap del broker retail
y de los drawdowns de reversión, sobre ESTOS 7 pares, en D1?".

## Fuente de data (FRED, gratis, sin key)

Tasas de política / interbancaria 3M por divisa, CSV directo:
`https://fred.stlouisfed.org/graph/fredgraph.csv?id=<SERIE>`
- USD: `DFF` (Fed Funds, diario) — proxy USD
- EUR: `ECBDFR` (ECB Deposit Facility, diario)
- GBP: `IUDSOIA` (SONIA, diario)
- JPY: `IRSTCI01JPM156N` (call rate, mensual)  — OECD, mensual
- AUD: `IR3TIB01AUM156N` (3M interbank, mensual)
- CAD: `IR3TIB01CAM156N` (3M interbank, mensual)
- CHF: `IR3TIB01CHM156N` (3M interbank, mensual)
- NZD: `IR3TIB01NZM156N` (3M interbank, mensual)
Décadas de historia. Diferencial del par = tasa(base) − tasa(quote), orientado al
par (long el par = long base). Se persisten en un **sqlite de research aparte**
(`trading_data/research_rates.db`, tabla `interest_rates`, idempotente) — NO en el
schema vivo: esto es research, no un collector de producción.

## Anti-lookahead (CRÍTICO — es donde muere la mayoría)

- **As-of con lag conservador**: para la barra D1 de fecha T, se usa la tasa
  publicada ESTRICTAMENTE ANTES de T. Series mensuales (JPY/AUD/CAD/CHF/NZD): se
  usa el valor del **mes ANTERIOR completo** (nunca el mes en curso, que se publica
  con lag). Diarias (USD/EUR/GBP): valor de fecha ≤ T−1.
- Los diferenciales cambian lento → el riesgo de lookahead es de días, pero se
  trata igual con paranoia (misma disciplina que el lag CFTC).

## Hipótesis (k=3)

**H-C1 — Sign del carry → retorno forward (event-study, POOL de pares):** ordenar
cada semana los 7 pares por diferencial de tasa; el retorno forward D1 a 5/10/20
días del par, orientado a favor del diferencial (long si base tiene tasa más alta),
debe ser > 0 en promedio del pool.
- Umbral: media forward direction-adjusted > 0 en los 3 horizontes, positiva en
  AMBAS mitades del período, ≥60% de años, t-Welch (sobre muestra decimada
  no-solapada) ≥ 2.39 (Bonferroni k=3).

**H-C2 — Regla congelada `carry_hold` para §11:** long el par si base−quote ≥
+0.5% anual (congelado); short si ≤ −0.5%; sino no opera. Entrada open barra
siguiente, stop 2.0×ATR (default de la casa, congelado), sin TP, time exit 20
barras D1 (~1 mes, horizonte típico del carry). Cost model forex ×1.25 **+ haircut
de swap**: el carry retail se cobra peor que el diferencial teórico → se resta un
swap pesimista adicional (ver script) o el veredicto miente. Corre en el harness
SOLO si H-C1 pasa. Criterio: §11 ESTRICTO.

**H-C3 — Top-minus-bottom (portfolio, referencia académica):** long el par de
mayor diferencial, short el de menor, rebalanceo semanal; medir si el spread neto
sobrevive. Es la forma "de paper" del carry; sirve para saber si el fracaso (si
lo hay) es del carry en sí o de expresarlo en D1 con stop fijo.

## Predicción declarada (honestidad, ANTES de correr)

El carry existe pero se cobra vía swap del broker, que en pares de tasa alta suele
comerse gran parte del diferencial, y sufre "crash risk" (se desarma violento en
risk-off: 2008, 2015 CHF). Predicción: **H-C1 probablemente muestre el signo
correcto (carry real) pero H-C2 probablemente NO PASE §11** por el haircut de swap
+ los drawdowns de reversión contra un stop fijo de 2×ATR. Si es así, el veredicto
es "carry real pero no tradeable retail en D1 standalone" y la familia C se cierra.

## Reglas

1. Scripts read-only sobre snapshot de la DB viva; backfill de tasas idempotente.
2. Resultado documentado gane o pierda (CHANGELOG research + memoria).
3. Holdout: últimos 2 años excluidos de la exploración de H-C1; un tiro si pasa.
4. k=3. Contador reportado con todo resultado positivo.
