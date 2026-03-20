"""Calibration: fit isotonic regression on raw model probabilities."""
import pickle
from pathlib import Path
from typing import cast

import numpy as np
from sklearn.isotonic import IsotonicRegression


def fit_isotonic(probs: np.ndarray, labels: np.ndarray) -> IsotonicRegression:
  """Fit isotonic regression calibrator on val-set predictions."""
  cal = IsotonicRegression(out_of_bounds="clip")
  cal.fit(probs, labels)
  return cal


def save_calibrator(calibrator: IsotonicRegression, path: Path) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)
  with open(path, "wb") as f:
    pickle.dump(calibrator, f)


def load_calibrator(path: Path) -> IsotonicRegression:
  with open(path, "rb") as f:
    return cast(IsotonicRegression, pickle.load(f))
