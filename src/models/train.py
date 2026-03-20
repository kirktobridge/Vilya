"""Train XGBoost / LightGBM classifiers on labeled weather market data."""
# Phase 3: implement full bodies
from pathlib import Path


def train(
  training_csv: Path,
  output_dir: Path,
  model_type: str = "xgboost",
) -> None:
  """
  Train a binary classifier and calibrator. Saves:
    output_dir/model.pkl        - raw classifier artifact
    output_dir/calibrator.pkl  - fitted isotonic regressor
    output_dir/metrics.json    - Brier score, calibration error, simulated P&L
  """
  raise NotImplementedError
