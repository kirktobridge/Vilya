"""Calibration: isotonic regression / Platt scaling on model outputs."""
# Phase 3: implement full bodies
from pathlib import Path

import numpy as np


def fit_isotonic(probs: np.ndarray, labels: np.ndarray) -> object:
  """Fit isotonic regression calibrator on val-set predictions."""
  raise NotImplementedError


def save_calibrator(calibrator: object, path: Path) -> None:
  raise NotImplementedError


def load_calibrator(path: Path) -> object:
  raise NotImplementedError
