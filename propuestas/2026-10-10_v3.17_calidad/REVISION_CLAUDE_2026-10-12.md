# Revisión del paquete v3.17 "calidad" — LEER ANTES DEL PROMPT (Claude, 2026-10-12)

**Qué es el paquete.** Lo preparó otra IA el 2026-10-10 sobre v3.16.0. Se guarda **tal
cual** en esta carpeta (los nombres de archivo ya no llevan el prefijo de la subida).
Hoy `main` = `origin/main` = **206f607 (v3.16.1)**, con 938 tests.

**Qué no hay que aplicar.**

- `referencia_repo_v3.16.0/` son copias del repo: `settings.py` difiere solo en la
  versión; `forex_collector.py` y `requirements.txt` son idénticos.
- `config/env_recomendado_calidad.txt` trae los secretos vacíos. NO copiarlo encima del
  `.env` real.

Esta revisión dice qué aplicar, qué adaptar y qué NO, para no romper lo que ya está
pre-registrado. **Cualquier punto de "Choques" se confirma con el user antes de tocarlo.**

## Choques con lo que ya está en marcha

1. **`AI_AGENT_EXPLORE_PCT=0.10` (en el `.env` recomendado y en el prompt): NO.**
   - Cambia el `policy_tag` del agente (`eps0.20` → `eps0.10`).
   - Con eso, ninguna decisión nueva entra en la evaluación pre-registrada: solo cuenta
     `v2|eps0.20|xr0.10|r0.50|thr0.05|pv0.25|nv1.00|xmax3|xstop2.0|px1`, desde el
     2027-01-11 con ≥ 200 decisiones.
   - Hay que mantener 0.20.
2. **Un quality gate antes del agente cambia la población evaluada.**
   - El agente v2 y las 3 sombras deciden sobre los candidatos forex/oro.
   - Un filtro nuevo que descarte candidatos antes cambia qué se evalúa, sin que cambie
     el tag.
   - Recomendado: aplicar el gate SOLO al camino que no es del agente (acciones y el
     camino normal hacia MT5). Si se quiere delante del agente, primero una adenda al
     pre-registro v2.
3. **"discard" borra el dato.**
   - Sin paper trade no se puede medir si el filtro ayudó, y el agente no aprende de
     ese candidato.
   - Recomendado: `paper_only` en lugar de `discard`.
   - Registrar la decisión del gate por candidato (como el exit shadow), para evaluarla
     después con pre-registro.
4. **Subir umbrales reduce candidatos y cambia el flujo a mitad de la evaluación.**
   - Afecta a `STRATEGY_MIN_CONFIDENCE=74`, `ALERT_SCORE_THRESHOLD=72`,
     `READINESS_MIN_SCORE=78` y `MAX_OPEN_TRADES_TOTAL=3`.
   - El pre-registro v2 midió que el tope de 5 estuvo lleno el 96 % del tiempo. Bajarlo
     a 3 deja menos decisiones para llegar a 200 en enero.
   - Opciones: declararlo en una adenda o no tocarlo hasta la evaluación.
5. **`DEMO_ALLOWED_SYMBOLS=EURUSD,XAUUSD,GBPUSD`.**
   - El agente hoy también ejecuta USDCAD, NZDUSD, etc.
   - Restringir la lista bloquea esas órdenes. La evaluación cuenta la intención, pero
     se pierde el dato real de MT5.
   - Decidirlo con el user.
6. **La meta "win rate 58-65 % / +0.10R" no tiene evidencia.**
   - Hay 27 familias probadas con pre-registro y 0 operables, incluido el reverso de las
     señales (H-FADE1) y los FVG (H-FVG1).
   - Filtrar señales con bruto ≈ 0 baja la cantidad de operaciones, no necesariamente la
     expectativa.
   - "Observar 7-14 días con /expectancy" no distingue nada con ~10 trades.
   - Cualquier afirmación de mejora se mide con pre-registro (k, t NW ≥ 2.50).

