# Pre-registro B4b — short Hyperliquid / long Binance (perp-perp), BTC y ETH, paper hacia adelante

> **Commiteado ANTES de bajar un solo dato de las ventanas que deciden** (protocolo del
> proyecto). Familia 16 del ledger (`research/LEDGER_FAMILIAS.md`), k = 2 (BTC, ETH), un
> tiro por activo. Research-only: no toca el bot, ni flags, ni MT5, ni el .env.
> Real-money sigue HARDCODED bloqueado; un PASA no lo cambia (ver §11).

## 0. Origen y contaminación (declarado antes de correr)

- B4b sale de una evaluación exploratoria SIN pre-registro (agente de ramas del carry,
  commit 62f8905, `EVALUACION_RAMAS_CARRY_2026-10-04.md`) que miró **2024-10-01 →
  2026-10-03** de Hyperliquid, Binance, Bybit, OKX y Bitget. Esa ventana es IN-SAMPLE:
  **no puede decidir** y no se vuelve a bajar ni a usar para nada (§3).
- El apalancamiento (§4) y la predicción (§9) se eligieron CONOCIENDO esos números. Por
  eso la ventana decisoria es hacia adelante: lo que se eligió mirando el pasado se juzga
  con datos que todavía no existen.
- **Ventana secundaria 2023-05 → 2024-09:** verificado el 2026-10-04 que todos los datos
  del agente (`trading_data/ramas_carry/funding_all.csv` y `funding_hl.csv`) arrancan el
  2024-10-01 en todos los venues y monedas (solo se leyeron fechas mín/máx y conteos, sin
  estadísticas), y que sus scripts fijan `START = 2024-10-01`. El funding de Hyperliquid y
  el spread HL − Binance de ese tramo NO se vieron. **Matiz:** el funding de Binance
  BTC/ETH de 2023-2024 sí apareció como contexto anual en H-FC1 (p. ej. BTC 2024 11.9 %
  anualizado): el nivel de UNA pata está parcialmente visto; el spread, no.

## 1. Hipótesis

El funding de Hyperliquid ancla a una tasa de interés fija de 0.01 % cada 8 h (0.00125 %
por hora, ≈ 11.6 % APR pagado a los shorts) mediante
`F = P + clamp(0.01 % − P, −0.05 %, +0.05 %)` y se paga cada hora
([docs, verificado 2026-10-04](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/funding)).
En el régimen actual Binance cobra menos. Short perp en Hyperliquid + long perp en Binance,
misma cantidad de monedas, cobra ese spread sin exposición direccional.

La pregunta que decide: **hacia adelante, neto de comisiones, transferencias entre
venues, rebalanceos y riesgo de liquidación, ¿rinde más que la tasa libre (EFFR) sobre el
capital TOTAL inmovilizado en los dos venues?**

## 2. Datos (fijados acá)

| Serie | Fuente | Checksum |
|---|---|---|
| Funding Hyperliquid BTC, ETH (horario) | `POST https://api.hyperliquid.xyz/info` `{"type":"fundingHistory","coin":…,"startTime":…,"endTime":…}`; máx. 500 registros por respuesta → paginar | Sin checksum oficial: sha256 propio de cada respuesta cruda |
| Velas 1 h Hyperliquid BTC, ETH | idem, `{"type":"candleSnapshot","req":{"coin":…,"interval":"1h",…}}`; **solo las 5000 velas más recientes** (≈ 208 días) | idem |
| Funding Binance BTCUSDT, ETHUSDT (USDⓈ-M) | data.binance.vision `futures/um/monthly/fundingRate`; lo que el archivo todavía no cubra, REST `fapi/v1/fundingRate` guardado por el colector (rotulado) | Oficial (`.CHECKSUM`) / sha256 propio |
| Velas 1 h perp Binance BTCUSDT, ETHUSDT | data.binance.vision `futures/um/{monthly,daily}/klines/…/1h`; REST `fapi/v1/klines` para el tramo no archivado | Oficial / sha256 propio |
| Tasa libre | EFFR del NY Fed (API `markets.newyorkfed.org`), as-of, ACT/360 | sha256 propio |

Manifest con sha256 de todo lo bajado, como en H-FC1/H-MS1. Normalización de klines por
archivo (unos traen encabezado y otros no). Timestamps de funding redondeados a la hora
(Binance trae offsets de milisegundos).

