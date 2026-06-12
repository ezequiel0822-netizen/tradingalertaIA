# MAPA DE EDGE Y RUTA — Trading Alert AI

> **Capturado el 2026-06-12.** Documento compañero de `ESPEC_BACKTEST_REPLAY_v1.md`.
> Preserva TODO el análisis estratégico de la conversación del 12-jun: el diagnóstico
> honesto, de dónde puede salir edge retail de verdad, qué NO ayuda, la decisión de
> arquitectura de los dos motores, y el orden completo de la ruta. La espec es el CÓMO
> de la primera etapa; este documento es el PORQUÉ y el QUÉ SIGUE. Guardado en la raíz
> del repo junto a los docs maestros.

---

## 1. Diagnóstico honesto (la base de todo lo demás)

**Base rates externos (investigados y citados el 12-jun):**

- **Brasil, futuros de equity** (Chague/De-Losso/Giovannetti, todos los que empezaron
  2013-2015): el 97% de los que persistieron 300+ días perdió dinero; solo 1.1% ganó
  más que el salario mínimo; el mejor ganó ~US$310/día con riesgo enorme. Sin evidencia
  de aprendizaje por experiencia.
- **Taiwán** (15 años de data del mercado completo): <1% de los day traders logró
  retornos positivos persistentes netos de comisiones.
- **Regulación europea (ESMA):** 74-89% de las cuentas retail de CFD pierden dinero.
  **CFTC (EE.UU.):** ~2 de cada 3 traders retail de forex pierden cada trimestre.
- La automatización quita la emoción, pero no crea edge donde no lo hay: los bots
  retail no escapan a estos números.

**Data propia (la respuesta provisional ya la dio el bot):**

- ~120-189 trades limpios: TODAS las estrategias en R negativo neto de costos.
- El único +R agregado (`forex_session_breakout` +0.38R, n=86) lo carga el lado short
  de un régimen (shorts +1.81R vs longs −0.31R). Eso no es edge: es estar del lado
  correcto de una tendencia. Demostrado en vivo: +$312 el 9-jun, pérdida el 10-jun con
  el mismo libro.
- Desde el baseline limpio post-bug: ~plano.

**Probabilidad honesta:**

- Edge durable con el setup intradía actual: un dígito bajo (2-5%).
- Reposicionado a D1 + régimen + costos + validación histórica: mejora varias veces,
  pero sigue siendo apuesta minoritaria.
- El valor YA capturado del proyecto: skills (Python, estadística, risk management,
  infraestructura) + la maquinaria de medición honesta. Eso vale más que lo que el bot
  probablemente genere tradeando — y no depende de que aparezca el edge.

## 2. La idea central (no olvidar nunca)

La ventaja retail nunca es cognitiva — es **ESTRUCTURAL**. El mercado no paga
"comprender mejor": toda la comprensión posible sobre data pública ya está metida en el
precio. Un bot que "entiende profundamente" pero opera con la misma información obtiene
los mismos resultados.

La diferencia posible no es contra los bancos: es contra el 97% del retail. No se puede
ganar el juego de ellos (intradía, rápido, caro), pero se puede negarse a jugarlo y
jugar el que a ellos no les da el cuerpo: **lento, barato, paciente, descorrelacionado
y brutalmente honesto en la medición.**

## 3. Las 4 fuentes reales de ventaja (en orden de impacto)

### 3.1 Horizonte temporal — la más grande

- HFT y bancos dominan de milisegundos a horas: ese campo está perdido por diseño.
- Nadie domina las semanas: las instituciones no pueden molestarse con posiciones
  chicas y lentas; el retail no tiene clientes, ni benchmark trimestral, ni presión de
  carrera.
- Las únicas anomalías con décadas de evidencia académica multi-activo (trend-following
  / momentum) viven en D1/W1.
- El spread se amortiza en días en vez de pagarse por hora; el ruido baja; la muestra
  es más limpia.
