"""v2.9.0 — MLPredictor: capa XGBoost hibrida, soft-fail y degradada.

Complementa (NO reemplaza) las reglas existentes. Predice probabilidad de win de
un trade a partir de sus features al entry. Filosofia identica al promotion gate:
solo puede filtrar HACIA ABAJO, nunca habilitar lo que las reglas bloquearon.

Modo degradado / soft-fail (clave para no romper nada):
  - Si xgboost/sklearn no estan instalados            -> predict() == 0.5 (neutral)
  - Si el modelo no fue entrenado                      -> predict() == 0.5
  - Si hay < min_train_samples trades limpios          -> no entrena; predict() == 0.5
  - Cualquier excepcion en predict()                   -> 0.5 (jamas crashea)

En modo degradado el sistema se comporta EXACTAMENTE igual que antes.

XGBClassifier: max_depth=5, learning_rate=0.1, n_estimators=100, subsample=0.8,
eval_metric='auc'. Validacion temporal (train pasado / test futuro, sin look-ahead;
mismo espiritu que walk_forward.py). AUC via sklearn.metrics.roc_auc_score.
"""

from __future__ import annotations

import logging
import pickle
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

try:  # soft-fail: el sistema funciona sin estas libs (modo degradado)
    import xgboost as xgb
    from sklearn.metrics import roc_auc_score

    _ML_AVAILABLE = True
except ImportError:  # pragma: no cover - depende del entorno
    _ML_AVAILABLE = False

MODEL_VERSION = "xgboost_v1"
NEUTRAL_CONFIDENCE = 0.5

_NUMERIC_FEATURES = [
    "vix_level",
    "dxy_level",
    "time_of_day_hour",
    "day_of_week",
    "rsi_entry",
    "atr_value",
]
_CATEGORICAL_FEATURES = [
    "session",
    "strategy_name",
    "category",
    "macd_state",
    "direction",
]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _prepare_features(
    df: pd.DataFrame, feature_columns: list[str] | None = None
) -> pd.DataFrame:
    """Convierte el df crudo (columnas del ml_dataset_builder + feat_*) en una
    matriz numerica. One-hot de categoricas; numericas coercidas a float (NaN ok,
    XGBoost lo maneja nativo). Si se pasa feature_columns, realinea (predict)."""
    num_cols = [c for c in _NUMERIC_FEATURES if c in df.columns]
    num_cols += [c for c in df.columns if c.startswith("feat_")]
    cat_cols = [c for c in _CATEGORICAL_FEATURES if c in df.columns]

    parts: list[pd.DataFrame] = []
    if num_cols:
        parts.append(df[num_cols].apply(pd.to_numeric, errors="coerce"))
    if cat_cols:
        parts.append(pd.get_dummies(df[cat_cols].astype(str), columns=cat_cols))

    if parts:
        x = pd.concat(parts, axis=1)
    else:
        x = pd.DataFrame(index=df.index)

    if feature_columns is not None:
        x = x.reindex(columns=feature_columns, fill_value=0)
    return x


