# Reporte Semanal Trading Alert AI

Resumen semanal automatico del aprendizaje local.
Se actualiza cada 7 dias cuando corre el monitor con `ENABLE_WEEKLY_OBSIDIAN_REPORT=true`.

Solo simulacion local. No es recomendacion financiera ni orden real.

Cada bloque incluye:

- Outcomes finales por horizonte (1h, 6h, 24h, 7d).
- Top 5 reglas por sharpe aproximado (combinaciones de features con `>= BACKTEST_MIN_SAMPLES` casos).
- Tabla de retornos medios por horizonte y categoria (memecoin/stock).

Si todavia no hay datos finales, el reporte solo dejara una nota indicando que estamos acumulando snapshots historicos.

Desde v2.6.0, cuando haya datos suficientes, el reporte debe separar resultados swing y scalping para evitar mezclar horizontes y estilos.

## 2026-05-22 - Nota manual v2.6.0

Obsidian queda sincronizado con:

- Phase 5 MT5 demo.
- Auto-confirm demo opt-in.
- `/health`.
- `/demo_close_all`.
- Scalping engine v2.6.0.
- Learning per-style: `SWING LESSONS` y `SCALPING LESSONS`.

Mientras no haya suficientes cierres de scalping, el reporte semanal puede seguir mostrando "sin datos suficientes".

## 2026-05-20 - Reporte Semanal v2.2.0

Sin datos suficientes esta semana.
Acumulando snapshots historicos para evaluar horizontes.

### Nota
- Simulacion local. No es recomendacion financiera ni orden real.
- El sistema no compra, no vende, no firma transacciones.


## 2026-05-20 - Reporte Semanal v2.2.0

Sin datos suficientes esta semana.
Acumulando snapshots historicos para evaluar horizontes.

### Nota
- Simulacion local. No es recomendacion financiera ni orden real.
- El sistema no compra, no vende, no firma transacciones.


## 2026-05-20 - Reporte Semanal v1.5.2

Sin datos suficientes esta semana.
Acumulando snapshots historicos para evaluar horizontes.

### Nota
- Simulacion local. No es recomendacion financiera ni orden real.
- El sistema no compra, no vende, no firma transacciones.


## 2026-05-27 - Reporte Semanal v2.6.4

### Resumen
- Outcomes finales 1h: 2000
- Outcomes finales 6h: 618
- Outcomes finales 1d: 236
- Outcomes finales 7d: 0

### Top 5 reglas (horizonte 24h)
1. gain_estimate:1000+ | n=7 | win 0.0% | avg 16.06% | MFE 16.88% | MAE 3.30% | sharpe 1.2011
2. ia_pro + score:80-90 | n=8 | win 0.0% | avg 8.37% | MFE 8.83% | MAE 3.17% | sharpe 0.6103
3. alert:forex_movement | n=42 | win 0.0% | avg 0.02% | MFE 0.02% | MAE -0.00% | sharpe 0.5991
4. category:forex | n=42 | win 0.0% | avg 0.02% | MFE 0.02% | MAE -0.00% | sharpe 0.5991
5. score:80-90 | n=10 | win 0.0% | avg 6.70% | MFE 7.06% | MAE 2.54% | sharpe 0.5315

### Retornos medios por horizonte y categoria
| Categoria | 1h | 6h | 24h | 7d |
|---|---|---|---|---|
| memecoin | +1334.51% | -2.22% | +1.73% | - |
| stock | +0.00% | +0.00% | +0.00% | - |

### Nota
- Simulacion local. No es recomendacion financiera ni orden real.
- El sistema no compra, no vende, no firma transacciones.


## 2026-06-04 - Reporte Semanal v2.9.1

### Resumen
- Outcomes finales 1h: 2000
- Outcomes finales 6h: 1678
- Outcomes finales 1d: 641
- Outcomes finales 7d: 0

### Top 5 reglas (horizonte 24h)
1. category:forex | n=70 | win 0.0% | avg 0.01% | MFE 0.01% | MAE -0.00% | sharpe 0.3705
2. alert:forex_movement | n=70 | win 0.0% | avg 0.01% | MFE 0.01% | MAE -0.00% | sharpe 0.3705
3. bullish_pattern | n=44 | win 0.0% | avg 0.04% | MFE 0.04% | MAE -0.00% | sharpe 0.3616
4. bullish_pattern + category:stock | n=44 | win 0.0% | avg 0.04% | MFE 0.04% | MAE -0.00% | sharpe 0.3616
5. alert:security_risk | n=21 | win 4.8% | avg 3.20% | MFE 3.22% | MAE 1.15% | sharpe 0.2892

### Retornos medios por horizonte y categoria
| Categoria | 1h | 6h | 24h | 7d |
|---|---|---|---|---|
| memecoin | +2030553.50% | +2677098.79% | +0.65% | - |
| stock | +0.00% | -0.00% | -0.00% | - |

### Nota
- Simulacion local. No es recomendacion financiera ni orden real.
- El sistema no compra, no vende, no firma transacciones.

