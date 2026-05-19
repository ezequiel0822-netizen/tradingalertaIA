# Telegram Assistant

## Version

Activo desde `v1.3`; mejorado iteradamente:
- `v1.5` cupos/descartes
- `v1.5.1` IA Pro
- `v1.5.2` Learning Engine
- `v1.6.0` horizons + backtest
- `v2.0.0` trader engine (portfolio, halt, strategies)
- `v2.1.0` security hardening

## Tipo

Asistente local basado en reglas + SQLite. Sin OpenAI API. Sin LLM externo.

Pendiente Phase 3.5: integrar Claude API para razonamiento sobre noticias/catalizadores.

## Comandos

```text
# Info y control basico
/help
/status
/cupos
/config

# Tokens y alertas
/top
/top_memecoins
/top_stocks
/alertas
/descartes
/analiza NVDA
/analiza 0x...

# Inteligencia
/noticias NVDA
/filings NVDA
/patron NVDA
/pro NVDA

# Aprendizaje
/aprendizaje
/paper
/entrenar
/horizontes NVDA
/backtest [24h] [features...]

# Trader engine (v2.0.0+)
/portfolio
/posiciones
/halt [horas]
/resume_trading
/strategies

# Pausa global
/pausar
/reanudar
```

## Comportamiento

- Solo responde al chat autorizado (`TELEGRAM_CHAT_ID`).
- Puede explicar datos guardados.
- Puede pausar/reanudar alertas automaticas.
- Puede activar/liberar el kill switch del trader engine (`/halt`, `/resume_trading`).
- Puede mostrar portfolio, posiciones abiertas, estrategias activas.
- Reportes automaticos: cuando el bot abre o cierra un paper trade, manda mensaje al chat.
- NO puede operar mercados reales.

## Reportes automaticos (v2.0.0+)

Cuando `ENABLE_TRADE_ACTION_REPORTS=true`, el bot manda:

- Al abrir: "🟢 Abri long EURUSD (breakout, conf 78). Entry/SL/TPs. Size USD. Simulado."
- Al cerrar: "🔴 Cerre NVDA (stopped). P&L -1.2%. MFE +0.8%/MAE -1.5%."

## Pendientes

- Phase 3.5: integrar Claude API para preguntas naturales y analisis cualitativo.
- Resumir semanalmente que filtros funcionan mejor.
- Conectar memoria automatica con aprendizajes manuales del usuario.
