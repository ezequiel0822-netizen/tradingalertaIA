"""v3.13.0 — regresión lineal bayesiana con Thompson sampling (numpy, sin I/O).

Modelo:  R = x·θ + ruido,  θ ~ N(0, prior_var·I),  ruido ~ N(0, noise_var).
Posterior conjugado:  A = I/prior_var + Σ x xᵀ / noise_var,  b = Σ x·R / noise_var,
μ = A⁻¹ b,  Σ = A⁻¹.

Decisión (Thompson): se muestrea el puntaje del candidato de su posterior,
score ~ N(x·μ, xᵀ Σ x), y se ejecuta si score > umbral. Con poca experiencia el desvío
es grande y el agente "prueba"; a medida que aprende, explora solo donde todavía no
sabe. Es la forma estándar y honesta de aprender practicando.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field

import numpy as np

R_CLIP = (-3.0, 5.0)        # una mecha o un gap no pueden dominar el aprendizaje


@dataclass
class LinearThompson:
    feature_names: tuple[str, ...]
    prior_var: float = 0.25
    noise_var: float = 1.0
    A: np.ndarray = field(default=None)  # type: ignore[assignment]
    b: np.ndarray = field(default=None)  # type: ignore[assignment]
    n: int = 0
    # v3.14.1 — datos sobre cómo se armó el modelo (p. ej. `excludes_mixed_gold`:
    # reconstruido sin el oro de precio mezclado, adenda 2026-10-07). Viaja con el
    # estado y sobrevive a las actualizaciones; no toca las cuentas.
    meta: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        d = len(self.feature_names)
        if self.A is None:
            self.A = np.eye(d) / float(self.prior_var)
        if self.b is None:
            self.b = np.zeros(d)

    @property
    def dim(self) -> int:
        return len(self.feature_names)

    # ---------------------------------------------------------------- aprendizaje
    def update(self, x, reward: float) -> float:
        """Agrega una observación. Devuelve la recompensa efectivamente usada (clip)."""
        v = np.asarray(x, dtype=float)
        r = float(min(max(float(reward), R_CLIP[0]), R_CLIP[1]))
        self.A = self.A + np.outer(v, v) / self.noise_var
        self.b = self.b + v * r / self.noise_var
        self.n += 1
        return r

    def mean(self) -> np.ndarray:
        return np.linalg.solve(self.A, self.b)

    def predict(self, x) -> tuple[float, float]:
        """(media, desvío) del puntaje esperado del candidato, en R."""
        v = np.asarray(x, dtype=float)
        mu = float(v @ self.mean())
        var = float(v @ np.linalg.solve(self.A, v))
        return mu, math.sqrt(max(var, 0.0))

    def sample_score(self, x, rng: np.random.Generator) -> tuple[float, float, float]:
        """(media, desvío, puntaje muestreado) — Thompson sampling sobre el posterior."""
        mu, sd = self.predict(x)
        return mu, sd, float(mu + sd * rng.standard_normal())

    # ----------------------------------------------------------------- persistencia
    def to_json(self) -> str:
        return json.dumps({
            "version": 1,
            "feature_names": list(self.feature_names),
            "prior_var": self.prior_var,
            "noise_var": self.noise_var,
            "A": self.A.tolist(),
            "b": self.b.tolist(),
            "n": self.n,
            "meta": dict(self.meta or {}),
        })

    @classmethod
    def from_json(cls, text: str | None, feature_names: tuple[str, ...],
                  prior_var: float, noise_var: float) -> "LinearThompson":
        """Carga el modelo guardado; si no hay, o cambió el set de features o la
        configuración del prior/ruido, arranca uno nuevo (no mezcla modelos)."""
        fresh = cls(feature_names=tuple(feature_names), prior_var=prior_var, noise_var=noise_var)
        if not text:
            return fresh
        try:
            d = json.loads(text)
            if (tuple(d.get("feature_names") or ()) != tuple(feature_names)
                    or float(d.get("prior_var")) != float(prior_var)
                    or float(d.get("noise_var")) != float(noise_var)):
                return fresh
            A = np.asarray(d["A"], dtype=float)
            b = np.asarray(d["b"], dtype=float)
            k = len(feature_names)
            if A.shape != (k, k) or b.shape != (k,):
                return fresh
            meta = d.get("meta")
            return cls(feature_names=tuple(feature_names), prior_var=prior_var,
                       noise_var=noise_var, A=A, b=b, n=int(d.get("n") or 0),
                       meta=dict(meta) if isinstance(meta, dict) else {})
        except (ValueError, TypeError, KeyError):
            return fresh
