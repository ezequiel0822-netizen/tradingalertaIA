# Telegram Assistant

## Version

Activo desde `v1.3`; mejorado en `v1.5` con cupos/descartes y en `v1.5.1` con IA Pro.

## Tipo

IA basica basada en reglas y SQLite.

No usa OpenAI API.

## Comandos

```text
/help
/status
/cupos
/top
/top_memecoins
/top_stocks
/alertas
/descartes
/aprendizaje
/paper
/entrenar
/analiza NVDA
/noticias NVDA
/filings NVDA
/patron NVDA
/pro NVDA
/analiza 0x...
/pausar
/reanudar
/config
```

## Comportamiento

- Solo responde al chat autorizado.
- Puede explicar datos guardados.
- Puede pausar alertas automaticas.
- Puede reanudar alertas automaticas.
- No puede operar mercados.
- Puede consultar titulares/eventos publicos por simbolo.
- Puede analizar patron tecnico basico para acciones.
- Puede generar lectura IA Pro con grafico, noticias, filings, riesgos y checklist.
- Puede mostrar lo que aprendio del historial.
- Puede mostrar paper trades simulados.
- Puede ejecutar entrenamiento local manual con `/entrenar`.

## Pendientes

- Responder preguntas mas naturales.
- Mejorar explicaciones de descartes con mas contexto historico.
- Resumir semanalmente que filtros estan funcionando mejor.
- Conectar memoria automatica con aprendizajes manuales del usuario.