## 3. Ventanas

- **DECISORIA (hacia adelante): `T0 → T1`**, con **T0 = primera 00:00 UTC posterior al
  timestamp del commit de este archivo** y **T1 = T0 + 182 días** (26 semanas exactas).
  Fecha de fin FIJA: no se extiende ni se acorta según cómo venga.
- **SECUNDARIA (requisito, no vista): `S0 → 2024-10-01 00:00 UTC`**, con S0 = primera
  00:00 UTC en que hay funding de Hyperliquid para esa moneda y velas 1 h de Binance, no
  antes de 2023-05-01. Si el funding de HL arranca más tarde, S0 se corre y se reporta.
- **PROHIBIDA: 2024-10-01 → T0.** No se baja ni se usa (salvo un colchón de 48 h antes
  de T0 que baja el colector para alinear, que no entra en ninguna métrica).
- **Orden:** la secundaria se corre en cuanto el código esté congelado y verificado con
  datos sintéticos (esta semana). Si un activo NO PASA la secundaria, queda cerrado y no
  se espera el forward; si no pasa ninguno, B4b se cierra y el colector se apaga.

## 4. Estrategia (parámetros FIJOS)

Un libro independiente por activo, capital inicial C = 1 (referencia US$10.000 para los
costos fijos), mitad en cada venue.

- **Apalancamiento por pata L = 3** sobre el equity de ESE venue: nocional por pata
  N = 3 × C/2 = 1.5 C. Retorno bruto ≈ spread × 1.5. (A 2x el techo es spread × 1: BTC
  quedaría mecánicamente debajo de la EFFR y el test estaría perdido de antemano; más de
  3x acerca la liquidación con la demora de transferencia.)
- **Cantidad**: q = N / P_Binance(T0) monedas en AMBAS patas (delta neutral en monedas).
- **Entrada** en T0 y **salida** en T1 (o S0 / S1) al precio de apertura de la vela 1 h de
  cada venue, pagando costos (§5) en ambas patas.
- **Funding**: cada liquidación en τ cuenta si `apertura < τ ≤ cierre` de la posición.
  HL (horario): la pata short cobra `q × P_HL(τ) × f_HL(τ)` (paga si f < 0). Binance (en
  sus horarios reales, normalmente cada 8 h): la pata long paga `q × P_BN(τ) × f_BN(τ)`.
  P(τ) = cierre de la vela 1 h que termina en τ (proxy del oracle/mark; declarado).
- **Mark-to-market horario**: equity de cada venue = depositado ± funding acumulado ±
  PnL de su pata a precio de cierre de SU venue (la brecha de precio HL − Binance entra
  al PnL).
- **Liquidación** (chequeo horario con extremos de la vela): la pata HL se liquida si su
  equity evaluado al MÁXIMO horario de HL ≤ MM_HL × q × máximo; la pata Binance si su
  equity al MÍNIMO horario ≤ MM_BN × q × mínimo. MM_HL = mitad del margen inicial al
  apalancamiento máximo ([docs](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/margining)):
  BTC 40x → **1.25 %**, ETH 25x → **2.0 %**. MM_BN = **1.0 %** (UNVERIFIED; más
  conservador que el escalón base publicado de ~0.4-0.5 %). Consecuencia: se pierde TODO
  el equity de ese venue, la otra pata se cierra al cierre de esa hora con costos y el
  libro queda en efectivo (sin rendimiento) hasta el fin de la ventana. El gate exige cero.
- **Rebalanceo**: al cierre de cada hora, si `min(equity_v / (q × P_v)) < 0.20` en algún
  venue y no hay uno pendiente, se agenda un rebalanceo que se **ejecuta 24 h después**
  (puente + operador humano), haya o no vuelto el ratio. Al ejecutar: E = E_HL + E_BN; se
  transfiere |E_HL − E/2| al venue pobre (costo §5) y se re-dimensiona a N' = 1.5 × E
  después de costos, operando |q' − q| en ambas patas. Las liquidaciones se siguen
  chequeando durante la demora. Referencia a 3x: la pata HL toca el gatillo con +11 % y
  se liquida con ~+31 %; la de Binance, con −17 % y −33 %.
- **Colateral**: no rinde nada (USDT en la billetera de futuros, USDC en HL), igual que
  H-FC1.
