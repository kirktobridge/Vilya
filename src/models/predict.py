"""Load trained artifact + calibrator and return P(YES) for a feature vector."""
# Phase 3: implement full bodies
from pathlib import Path


def load_model(model_path: Path, calibrator_path: Path) -> object:
  """Load classifier + calibrator from disk."""
  raise NotImplementedError


def predict_prob(model: object, features: dict[str, float]) -> float:
  """Return calibrated P(YES) in [0, 1]."""
  raise NotImplementedError
