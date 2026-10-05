"""v3.13.0 — arranque en caliente (OPCIONAL) del agente IA con la experiencia del bot.

Alimenta el modelo del agente con los paper trades forex/gold YA CERRADOS (sin
artifacts), como si los hubiera visto practicando. Sin esto, el agente arranca sin
experiencia y explora más (ejecuta ~la mitad de los candidatos al principio). Con
esto, arranca sabiendo lo que el bot ya midió (hoy: breakout y mean_reversion con R
negativo) y ejecuta menos.

No envía órdenes ni toca el ciclo vivo. Solo escribe el estado del modelo en
`bot_state` si se pasa --apply (sin --apply, solo muestra qué aprendería).
No lee el .env: usa la DB por ruta.

  python scripts/ai_agent_warmstart.py                 # vista previa
  python scripts/ai_agent_warmstart.py --apply         # guarda el modelo
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.ai_agent.agent import MODEL_STATE_KEY  # noqa: E402
from app.ai_agent.features import DIM, FEATURE_NAMES, build_features  # noqa: E402
from app.ai_agent.model import LinearThompson  # noqa: E402
from app.database.repository import Repository  # noqa: E402
from app.learning.trade_outcomes import is_artifact, r_multiple  # noqa: E402


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", type=Path, default=ROOT / "trading_data" / "trading_alert_ai.db")
    ap.add_argument("--prior-var", type=float, default=0.25, help="= AI_AGENT_PRIOR_VAR")
    ap.add_argument("--noise-var", type=float, default=1.0, help="= AI_AGENT_NOISE_VAR")
    ap.add_argument("--apply", action="store_true", help="guardar el modelo en bot_state")
    ap.add_argument("--force", action="store_true", help="pisar un modelo que ya aprendió")
    args = ap.parse_args()

    repo = Repository(args.db)
    current = LinearThompson.from_json(repo.get_state(MODEL_STATE_KEY), FEATURE_NAMES,
                                       args.prior_var, args.noise_var)
    if current.n and args.apply and not args.force:
        print(f"El agente ya aprendió de {current.n} trades. Usá --force para reemplazarlo.")
        return 1

    model = LinearThompson(feature_names=FEATURE_NAMES, prior_var=args.prior_var,
                           noise_var=args.noise_var)
    used = skipped = 0
    for t in sorted(repo.fetch_paper_trades(limit=100000), key=lambda r: int(r["id"])):
        if str(t.get("category") or "").lower() not in {"forex", "gold"}:
            continue
        if str(t.get("status") or "") == "open" or is_artifact(t):
            continue
        r = r_multiple(t)
        if r is None:
            skipped += 1
            continue
        model.update(build_features(t), r)   # sin régimen D1 histórico -> 0
        used += 1

    print(f"Trades forex/gold cerrados usados: {used} (sin R utilizable: {skipped})")
    print("Lo que el agente creería (R esperado, contexto neutro, long):")
    for name, idx in (("session_breakout", 1), ("mean_reversion", 2), ("momentum", 3)):
        x = [0.0] * DIM
        x[0], x[idx] = 1.0, 1.0
        mu, sd = model.predict(x)
        print(f"  {name:17} {mu:+.2f}R ± {sd:.2f}")
    if args.apply:
        repo.set_state(MODEL_STATE_KEY, model.to_json())
        print(f"Modelo guardado ({model.n} observaciones).")
    else:
        print("Vista previa: no se guardó nada (usá --apply).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
