# Cómo aplicar las mejoras (paso a paso)

## 1. Backup rápido

```powershell
cd C:\Users\LENOVO\tradingalertaIA   # o la ruta de tu repo
Copy-Item .env .env.backup_$(Get-Date -Format "yyyyMMdd_HHmm")
```

## 2. Copiar módulos nuevos

```powershell
# Desde la carpeta bot_improvements que te entregué:
Copy-Item new_modules\web_news_enhancer.py app\collectors\web_news_enhancer.py
Copy-Item new_modules\quality_gate.py app\risk\quality_gate.py
```

(Si las carpetas `collectors` o `risk` no existen exactamente así, ajústalas.  
El quality_gate también puede vivir en `app/analyzers/` o `app/strategies/`.)

## 3. Extender settings.py

Abre `app/config/settings.py` y:

1. Añade los 4 campos nuevos al `@dataclass Settings` (ver `patches/settings_additions.py`).
2. En `load_settings()` lee los 4 valores del env y pásalos al constructor.
3. Sincroniza los helpers de tests (`tests/test_score.py`, `tests/test_alert_rules.py`).

## 4. Integrar en el flujo de decisión (mínimo viable)

Lugar típico: donde se decide si un candidato va a paper o a MT5 demo  
(por ejemplo en el strategy router, decision engine o lifecycle).

Ejemplo mínimo:

```python
# Después de tener el candidato y el contexto de régimen/calendario
from app.collectors.web_news_enhancer import WebNewsEnhancer
from app.risk.quality_gate import QualityGate

news_enhancer = WebNewsEnhancer(settings)
quality_gate = QualityGate(settings)

news_extra = news_enhancer.enrich(symbol, existing_news=candidate.get("news"))
context = {
    "regime": candidate.get("regime"),
    "calendar_safe": candidate.get("calendar_safe"),
    "news": news_extra.to_dict(),
}
qd = quality_gate.evaluate(candidate, context)

if qd.action == "discard":
    # no paper, no alerta
    ...
elif qd.action == "paper_only":
    # forzar paper, no MT5
    candidate["force_paper"] = True
# si "allow" → sigue el flujo normal
```

## 5. Actualizar .env

Copia las líneas de `config/env_recomendado_calidad.txt` a tu `.env` real  
(especialmente las de selectividad, gates y los dos flags nuevos).

## 6. Requirements (opcional pero recomendado)

```powershell
pip install -r config/requirements_mejorado.txt
# o fusiona a mano con tu requirements.txt actual
```

## 7. Warm-start del agente (si usas AI agent)

Con el bot **apagado**:

```powershell
python scripts/ai_agent_warmstart.py --version 2 --mt5-d1 --exclude-mixed-gold --apply --force
```

## 8. Arrancar

```powershell
.\start_bot.ps1
```

Verifica con Telegram:

- `/health` → versión
- `/status` / `/cupos`
- `/agente` → tag `|px1` y “modelo sin oro mezclado: sí”
- `/expectancy` y `/edge` después de unos días

## 9. Observar 7-14 días

No cambies más parámetros.  
Mide:

- ¿Bajó el número de trades?
- ¿Subió el win rate paper?
- ¿El expectancy se movió hacia positivo?

Si después de 2 semanas el expectancy sigue ≤ 0, el siguiente paso no es más código,  
sino **aceptar que este vehículo necesita otra familia de hipótesis** (con pre-registro).

---

## Checklist rápido

- [ ] Backup de `.env`
- [ ] Módulos copiados
- [ ] Settings extendido + tests helpers
- [ ] Integración mínima en el decision path
- [ ] `.env` con valores de calidad
- [ ] `PAPER_PRICE_FROM_MT5=true`
- [ ] Warm-start agente (si aplica)
- [ ] Bot reiniciado
- [ ] `/agente` muestra configuración limpia
