# Pre-registro B11 — posicionamiento en perps de Binance: OI, top traders y flujo taker (k = 3)

> **VEREDICTO (corrido 2026-10-05): las TRES NO PASAN — familias 17-19 cerradas.**
> - **H-OI1 (cambio de OI, contraria al día): NO PASA.** Corregida (adenda 1b): exceso
>   −4.1 %/año, t_NW −0.29, n 164 (79 BTC / 85 ETH); mitades −22.4 % / +14.2 %; costos × 2
>   −8.2 %. Original con el bug de OI = 0: −4.6 %, t_NW −0.31, n 166 — misma conclusión.
> - **H-TT1 (top traders, ventana original): INVÁLIDA** — la fuente oficial trae la columna
>   vacía en casi todo 2022 (cobertura 69 %); ninguna estadística calculada.
> - **H-TT1b (top traders por posición, SEGUIR; 2022-12-15 → 2024-10-01): NO PASA.** Exceso
>   −20.3 %/año, t_NW −1.23, n 135; mitades −8.4 % / −32.3 %.
> - **H-TK1 (flujo taker, contraria): NO PASA.** Exceso −25.0 %/año, t_NW −1.29, n 244;
>   ambas mitades negativas.
> Que dos señales pierdan NO convierte a la dirección opuesta en hallazgo: t −1.2/−1.3 es
> ruido en cualquier dirección, y probarla sería un pre-registro nuevo (y dredging).
> Data: 2.700/2.700 checksums oficiales OK; manifest en `trading_data/b11_positioning/`
> (sha256 fc23234e…1c6751); resultados en `research/B11_result.json`,
> `research/B11_tt1b_result.json` y `research/B11_result_ORIGINAL_pre_fix.json`.
> Commits: e80f809 (pre-registro) → dd9e59d (código, 21/21) → 4ff468d (adenda 1, 23/23) → este.

> **Commiteado ANTES de bajar los datos de esta tanda** (protocolo del proyecto).
> Familias 17-19 del ledger. k = 3, un tiro cada una, umbral **t ≥ 2.50**.
> Research-only: no toca el bot, ni flags, ni MT5, ni el .env. Un PASA habilita solo
> un diseño de paper-trading con su propio pre-registro; real-money sigue bloqueado.

## 0. Qué ya se vio (declarado)

- H-POS1 (familia 15) probó el ratio long/short de CUENTAS globales en 2024-10 → 2026-09
  (NO PASA). Para su warm-up se cargó `metrics` 2024-06 → 2024-09, solo la columna
  `count_long_short_ratio`; ninguna estadística de ese tramo se examinó.
- Ventana de esta tanda: **2021-12-01 → 2024-10-01**, NO usada para ninguna señal de
  posicionamiento. Sí se conocen (públicos o vistos en otros tests) los caminos de
  precio de BTC/ETH y el nivel anual del funding de Binance (H-FC1), y en B4b (2026-10-05)
  se usaron velas 1 h y funding de Binance BTC/ETH 2023-05 → 2024-09 para un carry, no
  para señales direccionales.
- Disponibilidad verificada por listado de archivos (2026-10-05, sin abrir ninguno):
  `metrics` diario BTCUSDT desde 2020-09-01 y ETHUSDT desde 2021-12-01, sin días
  faltantes en el listado.

## 1. Datos

- data.binance.vision, todo con checksum oficial y manifest:
  `futures/um/daily/metrics` BTCUSDT 2020-09-01 → 2024-09-30 y ETHUSDT 2021-12-01 →
  2024-09-30 (registros cada 5 min); `futures/um/monthly/klines/{sym}/1d` 2020-06 → 2024-09
  (precio y volumen taker); `futures/um/monthly/fundingRate` 2021-11 → 2024-09.
- Tasa libre: EFFR del NY Fed, as-of, ACT/360.
- Normalización por archivo y por NOMBRE de columna (`metrics` trae encabezado; klines
  por posición). Marcas en µs → ms.

## 2. Valor diario de cada señal (cierre del día UTC d)

- **Variables de stock** (`metrics`): último registro con marca en (d 00:00, d+1 00:00]
  (el de las 00:00 cierra el día anterior, como H-POS1). Día válido si tiene ≥ 144 de los
  288 registros; si no, NaN.
- z-score contra los **90 días calendario previos** (mín. 60 válidos), como H-POS1.

Las tres señales (dirección fijada acá, no se prueba la opuesta):

| Hipótesis | Valor diario v_d | Regla si \|z\| > 1.5 | Tesis |
|---|---|---|---|
| **H-OI1** cambio de open interest | ln(OI_d / OI_{d−1}), OI = `sum_open_interest` (en monedas, no en USD: así el precio no lo mueve mecánicamente) | posición **contraria al retorno del día d** (−signo de ln(C_d/C_{d−1})); si el retorno es 0, nada | Un cambio extremo de apalancamiento (entrada masiva o barrida de posiciones) marca agotamiento del movimiento del día |
| **H-TT1** top traders por POSICIÓN | `sum_toptrader_long_short_ratio` (elegido a priori sobre el de cuentas: mide dinero, no cantidad de cuentas) | z > +1.5 → **long**; z < −1.5 → **short** (SEGUIR) | Los top traders (20 % con más margen) estarían informados: lo opuesto a la tesis minorista de H-POS1 |
| **H-TK1** flujo taker | fracción compradora del volumen del perp en el día d = `taker_buy_volume / volume` de la vela 1d (el `sum_taker_long_short_vol_ratio` de `metrics` es un flujo de 5 min: su último registro solo describe los últimos 5 minutos) | z > +1.5 → **short**; z < −1.5 → **long** (CONTRARIA) | Compra/venta agresiva extrema en el día = agotamiento |