- **Secundaria**: velas 1 h de Hyperliquid NO disponibles para 2023-2024 (límite de 5000)
  → se usa el precio del perp de Binance como proxy para la pata HL (MTM, funding y
  liquidación) y se suma **0.03 %** de slippage extra a cada operación de la pata HL por la
  brecha no observable.

## 5. Costos por lado y por operación

| Concepto | Valor | Estado |
|---|---|---|
| Taker Hyperliquid (nivel 0) | 0.045 % | Verificado en docs oficiales 2026-10-04 |
| Taker Binance USDⓈ-M (usuario regular) | 0.05 % | FAQ oficial de Binance (act. 2026-05-01); la tabla dinámica no se pudo leer |
| Slippage por pata | 0.02 % | Supuesto (BTC/ETH, ambos venues líquidos) |
| Transferencia entre venues (USDT↔USDC + puente/retiros) | 0.10 % de lo transferido + US$5 fijos (0.0005 C) | UNVERIFIED, conservador |

Escenario de estrés obligatorio: todos los costos × 2 (§6.6).

## 6. Criterio de veredicto (por activo, idéntico en ambas ventanas)

Retornos semanales = bloques de 7 días desde T0 (o S0) sobre el equity total MTM; exceso
semanal = retorno − tasa libre compuesta de esos 7 días (EFFR as-of, ACT/360).

**PASA la ventana** si cumple TODO:
1. Exceso anualizado (media semanal × 52) > 0, neto de todo costo;
2. **t de Newey-West** (Bartlett, 4 rezagos) de los excesos semanales **≥ 2.50**. El
   funding es persistente → los excesos semanales están autocorrelacionados y la t simple
   los sobreestima; se reporta también la t simple, que NO decide;
3. drawdown máximo del equity horario ≤ **10 %**;
4. **cero** liquidaciones;
5. exceso > 0 en ambas mitades (13 + 13 semanas en la decisoria; mitades por semanas en la
   secundaria);
6. exceso > 0 con todos los costos × 2.

**Un activo PASA** si pasa la secundaria Y la decisoria. **B4b PASA** si al menos un
activo pasa (k = 2). Si ninguno pasa, la familia se cierra sin re-cortes: otros
apalancamientos, otros umbrales, otras monedas u otros venues = pre-registro NUEVO.

## 7. Calidad de datos (se reporta; puede invalidar, nunca "arreglar")

- Horas faltantes de funding HL o de velas (HL en la decisoria, Binance en ambas) se
  cuentan. Si superan el **1 %** de las horas de la ventana, esa ventana es **INVÁLIDA**
  para ese activo (no puede pasar). Funding faltante = 0, sin imputar.
- Inmutabilidad: al evaluar se vuelve a bajar el funding de HL y se compara con lo que
  guardó el colector; cualquier diferencia se reporta y se usa la versión re-bajada.
- Binance: REST guardado vs. archivo oficial donde se superpongan; diferencias reportadas.
- Archivos con checksum oficial que no coincide: se excluyen y cuentan como faltantes.

## 8. Disciplina hacia adelante (anti-espiar)

- **Nadie calcula ni mira PnL, spread ni funding medio del tramo T0 → T1 antes de T1.**
  El colector reporta solo salud de datos (filas, primera/última marca, huecos).
- El script de evaluación se niega a evaluar la decisoria si `ahora < T1 + 1 día`.
- Colector `scripts/b4b_forward_collector.py`: idempotente, guarda respuestas crudas
  comprimidas + sha256 por corrida en `trading_data/b4b_forward/` (fuera de git), detecta
  valores que cambien entre corridas. Cadencia semanal (Programador de tareas de Windows).
  El funding histórico se puede re-bajar siempre; las velas de HL solo ~208 días hacia
  atrás → tolera hasta ~29 semanas sin correr, pero el forward completo (182 días) solo
  se puede recuperar entero con una corrida antes de T0 + 5000 h (≈ fin de abril 2027).
- Evaluación: después de T1, cuando data.binance.vision publique el mensual que contiene
  T1 (primeros días de mayo 2027); el tramo que falte se cubre con el REST del colector.
