"""Load trained artifact + calibrator and return P(YES) for a feature vector."""
import pickle
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import numpy as np
from sklearn.isotonic import IsotonicRegression

from src.models.calibrate import load_calibrator


@dataclass
class ModelBundle:
  classifier: Any
  calibrator: IsotonicRegression
  feature_names: list[str] = field(default_factory=list)


def load_model(model_path: Path, calibrator_path: Path) -> ModelBundle:
  """Load classifier + calibrator from disk."""
  with open(model_path, "rb") as f:
    data = cast(dict[str, Any], pickle.load(f))
  return ModelBundle(
    classifier=data["classifier"],
    calibrator=load_calibrator(calibrator_path),
    feature_names=data["feature_names"],
  )


def predict_prob(model: ModelBundle, features: dict[str, float]) -> float:
  """Return calibrated P(YES) in [0, 1]."""
  X = np.array([[features.get(f, float("nan")) for f in model.feature_names]])
  raw_prob = float(model.classifier.predict_proba(X)[0, 1])
  calibrated = float(model.calibrator.predict(np.array([raw_prob]))[0])
  return float(np.clip(calibrated, 0.0, 1.0))