class MLPredictor:
    """Predictor XGBoost hibrido. Construye, persiste y consulta el modelo, todo
    con soft-fail. Una instancia carga el modelo persistido (si existe) al init."""

    def __init__(
        self,
        model_path: str | Path = "models/xgboost_v1.pkl",
        min_train_samples: int = 100,
    ) -> None:
        self.model_path = Path(model_path)
        self.min_train_samples = int(min_train_samples)
        self._model: Any = None
        self._feature_columns: list[str] = []
        self._status: dict[str, Any] = {
            "trained": False,
            "samples": 0,
            "auc": None,
            "trained_at": None,
            "version": MODEL_VERSION,
        }
        self.load_model()

    # ------------------------------------------------------------------ #
    # Entrenamiento
    # ------------------------------------------------------------------ #
    def _fit(self, df: pd.DataFrame) -> dict[str, Any] | None:
        """Entrena un modelo NUEVO sin tocar el estado de la instancia. Devuelve
        un dict {model, feature_columns, auc, samples, trained_at} o None si no se
        puede (libs ausentes, muestra insuficiente, target de una sola clase)."""
        if not _ML_AVAILABLE:
            return None
        if df is None or len(df) < self.min_train_samples:
            return None
        if "win_loss" not in df.columns:
            return None

        work = df.reset_index(drop=True)
        y = pd.to_numeric(work["win_loss"], errors="coerce").fillna(0).astype(int)
        if y.nunique() < 2:
            return None  # una sola clase -> no se puede aprender ni medir AUC

        x = _prepare_features(work)
        feature_columns = list(x.columns)

        # split temporal: train = pasado (80%), test = futuro (20%). Sin look-ahead.
        n = len(work)
        cut = max(1, int(n * 0.8))
        x_train, x_test = x.iloc[:cut], x.iloc[cut:]
        y_train, y_test = y.iloc[:cut], y.iloc[cut:]

        model = xgb.XGBClassifier(
            max_depth=5,
            learning_rate=0.1,
            n_estimators=100,
            subsample=0.8,
            eval_metric="auc",
            random_state=42,
        )
        try:
            model.fit(x_train, y_train)
        except Exception:
            logger.exception("MLPredictor: fit fallo")
            return None

        auc: float | None = None
        try:
            if len(x_test) >= 2 and y_test.nunique() == 2:
                proba = model.predict_proba(x_test)[:, 1]
                auc = float(roc_auc_score(y_test, proba))
        except Exception:
            logger.exception("MLPredictor: calculo de AUC fallo")
            auc = None

        return {
            "model": model,
            "feature_columns": feature_columns,
            "auc": auc,
            "samples": int(n),
            "trained_at": _utc_now_iso(),
        }

    def train(self, df: pd.DataFrame) -> dict[str, Any]:
        """Entrena y adopta el modelo. Si no hay muestra suficiente / libs, queda
        en modo degradado (trained=False) y predict() devuelve 0.5. Devuelve status."""
        fitted = self._fit(df)
        if fitted is None:
            # modo degradado: registra cuantas muestras habia pero no adopta modelo
            self._model = None
            self._feature_columns = []
            self._status = {
                "trained": False,
                "samples": int(len(df)) if df is not None else 0,
                "auc": None,
                "trained_at": None,
                "version": MODEL_VERSION,
            }
            return self.get_status()

        self._adopt(fitted)
        self.save_model()
        return self.get_status()

    def _adopt(self, fitted: dict[str, Any]) -> None:
        self._model = fitted["model"]
        self._feature_columns = fitted["feature_columns"]
        self._status = {
            "trained": True,
            "samples": fitted["samples"],
            "auc": fitted["auc"],
            "trained_at": fitted["trained_at"],
            "version": MODEL_VERSION,
        }

    def retrain_if_needed(
        self, df: pd.DataFrame, min_new_trades: int = 20
    ) -> dict[str, Any]:
        """Reentrena solo si hay >= min_new_trades muestras nuevas desde el ultimo
        entrenamiento. Si el AUC nuevo cae > 0.05 vs el anterior, MANTIENE el modelo
        anterior (revert) y loguea warning. Devuelve un resumen del intento."""
        result = {"retrained": False, "reason": "", "auc_old": self._status.get("auc"),
                  "auc_new": None, "reverted": False}
        if df is None:
            result["reason"] = "sin dataset"
            return result
        new_count = len(df) - int(self._status.get("samples") or 0)
        if self._status.get("trained") and new_count < min_new_trades:
            result["reason"] = f"solo {new_count} trades nuevos (<{min_new_trades})"
            return result

        fitted = self._fit(df)
        if fitted is None:
            result["reason"] = "muestra insuficiente o libs ausentes (modo degradado)"
            return result

        auc_old = self._status.get("auc")
        auc_new = fitted["auc"]
        result["auc_new"] = auc_new
        if (
            auc_old is not None
            and auc_new is not None
            and auc_new < auc_old - 0.05
        ):
            logger.warning(
                "MLPredictor: AUC bajo de %.3f a %.3f (>0.05); mantengo modelo anterior",
                auc_old,
                auc_new,
            )
            result["reverted"] = True
            result["reason"] = "AUC degrado; modelo anterior conservado"
            return result

        self._adopt(fitted)
        self.save_model()
        result["retrained"] = True
        result["reason"] = "ok"
        logger.info(
            "MLPredictor: reentrenado samples=%s AUC %s -> %s",
            fitted["samples"], auc_old, auc_new,
        )
        return result

    # ------------------------------------------------------------------ #
    # Prediccion
    # ------------------------------------------------------------------ #
    def predict(self, features_dict: dict[str, Any]) -> float:
        """Probabilidad de win [0,1]. Soft-fail total: 0.5 si no entrenado, libs
        ausentes, o cualquier error. NUNCA crashea."""
        if not _ML_AVAILABLE or not self._status.get("trained") or self._model is None:
            return NEUTRAL_CONFIDENCE
        try:
            row = pd.DataFrame([features_dict])
            x = _prepare_features(row, self._feature_columns)
            proba = self._model.predict_proba(x)[:, 1][0]
            return float(min(1.0, max(0.0, proba)))
        except Exception:
            logger.exception("MLPredictor.predict fallo; devuelvo neutral 0.5")
            return NEUTRAL_CONFIDENCE

    def feature_importance(self, top: int = 5) -> list[tuple[str, float]]:
        """Top-N features mas influyentes (lista vacia si no entrenado)."""
        if not self._status.get("trained") or self._model is None:
            return []
        try:
            importances = self._model.feature_importances_
            pairs = list(zip(self._feature_columns, (float(i) for i in importances)))
            pairs.sort(key=lambda p: p[1], reverse=True)
            return pairs[:top]
        except Exception:
            logger.exception("MLPredictor.feature_importance fallo")
            return []

    # ------------------------------------------------------------------ #
    # Persistencia y estado
    # ------------------------------------------------------------------ #
    def save_model(self) -> bool:
        if not self._status.get("trained") or self._model is None:
            return False
        try:
            self.model_path.parent.mkdir(parents=True, exist_ok=True)
            with self.model_path.open("wb") as fh:
                pickle.dump(
                    {
                        "model": self._model,
                        "feature_columns": self._feature_columns,
                        "status": self._status,
                    },
                    fh,
                )
            return True
        except Exception:
            logger.exception("MLPredictor.save_model fallo")
            return False

    def load_model(self) -> bool:
        if not _ML_AVAILABLE or not self.model_path.exists():
            return False
        try:
            with self.model_path.open("rb") as fh:
                blob = pickle.load(fh)
            self._model = blob["model"]
            self._feature_columns = list(blob["feature_columns"])
            self._status = dict(blob["status"])
            return True
        except Exception:
            logger.exception("MLPredictor.load_model fallo; sigo en modo degradado")
            self._model = None
            return False

    def get_status(self) -> dict[str, Any]:
        degraded = not bool(self._status.get("trained")) or not _ML_AVAILABLE
        return {
            **self._status,
            "ml_available": _ML_AVAILABLE,
            "degraded": degraded,
            "n_features": len(self._feature_columns),
            "model_path": str(self.model_path),
        }


