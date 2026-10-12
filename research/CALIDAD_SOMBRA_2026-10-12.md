# Filtro de calidad en sombra (v3.17.0) — qué se guarda y cuándo se podrá probar

> **Esto NO es un pre-registro.** Es la regla de juego de los datos, fijada ANTES de que
> exista la primera fila. El pre-registro de cualquier hipótesis con estos datos va
> aparte, y recién cuando haya historia suficiente.

## Por qué así

El 10-oct el user trajo un paquete hecho por otra IA ("v3.17 calidad",
`propuestas/2026-10-10_v3.17_calidad/`) con un **quality gate** (filtro de confluencia) y
un buscador de noticias. El paquete promete 58-65 % de acierto y +0.10R. No hay evidencia
de eso:

- 27 familias probadas con pre-registro → 0 operables, incluido operar el reverso de las
  señales (H-FADE1) y los FVG (H-FVG1).
- Los puntos del gate (+15, +12, −18…) están puestos a mano, no salen de datos.
- Prender un filtro así sin medirlo solo baja la cantidad de operaciones. No dice nada
  sobre si mejora la expectativa.

Lo honesto es **anotar qué diría el gate para cada candidato, sin cambiar nada**, y
evaluarlo después con pre-registro, como el exit shadow y el colector de opciones.

## Qué se guarda

Con `ENABLE_QUALITY_GATE=true`, la tabla `quality_gate_shadow` guarda una fila por cada
paper trade que abre el strategy router: acciones, forex y oro.

- **Identidad:** paper trade, fecha UTC, símbolo, categoría, estrategia, dirección,
  versión del gate (`qg1`) y si el candidato fue al agente.
- **Datos de entrada, todos a la fecha de apertura:**
  - Confianza de la señal (`StrategySignal.confidence`) y score de la alerta
    (`AlertRecord.score`). También se guardan los umbrales vigentes:
    `STRATEGY_MIN_CONFIDENCE`, `ALERT_SCORE_THRESHOLD` y `QUALITY_MIN_CONFLUENCE`.
  - Tendencia D1 `up` / `down` / `flat` en forex y oro, con la misma definición y fuente
    que el agente: cache D1 de MT5 si está fresco; si no, D1 de MT5 en vivo, sin la vela
    del día en curso. En acciones no hay dato.
  - Calendario: si hay un evento de alto impacto de las monedas del símbolo dentro de
    `CALENDAR_BUFFER_MINUTES`. Requiere `ENABLE_ECONOMIC_CALENDAR`; en acciones cuentan
    los eventos de USD. Sin datos, queda vacío.
  - Distancia al stop en ATR: |entrada − stop| / entrada, dividido por el ATR %. Es el ATR
    de las mismas velas que usó la estrategia.
  - Noticias, **solo acciones**, y solo titulares publicados **antes** de la apertura:
    - Yahoo Finance: lo que el bot ya bajó en ese ciclo. Se lee de memoria, sin red.
    - Google News RSS, si `ENABLE_WEB_NEWS_ENHANCER=true`. Se busca **después** de la
      decisión: hasta 2 búsquedas por ciclo, 5 s cada una y caché de 30 min por símbolo.
    - Se guardan los títulos con su fecha y, a partir de ellos, frescura, sentimiento
      simple y catalizador.
- **Salida:** puntaje 0-100, cantidad de confluencias, acción (`allow` / `paper_only`),
  motivos y si el gate de verdad actuó (`enforced`; solo con `QUALITY_GATE_ENFORCE`, fuera
  del agente).

## Reglas del gate QG1 (congeladas)

Son los puntos del paquete, con el mapeo de la revisión del 12-oct:

| Componente | Suma | Resta |
|---|---|---|
| Confianza ≥ mínimo + 5 **o** score ≥ umbral + 5 | +15 y +1 confluencia | −20 si confianza < mínimo − 10 **y** score < umbral − 10 |
| Tendencia D1 a favor de la dirección | +12 y +1 | −18 si va en contra (`flat` o sin dato: 0) |
| Noticia con catalizador y frescura ≥ 60 | +10 y +1 | −12 si el sentimiento es ≤ −0.4 en una compra |
| Stop entre 0.5 y 2.2 ATR | +8 y +1 | −15 si es < 0.3 o > 3.5 ATR |
| Calendario limpio | +8 y +1 | −25 con un evento cerca (sin dato: 0) |