- Código congelado: `scripts/b4b_study.py` se commitea y se verifica con datos
  sintéticos (spread constante → retorno conocido; shock de precio → liquidación;
  gatillo + demora de 24 h; bordes de funding en apertura/cierre; huecos → INVÁLIDO;
  guard de fecha) ANTES de bajar la secundaria. El mismo código evalúa el forward en
  2027; un bug encontrado después se arregla con commit propio y se declara en el
  veredicto.

## 9. Predicción declarada

- **BTC: NO PASA** (spread reciente ~2 pp × 1.5 ≈ 3 % bruto, debajo de una EFFR de
  ~3.6-3.9 %).
- **ETH: marginal, probable NO PASA** (por la t con 26 semanas o por el exceso neto de
  entrada/salida y rebalanceos).
- **Secundaria: incierta.** En 2023 el funding de Binance fue bajo (favorece el spread);
  en el rally de 2024 Binance superó a menudo el 11.6 % (spread negativo esas semanas),
  aunque HL también sube cuando la prima supera el clamp.

## 10. Limitaciones y riesgos NO modelables (declarados antes)

- **ADL**: el 10-oct-2025 Hyperliquid hizo ~35k cierres por auto-desapalancamiento. ADL
  cierra posiciones en GANANCIA: en un crash la pata ganadora es el short en HL → queda
  el long de Binance descubierto en plena caída. No modelable con estos datos. Cualquier
  estrés de ADL sería diagnóstico POST-HOC rotulado como tal.
- Contraparte DEX (smart contract, puente Arbitrum, validadores), riesgo de exchange
  centralizado (Binance), USDC vs USDT (depeg no modelado).
- Precio de funding: HL usa el oracle y Binance el mark; acá se usa el cierre horario.
- Comisiones/márgenes pueden cambiar durante la ventana: se usan los fijados acá.
- La demora de 24 h puede ser optimista (puente congestionado, fin de semana) o
  pesimista. Sin margen cruzado entre venues.
- Ejecutabilidad desde México y tratamiento fiscal: no evaluados (fuentes secundarias).
- La secundaria no observa la brecha de precio HL − Binance (proxy + slippage extra).

## 11. Qué habilita cada resultado

- **PASA**: NO habilita dinero real (bloqueado por diseño; además exigiría wallet propia
  y puente). Habilita solo una segunda fase sin dinero —otros 6 meses de paper o un test
  en testnets para medir fills y demoras reales— con pre-registro propio.
- **NO PASA** (lo esperado): familia 16 cerrada, fila en el ledger, colector apagado.

Firmado (protocolo): k = 2, un tiro por activo, ventanas y parámetros fijos, umbral
t ≥ 2.50 (Newey-West), secundaria como requisito.

## Adenda 1 (2026-10-05, ANTES de correr la secundaria; solo se vieron marcas de tiempo)

Al bajar la secundaria (código congelado d9c27a9, 68/68 checksums oficiales OK), el
chequeo de calidad del §7 mostró 570 "horas faltantes" de funding de Hyperliquid
(4.7 %). Inspeccionando SOLO las marcas de tiempo (ninguna tasa, ningún precio, ningún
resultado): **Hyperliquid liquidaba el funding cada 8 h hasta el 2023-06-08 00:00 UTC y
cada hora desde las 01:00** (81 saltos de 8 h, idénticos en BTC y ETH). En el régimen
horario faltan solo 3 horas de ~11.300 (2023-07-02 21h, 2023-08-23 21h, 2024-08-15 14h:
0.03 %). No son datos perdidos: es otra frecuencia de liquidación, que el modelo del §4
(funding horario) no contempla. Aplicar el gate del 1 % al pie de la letra invalidaría
ambas secundarias por un tecnicismo de formato, no de calidad.

**Resolución** (bajo la cláusula del §3 "si el funding de HL arranca más tarde, S0 se
corre y se reporta"): la secundaria arranca en el régimen horario. S0 crudo = primera
00:00 UTC posterior a 2023-06-08 01:00 = 2023-06-09, alineado a semanas enteras antes de
S1 → **S0 = 2023-06-13 00:00 UTC** (68 semanas, ambos activos). Todo lo demás sin
cambios. Implementado como `SEC_HOURLY_FROM` / `secondary_start()` en
`scripts/b4b_study.py`, con caso nuevo en `scripts/b4b_selftest.py`. Si se hubiera
aplicado la regla literal, ambas secundarias serían INVÁLIDAS y B4b se cerraría sin
evaluar.