## Detalles técnicos del código propuesto

- **`new_modules/quality_gate.py` lee claves que los candidatos del bot no tienen.**
  - Las claves son `confidence`, `score`, `regime`, `risk_r` y `calendar_safe`.
  - Pegado tal cual, la confluencia queda en 0 y TODO sale "discard".
  - Hay que mapear:
    - confidence → `StrategySignal.confidence`;
    - regime → `_d1_candles_for_regime` / `_ai_agent_context`, que devuelven
      'up' / 'down' / 'flat' (no 'range');
    - calendar_safe → `_calendar_gate`;
    - `risk_r` no tiene sentido porque el stop ya ES 1R: usar la distancia al stop en
      ATR.
- **`new_modules/web_news_enhancer.py` sirve poco tal como está.**
  - Para forex/oro no sirve: Google News RSS buscaría "EURUSD=X stock OR EURUSD=X
    shares".
  - En acciones, el sentimiento por palabras sueltas es pobre: "cut" (baja de tasas)
    cuenta como negativo.
  - Hace un request por candidato dentro del ciclo, con timeout de 12-15 s, y puede
    frenar el ciclo.
  - Si se usa: solo acciones, caché por símbolo (~30 min) y nunca bloquear el ciclo.
- **`config/requirements_mejorado.txt`: NO aplicarlo tal cual.**
  - El bot no usa yfinance: solo aparece en un comentario de `mt5_reader.py`; usa HTTP
    directo a Yahoo.
  - Agrega dependencias sin pin, contra la política de pins anti supply-chain de
    `requirements.txt`.
- **`.env` recomendado con `ENABLE_OLLAMA_INTEGRATION=true` + `ENABLE_LLM_ADVISOR=true`:**
  ojo con el hardware, el LLM local tarda ~50 s por generación. Mantenerlo fuera del
  ciclo.
- **Bien encaminado en el prompt:** opt-in OFF, soft-fail, downward-only, sincronizar
  `tests/test_score._settings()` y `tests/test_alert_rules._settings()`, y versión
  **v3.17.0** (minor; hoy es v3.16.1).

## Qué SÍ tiene valor (orden sugerido)

1. **Los dos módulos como MEDICIÓN en sombra.** Opt-in, sin descartar nada: registrar
   qué diría el gate y qué noticias había por candidato. Después, pre-registro sobre esos
   datos.
2. **Refresco del cache D1 de MT5** (P2 #11). Está congelado desde el 2026-06-15; es
   infra real, porque los gates de régimen y de VWAP hacen soft-allow por eso.
3. **Log de descartes** (P2 #14): por qué se descartó cada candidato.
4. **`realized_pnl_today` con la mitad cobrada en TP1** (P1 #9). Es la decisión que el
   user tenía pendiente: el kill-switch queda algo menos sensible. Confirmar con el user.
5. **Trailing propio para forex/oro** (P2 #12). Primero medir con el exit shadow, que ya
   existe; no cambiar salidas a ciegas.

## Estado operativo al escribir esto (2026-10-12 06:51 UTC)

- **Bot APAGADO.** No hay ningún proceso de Python.
  - El 10-oct quedó ~30 h congelado: con texto seleccionado en su ventana, Windows pausa
    la consola.
  - v3.16.1 lo previene si se arranca con el `start_bot.ps1` nuevo.
  - Última actividad: snapshot del 2026-10-11 05:27 UTC.
- **Kronos (H-KRON1) APAGADO.** Se perdió la ronda del lunes 00:02 UTC (las rondas
  perdidas no se rellenan). Arrancar con `.\start_kronos.ps1`.
- **MT5 demo:** sin posiciones abiertas; saldo 2.984,80 USD. La venta EURUSD del agente
  se cerró.
- **Agente v2:** 5 decisiones con el tag `|px1` (todas del viernes 9-oct).
- **Colector de opciones:** 3 sesiones guardadas. Los valores no se miran (regla de la
  colecta).