## 3. Trades (mecánica de H-POS1)

- Entrada al cierre del día d (= 00:00 UTC de d+1) al cierre de la vela 1d del perp;
  mantener **3 días**; salida al cierre. Sin solapamiento por símbolo y por señal
  (señales mientras hay un trade abierto se ignoran). Long o short del perpetuo, 1x.
- **Ventana DECISORIA: entradas ≥ 2021-12-01 00:00 UTC y salidas ≤ 2024-10-01 00:00
  UTC.** BTC usa 2020-09 → 2021-11 solo como warm-up del z; ETH empieza a operar cuando
  tiene 60 días válidos (~fin de enero 2022).
- Costos: perp 0.05 % + slippage 0.02 % por lado (ida y vuelta 0.14 %); funding
  pagado/cobrado durante el trade con las liquidaciones reales de Binance en
  (entrada, salida].

## 4. Estadística (cambio respecto de H-POS1, declarado)

BTC y ETH suelen señalar los mismos días y sus retornos están muy correlacionados: la t
por trade de H-POS1 trata como independientes trades que no lo son. Por eso la t
decisoria se calcula sobre la **serie DIARIA del portafolio**:

- Libro por símbolo con capital 1: en un día dentro de un trade, exceso = retorno del día
  (posición × retorno del perp − posición × funding del día − costos de entrada/salida en
  sus días) − tasa libre del día; en un día sin posición, exceso = 0 (el efectivo rinde la
  tasa libre). Portafolio = 50 % BTC + 50 % ETH (el libro de ETH en efectivo hasta que
  puede operar).
- **t de Newey-West** (Bartlett, **5 rezagos**) de los excesos diarios del portafolio.
- Se reporta además la t por trade de H-POS1 (no decide).

## 5. Criterio (por hipótesis)

**PASA** si cumple TODO:
1. exceso anualizado (media diaria × 365) > 0;
2. t NW ≥ **2.50**;
3. n ≥ **30** trades (BTC + ETH);
4. exceso > 0 en ambas mitades (corte en la mitad calendario de la ventana, 2023-05-02);
5. exceso > 0 con costos × 2;
6. datos válidos: ≥ 90 % de días válidos de la señal en la ventana para cada símbolo
   (un símbolo inválido queda fuera; si quedan los dos fuera, la hipótesis es INVÁLIDA).

Si no pasa, la familia se cierra sin re-cortes (otros umbrales, otra dirección, otra
columna u otro horizonte = pre-registro NUEVO).

## 6. Predicción declarada

Las tres **probablemente NO PASAN**: H-POS1 no encontró nada con la columna hermana, el
posicionamiento de Binance es público y gratuito (lo mira todo el mercado) y 15 de 16
familias ya cayeron. Si alguna da señal, la más plausible es H-OI1 (barridas de
liquidaciones con rebote), con H-TT1 la menos (el "dinero informado" de un ranking público).

## 7. Limitaciones

- Un solo exchange; riesgo de contraparte no modelado.
- Precio de cierre diario: no se modela el slippage de entrar justo a las 00:00.
- La definición de "top trader" de Binance puede haber cambiado en el período (no
  documentado públicamente).
- BTC aporta ~2 meses más de trades que ETH.

Firmado (protocolo): k = 3, un tiro por hipótesis, ventana fija, umbral t ≥ 2.50 (NW).

## Adenda 1 (2026-10-05; después de la primera corrida, ANTES de evaluar H-TT1b)

Datos: 2.700/2.700 checksums oficiales OK (código congelado dd9e59d). La primera corrida
dio H-OI1 exceso −4.6 %/año (t_NW −0.31, n 166), H-TK1 −25.0 %/año (t_NW −1.29, n 244) y
H-TT1 INVÁLIDA (cobertura 69 %, 0 trades). Verificado sobre el dataset completo:

a) **La fuente trae vacías ("") las columnas de top traders** (y el taker de `metrics`)
   en 2021-12-31 → 2022-01-29, 2022-01-31 → 2022-05-27 y 2022-06-25 → 2022-12-14, en BTC
   y ETH (comprobado abriendo los crudos de 2022-03-01 y 2022-08-01). No es un error de
   parseo: H-TT1 queda INVÁLIDA bajo este pre-registro. **Ningún trade ni estadística de
   top traders se calculó.**
b) **Bug de limpieza:** hay registros con `sum_open_interest` = 0 (imposible; 448 en BTC,
   184 en ETH), y en 5 días el cierre es 0 (BTC 2022-03-07, 2024-07-13, 2024-07-14; ETH
   2022-03-07, 2024-07-10). ln(0) = −∞ disparó trades sobre basura y anuló ~90 días de z
   después de cada caso. **Corrección:** valores ≤ 0 se tratan como faltantes antes de
   tomar el último registro del día (vale para cualquier columna de stock). H-OI1 se
   vuelve a correr; se reportan ambos resultados y el veredicto usa el corregido.
c) **H-TT1b (hipótesis nueva, misma regla que H-TT1):** ventana decisoria
   **2022-12-15 → 2024-10-01**, el único tramo continuo con la columna completa en ambos
   símbolos (el z se calienta dentro del tramo: opera cuando hay 60 días válidos). Mismos
   criterios del §5, con la mitad calendario de esta ventana. Como H-TT1 nunca produjo un
   número, la tanda sigue con 3 evaluaciones efectivas (H-OI1, H-TK1, H-TT1b) y umbral
   t ≥ 2.50.
