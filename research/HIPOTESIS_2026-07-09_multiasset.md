# Pre-registro H-M1 — Trend following D1 multi-asset (índices + plata), neto de financiamiento CFD

> **Commiteado ANTES de correr** (protocolo del proyecto). k=1: UNA hipótesis, UNA
> estrategia CONGELADA, UN tiro. Si NO PASA, la familia "instrumentos
> descorrelacionados vía CFD retail" queda CERRADA sin re-cortes, como las otras 9.
> Contexto y justificación: `research/EVALUACION_MULTIASSET_2026-07-09.md`
> (gate documental MAPA §8, survey MT5 2026-07-09, informe research externo).

## 1. Hipótesis (H-M1)

La estrategia **`trend_following_d1` CONGELADA desde v3.6.0** (Donchian 20-alto/
20-bajo con stop 2×ATR, long y short simétricos — cero parámetros tocados), aplicada
a un universo DIVERSIFICADO de índices bursátiles + plata en D1, produce expectancy
neta que pasa los criterios **§11 de ESPEC_BACKTEST_REPLAY_v1** una vez descontado
el **financiamiento CFD retail** — el costo que el research 2026-07-09 identificó
como dominante y que el demo esconde (swaps deshabilitados/irrisorios).

Racional pre-declarado: el TSMOM multi-asset es el premium mejor documentado
(AQR/MOP), PERO (a) en índices se confunde con el drift (Huang et al. 2020) y el
financiamiento CFD confisca ~5%/año de ese drift; (b) el realizado neto post-2010
de los CTAs es mediocre (SG Trend SR ~0.3). **Predicción declarada: probable NO
PASA en el escenario central de financiamiento.** Si tampoco pasa BRUTO (sin
financiamiento), la familia muere sin ambigüedad ni excusas de costos.

## 2. Data (decidido ANTES de correr, tras el probe del 2026-07-09)

- El gate de suficiencia de la evaluación (≥10 símbolos con ≥10 años) **FALLÓ para
  data MT5-CFD** (solo 6/14; la mitad del universo MT5 arranca en 2019). NO se
  relaja la barra: se cambia la fuente a **Yahoo D1 índices cash** (décadas), vía el
  `stock_historical_loader` existente (S1, anti-429), cacheado en
  `mt5_historical_cache` timeframe 1440 — mismo pipeline que el backtest de acciones.
- El survey MT5 queda como capa de REALIDAD DE EJECUCIÓN: los símbolos elegidos
  existen como CFD tradeable en el broker con spread <3.5 bps (medido 2026-07-09).
- **Universo (13 mercados, fijado acá):** `^GSPC` (S&P), `^DJI` (Dow), `^NDX`
  (Nasdaq100), `^GDAXI` (DAX), `^FTSE` (UK), `^N225` (Nikkei), `^SSMI` (SMI),
  `^AEX` (Países Bajos), `^FCHI` (CAC40), `^STOXX50E`, `^AXJO` (ASX200), `^HSI`
  (Hang Seng), `SI=F` (plata). Sin sustituciones post-hoc: si Yahoo no da data de
  alguno, se corre con los que haya y se reporta.
- FX y oro NO se re-corren (ya tienen veredicto v3.6.0). Índices price-return de
  Yahoo: el drag de dividendos no capturado se declara y queda cubierto por el
  rango de escenarios de financiamiento.

## 3. Costos (números fijados acá, del survey + research con fuentes)

Categoría nueva `index` en el cost model del harness (extensión HARNESS-ONLY con
tests; no toca el ciclo vivo):

- **Roundtrip** (spread+slippage): 0.08% (≈ 2× el spread mediano medido de ~1-3 bps
  + colchón pesimista, coherente con el multiplicador ×1.25/×1.5 de la casa).
- **Financiamiento por día calendario de holding** (nuevo, drag proporcional):
  - Escenario **BRUTO** (referencia): 0%/año — solo para saber si existe ALGO.
  - Escenario **CENTRAL** (el que decide §11): **5%/año long / 1%/año short**
    (benchmark+markup − dividendos; FXCM/CME/Capital.com, research 2026-07-09).
  - Escenario **ESTRÉS**: 7%/año long / 2%/año short.
  - Plata (`SI=F`): mismos escenarios (swap medido en demo −1.4%/año no es creíble).
- Conversión a R: `financing_r = (annual_pct × días_holding/365) / risk_pct`,
  días_holding = bars_held × 365/252 (los swaps CFD cobran los 7 días vía triple).

## 4. Criterio de veredicto (SIN cambios sobre §11)

- **PASA** solo si cumple §11 completo de `ESPEC_BACKTEST_REPLAY_v1.md` en el
  escenario **CENTRAL** (expectancy neta ≥ +0.10R, y el resto de §11: PF, % años
  positivos, ambas mitades, sin concentración, estrés de costos).
- **Regla descalificadora pre-declarada** (recomendación del research): si pasa §11
  agregado PERO la descomposición muestra que los **longs de índices** aportan >80%
  del R neto positivo Y (shorts de índices + plata) son ≤ 0 en conjunto → veredicto
  **NO PASA — "beta apalancada con peaje, no edge"** (largo de índice CFD = pagar
  6-7%/año por exposición que un ETF da gratis).
- Contabilidad de intentos: k=1. No hay Modo B, no hay variantes de parámetros, no
  hay re-cortes por región/periodo si falla. El resultado se documenta en
  CHANGELOG (sección research) gane o pierda.

## 5. Qué habilitaría un PASA (y qué NO)

Un PASA habilita ÚNICAMENTE: proponer la promoción de `trend_following_d1` a
estrategia paper-only del router (opt-in OFF), sobre los símbolos CFD equivalentes
del broker, con el flag y el proceso de siempre. **JAMÁS habilita MT5 demo directo
ni real-money** (esas puertas tienen sus propios gates: ESPEC §12, GO_LIVE_RUNBOOK).

## 6. Implementación mínima requerida (harness-only, ANTES del run)

1. `net_r()` del `trade_simulator`: parámetro opcional de financiamiento
   (annual_pct por lado × días de holding) + categoría `index` en el cost map.
   Con tests unitarios (aritmética a mano).
2. Run config `multiasset_trend_run.json` (mode A, category index, strategy
   trend_following_d1 únicamente).
3. Reporte con descomposición por lado (long/short) y por símbolo — necesaria
   para la regla descalificadora. Si el report actual no la tiene, se agrega
   al report del harness (harness-only).

Firmado (protocolo): predicción = NO PASA en central; si pasa bruto pero muere por
financiamiento, la lección documentada es "el premium existe pero ESTE VEHÍCULO
(CFD retail) lo confisca" — misma familia de conclusión que carry y overnight.
