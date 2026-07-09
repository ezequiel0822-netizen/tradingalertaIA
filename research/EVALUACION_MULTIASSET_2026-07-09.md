# Evaluación previa — Instrumentos descorrelacionados (índices/commodities D1)

> **Gate del MAPA §8 (etapa v3.8+): "Evaluación previa documentada antes de codear".**
> Este documento ES esa evaluación. Fecha survey: 2026-07-09, MetaQuotes-Demo,
> script read-only (initialize/symbol_info/shutdown, proceso propio — cero órdenes).
> Nada de código nuevo de estrategia: la hipótesis usaría `trend_following_d1`
> **CONGELADA desde v3.6.0, sin tocar un solo parámetro** (k=1, no es dredging:
> es la MISMA regla sobre mercados NUEVOS = data nueva, el único tipo de re-test
> que el protocolo permite).

## 1. Por qué esta familia está ABIERTA (y no viola el cierre de jul-2026)

- La búsqueda de edge 2026-07 cerró 9 familias — esta **no estaba entre ellas**:
  el propio MAPA §5/§8 la dejó DIFERIDA ("el n efectivo crece con instrumentos
  descorrelacionados, no con más pares de dólar").
- El trend D1 falló sobre 7 pares FX + oro (v3.6.0). La literatura del time-series
  momentum es explícita: el premium vive en la **diversificación** (30-60 mercados,
  4 clases de activo); 8 mercados correlacionados al dólar no lo testean.
- Regla anti-dredging de este experimento: **una sola hipótesis (k=1)**, estrategia
  congelada, criterio §11 sin cambios, pre-registro commiteado antes de correr.
  Si NO pasa, la familia queda cerrada como las demás — sin re-cortes.

## 2. Survey del broker (MetaQuotes-Demo, 2026-07-09)

12.698 símbolos; 27 índices cash + metales spot. **No hay CFDs de energía**
(petróleo/gas: el "WTI" listado es una acción del Nasdaq, no el crudo) ni de
agrícolas → el universo alcanzable es **índices + plata** (+ oro/FX ya cacheados).

### Candidatos con spread y financiamiento medidos

| Símbolo | Precio | Spread (bps) | swap_mode | swap L/S | Financiamiento long aprox (%/año) |
|---|---|---|---|---|---|
| DE40 | 24 967 | **0.20** | 3 (% anual) | −0.70/−1.12 | −0.7 |
| US30 | 52 411 | **0.23** | 3 | −2.21/−1.99 | −2.2 |
| USTEC | 29 487 | **0.34** | 3 | −0.82/−0.75 | −0.8 |
| SWI20 | 14 196 | **0.56** | 3 | −0.53/−0.93 | −0.5 |
| US500 | 7 505 | **0.67** | 2 (USD/lote/noche) | −0.31/−0.26 | −1.5 |
| XAUUSD | 4 116 | **0.78** | 1 (points) | −12.6/−4.6 | −1.1 |
| NETH25 | 1 082 | **0.92** | 3 | −0.04/−0.06 | −0.04 |
| UK100 | 10 228 | **1.08** | 3 | −5.1/−2.0 | −5.1 |
| JPN225 | 68 010 | **1.32** | 0 (DESHABILITADO) | — | 0 (demo) |
| SE30 | 3 164 | **1.39** | 3 | −0.17/−0.09 | −0.2 |
| FRA40 | 8 289 | **1.93** | 0 (DESHABILITADO) | — | 0 (demo) |
| AUS200 | 8 758 | **2.28** | 3 | −6.83/−0.42 | −6.8 |
| EUSTX50 | 6 253 | **3.04** | 0 (DESHABILITADO) | — | 0 (demo) |
| HK50 | 23 937 | **3.34** | 0 (DESHABILITADO) | — | 0 (demo) |
| XAGUSD | 59.4 | **8.92** | 1 | −2.3/+0.2 | −1.4 |

### Excluidos y por qué

| Símbolo | Motivo |
|---|---|
| US2000 | spread 18.5 bps (inviable para el cost model) |
| IT40, SA40, CHINA50, CHINAH, MIDDE50 | spreads 15-80 bps |
| XPTUSD, XPDUSD | spreads >100 bps |
| ESP35 | swap corto −18%/año, spread 11 bps |
| Energía/agrícolas | NO existen en este broker |

## 3. ⚠️ Caveats de honestidad (leer antes del pre-registro)

1. **Los swaps del demo son irrealmente baratos.** Cuatro símbolos tienen el swap
   directamente DESHABILITADO (mode 0) y el resto cobra 0.04-2.2%/año en su mayoría.
   Un broker real de CFDs cobra ~tasa base + 2.5-3% de markup (≈6-8%/año long con
   tasas 2026). Un trend D1 mantiene posiciones semanas/meses → **el financiamiento
   es EL costo dominante de esta familia**, igual que el swap mató al carry.
   → El pre-registro DEBE incluir escenarios de estrés de financiamiento
   (0% / 3%/año / 6%/año de drag proporcional al holding period) y el veredicto
   §11 se evalúa sobre el escenario MEDIO (3%), no el del demo.
2. **Profundidad D1 desconocida hasta backfillear**: MetaQuotes suele dar 10-20+
   años en índices majors, pero se mide con el loader (que reporta rango real y
   sospecha de truncamiento). Gate de suficiencia: **≥10 símbolos con ≥10 años**
   de D1; si no se llega, el experimento se documenta como NO-FACTIBLE-AÚN.
3. **Los índices comparten beta global**: 13 índices no son 13 muestras
   independientes (≈ 3-5 apuestas: US, Europa, Asia, metales). El n efectivo sube
   vs FX-only, pero menos de lo que parece. Se declara en el pre-registro.
4. **Dividendos**: los índices cash CFD ajustan por dividendos vía swap/ajustes que
   el cache D1 no captura → sesgo alcista de precio en índices price-return… los
   índices CFD siguen al futuro/price index. El drag de dividendos no modelado se
   cubre dentro del estrés de financiamiento (declarado, no ocultado).
5. Encuesta del 9-jul: spreads fuera de horario pico pueden diferir; el cost model
   del harness ya castiga con pesimismo (spread + slippage), se mantiene.

## 4. Universo propuesto (pendiente de confirmar profundidad)

**Núcleo (spread <2.5 bps):** US500, US30, USTEC, DE40, UK100, JPN225, SWI20,
NETH25, SE30, FRA40, AUS200 (11 índices)
**Extensión:** EUSTX50, HK50 (3-3.5 bps), XAGUSD (8.9 bps, único commodity nuevo)
**Ya cacheados:** XAUUSD + 7 pares FX (32-53 años D1)

Total potencial: **~22 mercados, 4 bloques** (US, Europa, Asia-Pacífico, metales+FX).

## 5. Informe de research externo (2026-07-09, agente web con fuentes)

Resumen del informe (fuentes: MOP 2012, AQR Century of Evidence/Trends Everywhere,
Huang et al. 2020 JFE, SG Trend Index, FXCM/CME financing docs, Man Group):

- **El premium TSMOM 3-12 meses es probablemente real** (positivo cada década desde
  1880) PERO el realizado neto post-2010 es mediocre: SG Trend ~4.9%/año desde 2000
  (SR ~0.3-0.35), −15% en los 12 meses a jun-2025.
- **Huang et al. 2020 (JFE)**: en índices, gran parte del "trend" es indistinguible
  del drift (estar long). Y el drift es EXACTAMENTE lo que el financiamiento CFD
  confisca.
- **Financiamiento CFD real** (no el del demo): benchmark + 1.5-3% markup sobre el
  nocional COMPLETO, diario → long índice paga ~6.5-7%/año, recibe ~1.3-1.8% de
  dividendos → **costo neto ~5%/año contra un drift histórico de 7-9%**. Un Donchian
  D1 long ~50% del tiempo arranca cada trade con ~0.5-1.2% de handicap de swap.
  El short recibe ~1% o queda neutro (no salva).
- **Breadth honesto**: con 10-20 mercados donde los índices son casi 1 sola apuesta,
  el multiplicador de diversificación es ~1.5-2×, no el 3× de 58 futuros.
  **Esperable: SR 0.35-0.6 GROSS → 0.15-0.4 NETO retail** — por debajo del 0.7 del
  overnight equities que ya se descartó por no accionable.
- Data nueva con literatura real y accesible: term structure del VIX (filtro de
  régimen, gratis), EIA API (energía — pero este broker NO tiene energía), short
  interest agregado (mensual, equities US). Sentimiento retail de brokers: plausible,
  sin literatura independiente. Google Trends/news sentiment D1: muertos.

**Veredicto del research: "No en índices por el lado long, marginal en el resto."**

## 6. Decisión y siguiente paso

**LUZ AMARILLA — se pre-registra y se corre UNA vez, con la predicción declarada
de probable NO PASA**, porque: (a) el costo del experimento es horas offline (la
data es gratis vía MT5 y el harness existe); (b) el proyecto cierra familias CON
EVIDENCIA, no con vibes — igual que el viernes del oro se corrió declarando su
dilución de R; (c) el modelado del financiamiento convierte el run en el test
DEFINITIVO de la familia. Condiciones duras del pre-registro:

1. Estrategia `trend_following_d1` CONGELADA (v3.6.0), k=1, sin variantes.
2. **Cost model con financiamiento por día de holding**: escenario central
   5%/año long / 1%/año short en índices (números del research, NO los swaps
   del demo); metales/FX con sus swaps medidos. Extensión harness-only al
   cost model, con tests.
3. **Regla descalificadora pre-declarada**: si el resultado agregado pasa §11
   pero el P&L viene SOLO de longs de índices, se declara "beta apalancada con
   peaje, no edge" → NO PASA. (Recomendación explícita del research.)
4. Gate de data: ≥10 símbolos con ≥10 años D1 (probe en curso).
5. Si NO pasa: familia "instrumentos descorrelacionados vía CFD retail" queda
   CERRADA como las otras 9, sin re-cortes ni segundo tiro.

La alternativa de nivel proyecto queda anotada con los números del research:
el premium que esta familia persigue se cosecha bien con FUTUROS o sin
apalancamiento — vehículos fuera de este bot (misma conclusión que E2 overnight).