- Se arranca en 50 y se acota a 0-100.
- Puntaje < 35 o 0 confluencias → `paper_only` con motivo `quality_too_low`. El paquete lo
  llamaba "discard".
- Menos confluencias que `QUALITY_MIN_CONFLUENCE` o puntaje < 55 → `paper_only`.
- Si no, `allow`.
- **Nunca descarta.** El paper trade se abre siempre y el agente ve el candidato siempre.

Cambios respecto del paquete, declarados:

- Las claves se leen de los datos reales del bot. La tendencia `range` del paquete es
  `flat`, y `risk_r` pasa a ser la distancia al stop en ATR, porque el stop ya es 1R.
- "discard" pasa a ser `paper_only`.
- Las noticias son solo de acciones y solo lo publicado antes de la apertura.
- Del sentimiento se sacan palabras ambiguas: cut, cuts, lower, higher y baja (una "baja
  de tasas" no es una mala noticia).

Cualquier cambio en estas reglas crea otra versión (`gate_version`), y las filas de
versiones distintas no se mezclan.

## Sesgos conocidos, declarados de antemano

- Los titulares de Yahoo salen del caché del bot, que puede tener hasta 20 min. Puede
  faltar alguno muy reciente, pero nunca entra uno del futuro.
- Google News devuelve los ~100 ítems más relevantes del último día. Los que no traen
  fecha se descartan, porque no se puede verificar que sean anteriores.
- El sentimiento por palabras es pobre. Por eso se guardan los títulos: un pre-registro
  futuro puede definir otro método sobre los mismos títulos.
- Con el bot apagado o congelado no hay filas, y no se rellenan.
- En acciones no hay tendencia D1: solo forex y oro leen MT5.
- Los umbrales salen del `.env` del user; por eso se guardan en cada fila.

## Regla de no mirar (para no contaminar la prueba)

- Nadie (ni Claude ni el user) cruza el resultado de los trades (R, acierto, expectativa)
  con la acción, el puntaje, las confluencias o las noticias del gate antes del
  pre-registro.
- `/filtro` solo cuenta filas, acciones y estados de las noticias. Nunca muestra
  resultados.
- Los R de los paper trades se siguen viendo en otros reportes (`/expectancy`,
  `/performance`). Eso está bien: lo prohibido es cruzarlos con el veredicto del gate.
- Chequeos de salud permitidos: cantidad de filas, estados y campos con dato.

## Cuándo se podrá pre-registrar

- **No antes del 2027-01-11** (la fecha del agente), y con **≥ 300 filas con R cerrado**
  (sin artifacts ni oro mezclado), de las cuales **≥ 100 de forex u oro**.
- El pre-registro fija, antes de mirar:
  - la hipótesis (por ejemplo, "el R de `allow` supera al de `paper_only`");
  - el universo (forex/oro y acciones, juntos o por separado);
  - el k y el umbral t de Newey-West ≥ 2.50;
  - los costos y la ventana;
  - qué habilita un PASA. Como mucho, proponer `QUALITY_GATE_ENFORCE` fuera del agente,
    o una adenda para el agente. Nada automático.
- Si al 2027-04-12 no llegó al mínimo, se evalúa con lo que haya y se declara baja
  potencia.
- Si se pre-registra, entra al ledger como familia 29 (o el número que siga).

## Lo que NO hace

- **No toca al agente:** ni su etiqueta, ni sus candidatos, ni lo que ve. En forex y oro
  la anotación se hace después de que el agente decide, y el gate nunca saca candidatos.
- `QUALITY_GATE_ENFORCE` (apagado) solo actúa en el camino a MT5 que **no** es del agente.
  Con el agente encendido no cambia ninguna orden, y nunca toca el paper trade, así que
  la medición no cambia.
- No sube umbrales ni cambia la selectividad del `.env`: el 12-oct el user decidió "no por
  ahora".