def ml_gate_decision(
    ml_confidence: float,
    conf_pass: float = 0.65,
    conf_low: float = 0.50,
) -> tuple[bool, bool, str]:
    """Modula la decision del promotion gate con la señal ML.

    SOLO debe invocarse cuando las reglas YA aprobaron (rules_ok=True): el ML solo
    filtra HACIA ABAJO, jamas habilita lo que las reglas bloquearon. Devuelve
    (allow, low_confidence, reason):

      - conf >= conf_pass            -> (True,  False)  pasa normal
      - conf_low <= conf < conf_pass -> (True,  True)   pasa con flag (lot a la mitad)
      - conf < conf_low              -> (False, False)  paper-only (no order_send)
    """
    c = float(ml_confidence)
    if c >= conf_pass:
        return True, False, f"ML ok (conf={c:.2f}>={conf_pass:.2f})"
    if c >= conf_low:
        return True, True, f"ML low confidence (conf={c:.2f}); lot reducido"
    return False, False, f"ML block (conf={c:.2f}<{conf_low:.2f}); paper-only"


def should_consult_ml(predictor: Any, gate_min_samples: int) -> bool:
    """True SOLO si el ML esta entrenado y con muestra suficiente para modular el
    gate. En cualquier otro caso (None, no entrenado, muestra insuficiente, libs
    ausentes, error) -> False, y el gate se comporta exactamente igual que antes.

    Esta es la salvaguarda dura del 'dormido pero listo': con n < gate_min_samples
    el ML existe y se puede inspeccionar (/ml_status) pero NO toca ninguna decision."""
    if predictor is None:
        return False
    try:
        status = predictor.get_status()
    except Exception:  # pragma: no cover - defensivo
        return False
    return bool(status.get("trained")) and int(
        status.get("samples") or 0
    ) >= int(gate_min_samples)
