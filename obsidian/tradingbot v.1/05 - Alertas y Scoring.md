# Alertas y Scoring

## Objetivo de alertas

Mandar pocas alertas y de mejor calidad.

## Memecoins

Telegram debe ser muy selectivo:

- subida estimada minima: 500%
- confianza minima: 45
- maximo 5 por 24h
- maximo 2 por ciclo

## Bolsa

Bolsa es menos explosiva que memecoins:

- subida estimada minima: 8%
- confianza minima: 55
- maximo 5 por 24h
- maximo 2 por ciclo

## Lo que se guarda

Aunque no se mande Telegram, el sistema guarda:

- tokens detectados
- alertas
- seguridad
- score
- subida estimada
- caida estimada
- confianza

## Lectura correcta

Una alerta no significa comprar. Significa: revisar manualmente.

## IA Pro v1.5.1

La lectura profesional suma contexto antes de rankear:

- grafico: tendencia, RSI, MACD, Bollinger, ATR, soporte/resistencia
- volumen: volumen relativo y actividad reciente
- catalizadores: noticias, earnings, revenue, guidance, conferencias
- SEC: filings recientes para acciones
- riesgo: extension, volatilidad, liquidez baja, seguridad unknown o critica

Resultado:

- `pro_high_conviction`
- `pro_watchlist`
- `pro_neutral`
- `pro_risk_off`
- `pro_security_block`

Esto sube o baja el ranking, pero no ejecuta ninguna operacion.
