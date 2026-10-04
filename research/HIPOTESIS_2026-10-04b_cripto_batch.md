# Pre-registro — tanda cripto 2026-10-04b: H-FC2 (carry en altcoins), H-XS1 (momentum cruzado), H-POS1 (posicionamiento)

> **VEREDICTO (corrido 2026-10-04, ventana 2024-10 → 2026-09): las TRES NO PASAN — familias cerradas.**
> - **H-FC2 (carry en altcoins): NO PASA.** CAGR −12.0 % (total −22.6 %) vs tasa libre 4.04 % →
>   exceso −16.3 %, t −2.69, maxDD −22.6 %; ambas mitades negativas. Pocas altcoins líquidas
>   superan 10 % de funding (mediana 2.5 posiciones, no 5) y apenas lo superan (funding
>   mediano al entrar 10.95 %, mientras se tienen 10.1 %); 210 entradas en 104 semanas: la
>   rotación cuesta más que el funding. 1 liquidación por mecha (2025-07-11: −11.3 % del
>   equity en una barra) y 3 deslistados. Post-hoc: aun sin la liquidación pierde ~11 %.
> - **H-XS1 (momentum cruzado): NO PASA.** CAGR −11.3 %, exceso −12.9 %, t −0.74, maxDD −46 %.
>   Primera mitad +19.1 % de exceso, segunda −44 %: crash de momentum. Rotación ~100 % semanal.
> - **H-POS1 (posicionamiento contrario): NO PASA.** 148 trades (57 long / 91 short), exceso
>   +0.32 % por trade con t 0.69 (ruido), 49 % ganadores; mitades −0.07 % / +0.76 %.
> Data: 41.532 archivos, 41.532/41.532 checksums oficiales OK (manifest en
> `trading_data/binance_batch/`, sha256 8de17c8deb925729e45946a26d98246c4c0860efc89afc7b5fe39b37ff59551d). 15 familias probadas con pre-registro, 0 operables.

> **Commiteado ANTES de bajar los datos de esta tanda** (protocolo del proyecto). Tres
> familias del mapa del user (B3-altcoins, B13, B11), **k = 3**, un tiro cada una.
> Umbral uniforme y conservador: **t ≥ 2.50** (más estricto que Bonferroni k=3, 2.40,
> porque la familia carry ya gastó 4 tests en H-FC1). Research-only: no toca el bot,
> ni flags, ni MT5; real-money HARDCODED bloqueado. Un PASA habilita solo un diseño de
> paper-trading con su propio pre-registro.

## Común a las tres

- Fuente: data.binance.vision (verificado 2026-10-04): 901 perpetuos USDⓈ-M con funding
  (incluye deslistados → sin sesgo de supervivencia); 471 con par spot de mismo nombre.
  Se excluyen contratos con prefijo multiplicador ("1000…", sin par spot equivalente),
  símbolos no-ASCII y bases estables (USDC, FDUSD, TUSD, BUSD, USDP, DAI, EUR, AEUR, USDE).
- Ventana DECISORIA única: **2024-10-01 → 2026-09-30** (misma que H-FC1). Data desde
  2024-07 solo como historia previa para filtros y señales.
- Tasa libre: EFFR del NY Fed (= DFF de FRED), como en H-FC1.
- Manifest con checksums oficiales. Comisiones de nivel base UNVERIFIED (tabla oficial
  requiere sesión): spot 0.10 %, perpetuo 0.05 % por lado.
- Liquidez (point-in-time, solo pasado): mediana de los 30 días previos del volumen
  diario en USDT del perpetuo ≥ **US$20 M** (y del spot ≥ **US$2 M** donde se usa spot).
- Si un símbolo deja de tener datos estando en cartera (deslistado): sale al último
  cierre con **2 %** extra de pérdida sobre su nocional (conservador).

## H-FC2 — Carry delta-neutral en altcoins (B3-altcoins)

