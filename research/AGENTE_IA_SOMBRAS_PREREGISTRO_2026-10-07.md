# Pre-registro — agentes sombra del agente IA v2 (v3.15.0)

> **Commiteado ANTES del código de las sombras** y antes de que exista una sola decisión
> del tag evaluado `...|px1` (adenda `AGENTE_IA_V2_ADENDA_2026-10-07_oro.md`). Las
> sombras nunca operan: no hay orden posible. Real-money sigue bloqueado por código.

## 0. Lo que el user pidió y lo que se le dijo

Pregunta (7-oct): "¿se pueden agregar más [agentes]?". Después: "sí, ármalo cuando esté
el arreglo del oro, pero haz todo ya".

Respuesta honesta, fijada acá:

- **Más agentes operando la misma cuenta, no.** Verían los mismos ~10 candidatos por día
  y aprenderían del mismo paper, porque el agente ya aprende de TODOS los candidatos
  (información completa). Además compartirían saldo y topes y ensuciarían la evaluación
  del agente.
- **Lo que se arma: 3 políticas "sombra".** Deciden sobre los MISMOS candidatos que el
  agente v2, pero no mandan órdenes: se calculan de lo que el agente ya registra en cada
  decisión, así que no tienen camino a MT5.
- **Expectativa:** con 26 familias de hipótesis sin edge, las sombras van a diferir en
  cuánto pierden, no en si ganan.

## 1. Las sombras (k = 3), fijas desde este commit

Las tres usan lo que el agente v2 guarda en cada fila de `ai_agent_decisions`: media y
desvío de su posterior (`mean_r`, `std_r`), el ajuste de realismo ĝ que usó
(`realism_gap`) y el vector de features (`features_json`). Ninguna explora: sin órdenes,
no hay nada que explorar. Umbral: el mismo del agente, **0.05R**.

| Sombra | Modelo | Ejecuta (virtualmente) si |
|---|---|---|
| **S1 `codicioso`** | el del agente v2 (misma posterior) | `mean_r + ĝ > 0.05` (la media, sin muestreo) |
| **S2 `prudente`** | el del agente v2 | `mean_r − std_r + ĝ > 0.05` (solo con confianza de 1 desvío) |
| **S3 `simple`** | propio, con 6 features: `bias`, las 3 de estrategia, `short`, `gold` (las 6 primeras del vector v2); mismo prior 0.25, ruido 1.0 y recorte de R [−3, 5] | su media `+ ĝ > 0.05` |

**S3 aprende con información completa**, como el agente. Antes de cada decisión se
re-entrena, en orden temporal, con TODOS los paper trades forex/oro cerrados antes de la
decisión (`closed_at < created_at`). Excluye artifacts y oro mezclado. Es un control:
¿las 18 features de contexto le suman algo a "qué estrategia, qué dirección y si es oro"?

**Comparaciones que esto aísla** (descriptivas, NO deciden):

- agente vs S1 = efecto del muestreo de Thompson + la exploración;
- S1 vs S2 = efecto de exigir confianza;
- S1 vs S3 = efecto de las features de contexto.

## 2. Qué se mide

- **Unidad:** cada decisión v2 con el tag evaluado
  `v2|eps0.20|xr0.10|r0.50|thr0.05|pv0.25|nv1.00|xmax3|xstop2.0|px1`, con R del paper
  trade (`reward_r`) y sin oro mezclado. Es la misma población de la evaluación del
  agente.
- **Valor de la sombra por decisión:** `v_s = R_paper` si la sombra ejecuta, 0 si no.
  Peso 1, porque las sombras no exploran.
- **Serie diaria:** suma de `v_s` de las decisiones creadas cada día UTC.
- **Comparadores:** no operar (0) y ejecutar todo (`R_paper`).
- **Reportado aparte, NO decide:** cuántas ejecuta cada sombra, media por decisión
  ejecutada, desglose por estrategia y las tres comparaciones del §1.

## 3. Cuándo

Igual que el agente (pre-registro v2 §3 + adenda): en la primera fecha **desde el
2027-01-11** con **≥ 200 decisiones `px1` con R**. Si al **2027-04-12** no llegó a 200, se
evalúa con lo que haya y se declara baja potencia. No se mira la t antes de esa fecha.

## 4. Criterio (cada sombra PASA si cumple TODO)

1. media de `v_s` > 0;
2. **t de Newey-West** (5 rezagos) de la serie diaria de `v_s` **≥ 2.50**. Con k = 3
   sombras + el agente = 4 políticas, 2.50 ≈ Bonferroni bilateral 0.05/4;
3. media de `v_s` > media de "ejecutar todo";
4. `v_s` > 0 en ambas mitades (por fecha).

No hay criterio de límites: las sombras no operan.

## 5. Predicción declarada

**NO PASA ninguna.** Forma más probable:

- S2 ≈ 0, porque casi nunca tiene confianza;
- S1 ≈ la parte de explotación del agente;
- S3 ≈ 0 o negativa: con las medias por estrategia negativas, casi no ejecuta.

## 6. Qué habilita cada resultado

- **Una sombra PASA:** no habilita órdenes. Solo justifica un pre-registro de
  confirmación (otros 3 meses, ventana nueva) antes de hablar de convertirla en un
  agente que opere en demo. Real-money sigue bloqueado.
- **NO PASA:** las sombras se cierran sin re-cortes. No se prueban otras reglas,
  umbrales o features "a ver si sí".
- **Agregar más sombras después** requiere su propio pre-registro, que sube k y el
  umbral.

## 7. Dónde vive

- `app/ai_agent/shadows.py`: funciones puras, sin órdenes, sin MT5 y sin escribir en la
  DB.
- `scripts/ai_agent_report.py`: las muestra siempre (solo lectura), y `--evaluate` las
  evalúa con este criterio desde la fecha.
- `/agente` y el resumen diario: muestran un resumen si `AI_AGENT_SHADOWS=true` (opt-in,
  solo display).

Firmado (protocolo): reglas, k, umbral, población, fechas y predicción fijos desde este
commit; el código va en el commit siguiente.
