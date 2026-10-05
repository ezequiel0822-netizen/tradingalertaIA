"""v3.13.0 — Agente IA en sandbox demo.

Un agente que APRENDE ONLINE (regresión bayesiana + Thompson sampling) a decidir,
para cada candidato forex/gold que generan las estrategias del bot, si EJECUTARLO en
MT5 demo o NO OPERAR. Aprende de TODOS los candidatos (también de los que no ejecuta),
porque el paper trade de cada uno se cierra igual y deja su R realizado.

Reglas (las del proyecto): opt-in OFF (`ENABLE_AI_AGENT=false`), soft-fail, solo demo
(real-money sigue HARDCODED bloqueado), `order_send` solo en
`app/brokers/mt5_demo_trader.py`, magic propio, límites duros (riesgo por trade,
posiciones abiertas, trades por día, stop diario en R) y los gates de RIESGO del bot
(calendario, exposición USD, kill-switch, halt) se mantienen. Lo que el agente
reemplaza son los filtros de EDGE (promotion/ML/LLM/régimen/VWAP): esa es su decisión.

Evaluación pre-registrada: research/AGENTE_IA_PREREGISTRO_2026-10-05.md.
"""