- **ESTADO:** encarnado en `trend_following_d1` (ESPEC §9). El motor D1 evalúa 1
  vez/día: casi gratis en hardware, cero presión en el hot path.

### 3.2 Régimen — "saber si el mercado está tranquilo o movido"

- Es un filtro de régimen: reglas tontas (precio vs SMA200 + pendiente; terciles de
  ATR; VIX/DXY como extensión futura). Lo simple gana acá porque lo complejo se
  overfittea. No es un cerebro que "comprende".
- El hallazgo shorts +1.81R / longs −0.31R fue la lección: codificar la alineación con
  el régimen en vez de descartarla como ruido.
- Caveat honesto: los regímenes se identifican tarde. El filtro evita pelear contra la
  tendencia; no predice los giros.
- **ESTADO:** `regime_filter.py` (ESPEC §8), doble uso: gate del trend D1 + dimensión
  de slicing para TODAS las estrategias (ahí se responde si el +R del session breakout
  era régimen o era edge).

### 3.3 Costos — la única "ventaja" 100% garantizada

- Con edge bruto cercano a cero, cada pip de costo es R puro. Bajar el costo por trade
  desplaza toda la distribución de R hacia arriba sin predecir nada.
- Operar menos, más lento, evitar spreads abiertos en noticias (el calendar gate ya lo
  hace). Si algún día hay go-live: la elección de broker es parte del edge.
- **ESTADO:** cost model con pesimismo ×1.25 y stress obligatorio ×1.5 (ESPEC §7). Un
  edge que no sobrevive costos pesimistas no es edge.

### 3.4 Información que el precio todavía no digirió

- Realista y gratis para retail: COT (CFTC, posicionamiento institucional semanal,
  valor documentado en horizontes de semanas), estacionalidad, sentimiento retail como
  contraindicador.
- Memecoins: data on-chain (Fase 7 del roadmap viejo) sería asimetría informacional
  real contra los que solo miran velas — pero cuesta plata y el venue sigue siendo PvP
  contra insiders.
- **ESTADO:** DIFERIDO a v3.7+ (ESPEC §17). El collector de COT es el primer candidato.

## 4. Eficiencia de muestra — cómo encontrar R más rápido

- El walk-forward backtester es el arma subutilizada: 10 años de barras D1 = miles de
  trades simulados en horas, contra 400 trades vivos que tardan meses. Pipeline
  correcto: **hipótesis → backtest con costos → walk-forward OOS → paper → demo →
  gates.** La data viva CONFIRMA; el backtest DESCUBRE y DESCARTA.
- Honestidad de correlación: 7 pares USD no son 7 muestras independientes — son ~1.5
  apuestas (el 10-jun lo demostró: 7 posiciones eran UNA apuesta long-USD y un
  movimiento las barrió juntas). El n efectivo crece con instrumentos descorrelacionados
  (índices, commodities en D1), no con más pares de dólar. Antes de sumarlos: evaluar
  disponibilidad y spreads reales en MetaQuotes-Demo. DIFERIDO (§8 de este doc, etapa
  v3.8).
- No multiplicar estrategias por volumen: las comparaciones múltiples inflan falsos
  positivos. Por eso la espec impone Modo A primero, tope de 9 configs, y contabilidad
  de intentos siempre visible.

## 5. Anti-lista — lo que NO va a dar edge (resistir la tentación)

- Más ML sobre el mismo OHLCV que tienen millones de personas.
- Más indicadores técnicos apilados.
- LLMs "razonando" o "comprendiendo" trades — la inteligencia es commodity; el moat es
  estructural + informacional, nunca cognitivo.
- Microestructura de ticks con latencia retail en una laptop: para alfa es imposible
  (territorio HFT); como defensa contra malos fills, aceptable.
- Más estrategias por cantidad.
- El LLM/ML del proyecto siguen SUBTRACTIVOS (vetan, explican, jamás habilitan).
  Correcto como está — no cambiar.

## 6. Arquitectura: dos motores, UN proceso