- Cada lunes 00:00 UTC: universo = perp ∩ spot, sin BTC/ETH, ≥ 30 días de datos de ambos,
  filtros de liquidez. Ranking por funding medio de los 7 días previos, anualizado
  (suma de liquidaciones × 365/7, sirve para intervalos de 8 h o 4 h).
- Selecciona las **5** con mayor funding si superan **10 %** anual; peso igual (1/5 del
  equity cada una); menos de 5 elegibles → el resto queda en efectivo.
- Cada posición: long spot + short perp, **margen 1.0** (short 1x: las altcoins se mueven
  más que BTC). Funding en cada liquidación. Chequeo de liquidación con máximo intra-vela
  (mantenimiento 1 % del nocional). Rebalanceo de la posición si el precio se mueve
  ±30 % desde su último ajuste.
- Las que siguen seleccionadas no se tocan; las que salen se cierran y las nuevas se
  abren. Slippage **0.10 %** por pata por operación (altcoins).
- **PASA** si: exceso anual sobre la tasa libre > 0; t semanal ≥ 2.50; drawdown máx
  ≤ **15 %**; exceso > 0 en ambas mitades; exceso > 0 con costos × 2. Liquidaciones:
  se cuentan y su pérdida entra al PnL.
- Predicción: funding bruto de las seleccionadas alto (15-40 % anual al momento de
  elegirlas), pero se revierte después de seleccionarlas y las salidas pagan base y
  costos. **Incierto; probable NO PASA** neto.

## H-XS1 — Momentum cruzado dollar-neutral con perpetuos (B13)

- Cada lunes 00:00 UTC: universo = perpetuos de la lista (incluye BTC/ETH) con filtro de
  liquidez del perp. Ranking por retorno de los **21 días** previos.
- Long el quintil superior, short el quintil inferior, peso igual, exposición bruta 1.0
  (0.5 long / 0.5 short). Se mantiene una semana.
- Costos: perp 0.05 % + slippage 0.05 % por lado por operación sobre lo que cambia.
  Funding pagado/cobrado en ambas patas.
- **PASA** si: exceso anual sobre la tasa libre > 0 (capital = 1.0 de margen); t semanal
  ≥ 2.50; drawdown máx ≤ **30 %**; ambas mitades > 0; costos × 2 > 0.
- Predicción: hay literatura de momentum semanal en cripto, pero los longs pagan funding
  alto y hay crashes de momentum. **Probable NO PASA.**

## H-POS1 — Posicionamiento minorista contrario en BTC y ETH (B11)

- Data: `metrics` diario de data.binance.vision (registros cada 5 min), BTCUSDT y
  ETHUSDT. Señal única elegida a priori: **ratio long/short de cuentas global**
  (`count_long_short_ratio`), valor al cierre de cada día UTC; z-score contra los 90
  días previos. Las demás columnas (OI, top traders, taker) NO se prueban acá.
- Regla contraria: z > **+1.5** → short del perpetuo por 3 días; z < **−1.5** → long por
  3 días; si no, nada. Trades sin solapamiento; entra al cierre del día de la señal.
- Costos: perp 0.05 % + slippage 0.02 % por lado; funding pagado/cobrado.
- **PASA** si (BTC y ETH juntos, capital = nocional 1x): exceso sobre la tasa libre > 0;
  t de los retornos por trade ≥ 2.50; n ≥ 30 trades; ambas mitades > 0; costos × 2 > 0.
- Predicción: el sentimiento minorista es contrario en extremos según los propios
  exchanges, sin literatura independiente sólida. **Probable NO PASA.**

## Limitaciones declaradas antes de correr

- Un solo exchange; riesgo de contraparte no modelado; velas de 8 h (rebalanceos y
  señales solo a los cierres).
- Excluir contratos "1000…" deja afuera algunas memecoins líquidas.
- Las comisiones de nivel base no se verificaron en la tabla oficial.

Firmado (protocolo): k = 3, un tiro por hipótesis, ventana decisoria fija. Si no pasa,
la familia queda cerrada sin re-cortes; variantes = pre-registro nuevo.
