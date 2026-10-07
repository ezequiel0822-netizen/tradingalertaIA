# Colecta de options flow (v3.16.0) — qué se guarda y cuándo se podrá probar

> **Esto NO es un pre-registro.** Es la regla de juego de los datos, fijada ANTES de que
> exista el primer día guardado. El pre-registro de cualquier hipótesis con estos datos
> va aparte, y recién cuando haya historia suficiente.

## Por qué así

El user preguntó (7-oct) si se podía agregar "options flow". El flujo real de opciones
(barridas, órdenes grandes, OPRA) es de pago. Lo gratis (Yahoo) es una foto de la cadena
**sin historia**, así que hoy no hay con qué probar nada. Lo honesto es guardar la foto
todos los días desde ahora y evaluarla más adelante, como se hizo con el COT.

Advertencias, también fijadas desde ahora:

- La literatura que encuentra poder predictivo en el volumen de opciones se apoya sobre
  todo en datos firmados que el público no ve (quién abre y quién cierra), y el efecto se
  debilitó después de publicarse.
- El bot opera forex y oro en MT5; las opciones son sobre todo de acciones de EE.UU. (en
  el bot, solo paper) y de algunos ETF (GLD, UUP, FXE, TLT).
- Probabilidad previa de encontrar algo operable: baja.

## Qué se guarda

- **Fuente:** Yahoo Finance, endpoint v7 de opciones (cookie A3 + crumb, como el sitio).
  Solo lectura.
- **Símbolos:** `OPTIONS_COLLECTOR_SYMBOLS` (por defecto SPY, QQQ, IWM, GLD, SLV, TLT, UUP,
  FXE) + las acciones del bot (`STOCK_SYMBOLS`). Hoy son 26.
- **Cuándo:** días hábiles, desde las 22:00 UTC hasta las 08:00 UTC del día siguiente.
  Unos pocos símbolos por ciclo. La fecha de la sesión sale de la cotización, así que un
  feriado no se guarda.
- **Vencimientos:** hasta 6, dentro de 60 días.
- **Resumen por (sesión, símbolo)** en `options_snapshots`:
  - volumen y OI de calls y de puts;
  - prima negociada (volumen × último precio × 100);
  - actividad "inusual": contratos con volumen ≥ 100 y mayor que su OI, cantidad y prima;
  - IV ATM y skew (IV del put 95 % − IV del call 105 %) del primer vencimiento con ≥ 7
    días. Si el strike justo no tiene IV válida, se usa el vecino con dato dentro del ±3 %.
- **Cadena compacta** (strike, último, bid, ask, volumen, OI, IV, última operación,
  ITM) en `<carpeta de la DB>/options_raw/<sesión>/<SÍMBOLO>.json.gz`. Sirve para definir
  otras medidas en el pre-registro sin perder historia. Son ~200 KB por día.

**Sesgos conocidos, declarados de antemano:**

- El OI que publica Yahoo es el del cierre ANTERIOR.
- El volumen es el de la sesión.
- Fuera de horario algunas IV vienen en ~0 y se descartan.
- El último precio puede estar viejo en contratos poco líquidos.

## Regla de no mirar (para no contaminar la ventana)

- El bot **no muestra los valores** en ningún lado: `/opciones` solo cuenta sesiones y
  símbolos.
- Nadie (ni Claude ni el user) calcula ratios, correlaciones ni gráficos con estos datos
  antes del pre-registro. Una sola mirada "para ver qué onda" vuelve la ventana IN-SAMPLE.
- Chequeos de salud permitidos: cantidad de filas, de días y de campos con dato. Nunca
  los valores.
- Las pruebas de formato del 7-oct (SPY, AAPL, UUP: estructura, tiempos y cantidad de
  campos con dato, sin valores) no cuentan como mirada.

## Cuándo se podrá pre-registrar

- **No antes de 120 sesiones guardadas** (~abril de 2027 si el colector corre todos los
  días).
- El pre-registro fija, antes de mirar:
  - la hipótesis (p. ej. "prima inusual de puts alta → retorno bajo del subyacente a 5
    días");
  - el universo, el k y el umbral t ≥ 2.50;
  - los costos y la ventana.
- Si la ventana es corta, se declara la baja potencia.
- Los días que falten (bot apagado) se reportan, no se rellenan.
