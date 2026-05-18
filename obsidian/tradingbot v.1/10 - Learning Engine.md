# Learning Engine

## Objetivo

Preparar a Trading Alert AI para pensar como un sistema de trading profesional sin operar real.

## Que aprende

- que tipos de alerta terminan mejor
- que features ayudan: IA Pro, patron tecnico, noticias, filings, volumen, liquidez
- que features castigan: anti-hype, baja liquidez, riesgo critico, catalizador negativo
- que setups merecen simulacion en papel

## Tablas

- `signal_outcomes`: compara precio de alerta contra precio actual guardado
- `strategy_lessons`: resume features ganadoras o peligrosas
- `paper_trades`: setups simulados A/B
- `training_runs`: bitacora de entrenamientos

## Comandos

```text
/aprendizaje
/paper
/entrenar
```

## Regla

El aprendizaje no compra, no vende y no ejecuta ordenes. Solo prepara decisiones manuales con mejor informacion.

## Criterio de readiness

- `A`: setup fuerte para revisar manualmente
- `B`: setup interesante, necesita confirmacion
- `C`: watchlist
- `D`: bajo interes
- `BLOCKED`: no simular por riesgo o datos insuficientes

## Primer entrenamiento local

- Version: `v1.5.2`
- Señales evaluadas: 300
- Outcomes nuevos: 300
- Lecciones creadas: 43
- Paper trades nuevos: 0

Lectura: el motor ya empezo a aprender del historial. Que haya 0 paper trades nuevos significa que, con las reglas estrictas actuales, no encontro setups A/B suficientes en el historial existente para simular entrada. Eso es sano: no fuerza operaciones.
