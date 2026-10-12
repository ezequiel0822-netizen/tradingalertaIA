# Mejoras para Trading Alert AI (v3.16.0 → propuesta v3.17)

Paquete de mejoras concretas preparado el 2026-10-10.

## Contenido

```
bot_improvements/
├── README.md                          ← este archivo
├── docs/
│   ├── PLAN_MEJORAS_v3.17.md          ← plan completo priorizado
│   └── COMO_APLICAR.md                ← pasos exactos para aplicar
├── config/
│   ├── env_recomendado_calidad.txt    ← .env optimizado para selectividad
│   └── requirements_mejorado.txt      ← dependencias más completas
├── new_modules/
│   ├── web_news_enhancer.py           ← noticias web + sentimiento simple
│   └── quality_gate.py                ← filtro de confluencia (downward-only)
└── patches/
    └── settings_additions.py          ← campos nuevos para Settings
```

## Qué mejora realmente

1. **Selectividad** – umbrales más altos + quality gate → menos trades, más calidad.
2. **Datos limpios** – fuerza `PAPER_PRICE_FROM_MT5` y warm-start del agente.
3. **Información** – noticias web frescas para filtrar mejor (especialmente acciones).
4. **Protecciones** – activa todos los gates que ya existían pero estaban OFF.
5. **Expectancy** – el objetivo deja de ser “muchas señales” y pasa a ser  
   win-rate ≥ 58-65 % con R neto positivo.

## Qué NO hace

- No desbloquea dinero real.
- No inventa edge mágico.
- No reabre las 27 hipótesis fallidas.
- No aumenta el riesgo por trade.

## Orden recomendado

1. Lee `docs/PLAN_MEJORAS_v3.17.md`
2. Sigue `docs/COMO_APLICAR.md`
3. Observa 1-2 semanas en paper/demo
4. Mide con `/expectancy`, `/edge`, `/performance`

Si después de eso el expectancy sigue negativo, el siguiente paso es  
**cambiar de vehículo de edge**, no seguir añadiendo filtros.
