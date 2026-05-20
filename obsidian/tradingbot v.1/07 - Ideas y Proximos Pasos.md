# Ideas y Proximos Pasos

## Estado actual (v2.3.0)

Phase 4 cerrada. 197 tests verdes. El bot ya tiene:
- Strategy router con 5 estrategias (breakout + mean_reversion + momentum + news_catalyst + forex_session_breakout)
- Portfolio manager + risk manager + position sizer
- Lifecycle manager con MFE/MAE/trailing/time exit/partial close
- **MT5 reader extendido**: symbol_info, validate_symbol, pip_value real, historical_range. Cuenta demo ICMarkets disponible.
- **Walk-forward backtester** out-of-sample (detecta curve-fitting). Persiste en walk_forward_results.
- **Data quality monitor**: gaps, staleness, collector failures. Persiste en data_quality_log.
- **CSV export** para outcomes/paper_trades/horizons/walk_forward.
- Comandos Telegram nuevos: `/mt5_status`, `/data_quality`, `/walk_forward`, `/export_csv`.
- Forex/oro collector con alertas Telegram activadas (caps separados)
- Macro context completo: sesiones FX + regime (VIX/DXY/SPY) + calendario economico (ForexFactory)
- Multi-timeframe analysis (M15 + H1) con confluence score
- Learning engine con horizons + backtester + learned weights + learning gate
- Claude API integration (Haiku 4.5) soft-fail para razonamiento sobre noticias + preguntas naturales en Telegram
- Security hardening (settings repr mascarado, safe_path, log redactor, safe_json, deps pinneadas)
- Packages `MetaTrader5 5.0.5735` y `anthropic 0.103.1` instalados.

## Roadmap pendiente

### Phase 3 — Forex price-action + dashboard avanzado

- Modulo de analisis forex-especifico: S/R diarios, breakouts con session filter (London/NY), calendario economico (NFP/FOMC/CPI).
- Activar alertas Telegram para forex/gold cuando el modulo este listo.
- Position sizing con pip values y spreads reales de MT5.
- Heatmaps return × horizon × hour-of-day.
- Drilldown per alert.
- Cohort comparison (con/sin IA Pro).
- Multi-timeframe confirmation (M5+H1+H4).
- VIX y DXY collectors para contexto macro.

### Phase 3.5 — LLM integration (Claude API)

- Integrar Anthropic Claude API en el bot.
- El bot manda noticias, contexto y catalizadores → Claude devuelve analisis razonado en texto.
- Reformula reasons de alerta con razonamiento cualitativo.
- Permite preguntas naturales en Telegram ("por que abriste NVDA?").
- Esto convierte el "AI" del nombre en AI real.
- Costo: ~$10-30 USD/mes segun uso.

### Phase 4 — MT5 demo READ-ONLY validation

- Validar conexion MT5 con cuenta demo real.
- Data quality monitor (gap detection, collector failure alerts).
- CSV export de outcomes para analisis externo.
- Walk-forward backtester sobre las 4 strategies (validacion out-of-sample).

### Phase 5 — MT5 demo ACTIVE trading (autorizado por usuario 2026-05-18)

- Primera fase donde `order_send(account_type='demo')` esta permitido.
- Kill-switch ya implementado, max drawdown daily ya implementado, position sizing ya implementado, mandatory SL en todos los trades, dry-run flag adicional.
- Real-money trading sigue prohibido hasta nueva autorizacion.

### Phase 6 — Strategy evolution (concepto del usuario 2026-05-19)

Aplicar "selección natural" a las estrategias:

- Cada strategy trade en demo durante 30+ dias.
- Fitness se calcula (Sharpe + win_rate + max drawdown).
- Estrategias con fitness bajo durante 3 periodos seguidos se desactivan.
- Estrategias con drawdown > 15% se reducen capital al 50%.
- Periodicamente se generan variantes con mutaciones de parametros (ej. `breakout_v2` con ATR multiplier distinto).
- Compiten contra las originales.

Protecciones contra overfitting:
- Min sample size 50+ trades antes de evaluar.
- Siempre 1 estrategia activa como floor (no all-or-nothing).
- Variantes con base teorica, no random.

## Mejoras de datos

- holders (cripto)
- liquidez bloqueada (cripto)
- contratos verificados (cripto)
- redes sociales
- volumen por exchanges
- eventos de noticias
- calendario economico (forex/stocks)
- VIX y DXY (macro)

## Mejoras de scoring

- Pesos aprendidos: ✅ shipped en v1.7.0
- Series historicas por pool
- Comparacion contra promedio movil
- Deteccion de wash trading
- Ajuste por market cap

## Seguridad

- Auditoria automatica de archivos: ✅ shipped en v2.1.0
- Rotacion recomendada de tokens: regla operativa, sin codigo
- Log redactor: ✅ shipped en v2.1.0
- Cifrado at-rest del SQLite: queda para futuro si lo pide el usuario

## Inteligencia avanzada

- Phase 3.5: Claude API (mas urgente)
- ML clasico (XGBoost) prediciendo win/loss: futuro, requiere 3+ meses de data
- Deep learning: NO recomendado para retail
- Reinforcement learning: NO recomendado