- **SÍ:** motor D1 conviviendo con el libro intradía dentro del mismo proceso.
  Precedente ya probado: el scalping engine (thread propio, caps propios, halt propio,
  mismas barandas compartidas).
- **NO:** segundo PowerShell / segundo proceso contra la misma cuenta MT5 y la misma
  SQLite — recrea exactamente el caos de mayo (posiciones huérfanas, órdenes
  duplicadas, el reconciler de un proceso peleando contra el otro, contención de la
  DB). La aislación que se busca es LÓGICA (estrategia, medición, caps y apagado
  separados), no FÍSICA.
- La maquinaria de medición ya separa todo por estrategia: `/expectancy` y `/edge`
  muestran cada libro como filas independientes, cada uno con su propio promotion gate.
  Es un A/B test con frenos compartidos (risk manager, cap USD, calendar gate,
  kill-switch cubren a ambos).
- Mientras tanto, el libro intradía sigue corriendo: genera la data con features
  (70→400) que necesita la Fase D. Nada del roadmap actual se pierde.
- **COMPROMISO INNEGOCIABLE:** dejar que el promotion gate mande a shadow al libro que
  pierda cuando llegue la evidencia. "Tener ambos" jamás puede volverse excusa para no
  apagar nada.

## 7. La forma realista del éxito (para calibrar expectativas)

Si TODO sale bien — el trend D1 pasa los criterios del §11 de la espec, sobrevive paper
y demo, los gates se ponen verdes — "funcionar" significa: **un dígito alto anual, con
drawdowns del 15-30% y años planos en el medio.** No hacerse rico. No vivir de esto.

Y la otra cara, igual de importante: si los criterios nunca se cumplen, eso NO es
fracaso del proyecto — es el proyecto funcionando exactamente como fue diseñado:
midiendo la verdad y evitando quemar dinero real en algo sin edge probado.

## 8. La ruta completa (orden y gates)

| Etapa | Qué | Gate |
|---|---|---|
| **v3.6.0 — AHORA** | `ESPEC_BACKTEST_REPLAY_v1.md`: harness de replay + `regime_filter` + `trend_following_d1` + veredicto Modo A (y Modo B solo si amerita) | Criterios §11 de la espec, escritos antes de correr |
| **v3.7 — candidatos** | Integración VIVA del motor D1 al ciclo (solo si pasó §11; entra como estrategia opt-in al router, evaluación diaria) · Collector de COT · Backfill macro VIX/DXY (regla estricta "solo close del día previo") · Salidas en granularidad H1 para trades D1 | Cada pieza: opt-in OFF + soft-fail + tests propios + merge del user |
| **v3.8+** | Instrumentos descorrelacionados (índices/commodities D1; evaluar data y spreads en demo primero) · Estacionalidad · Sentimiento retail contrario | Evaluación previa documentada antes de codear |
| **Sin cambios** | Fase D (400 trades VIVOS con features — el backtest no cuenta), Fase E, `GO_LIVE_RUNBOOK.md`, real-money BLOQUEADO (`ENABLE_REAL_TRADING=false` HARDCODED) | Los de siempre — este documento no toca ninguno |

## 9. Compromisos anti-autoengaño (transversales a toda la ruta)

1. Hipótesis y criterios de aceptación POR ESCRITO antes de correr nada. Prohibido
   ajustar hasta que pase.
2. El backtest jamás cuenta para `/readiness`, `/expectancy`, `/edge` ni los 400 de la
   Fase D.
3. La contabilidad de configs probadas (`n_configs_tested`) siempre visible junto al
   mejor resultado.
4. El gate ejecuta la sentencia; el humano solo enciende flags de paper. Nada se
   promueve solo.
5. Medir el éxito del proyecto por lo aprendido y por la honestidad de la medición —
   no por el balance de la demo.

---

*Capturado el 2026-06-12 entre el user y Claude. Compañero de
`ESPEC_BACKTEST_REPLAY_v1.md`. Si en una sesión futura hay conflicto entre la ambición
y este documento, releer el §1.*
