"""Train XGBoost / LightGBM classifiers on labeled weather market data."""
import json
import pickle
import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss

from src.models.calibrate import fit_isotonic, save_calibrator
from src.monitoring.logger import get_logger

log = get_logger(__name__)

_NON_FEATURE_COLS = {"ticker", "title", "valid_date", "yes_settlement"}
_MIN_ROWS = 20


def train(
  training_csv: Path,
  output_dir: Path,
  model_type: str = "xgboost",
  _classifier_kwargs: dict[str, Any] | None = None,
) -> None:
  """
  Train a binary classifier and calibrator. Saves:
    output_dir/model.pkl        - dict with classifier + feature_names
    output_dir/calibrator.pkl   - fitted isotonic regressor
    output_dir/metrics.json     - Brier score, ECE, accuracy
  """
  output_dir.mkdir(parents=True, exist_ok=True)

  df = pd.read_csv(training_csv)
  if len(df) < _MIN_ROWS:
    raise ValueError(f"Need at least {_MIN_ROWS} rows, got {len(df)}")

  df = _add_derived_features(df)
  feature_cols = [c for c in df.columns if c not in _NON_FEATURE_COLS]
  X = df[feature_cols].astype(float).values
  y = df["yes_settlement"].astype(int).values

  # Time-ordered split: first 80% train, last 20% val (no shuffle to avoid lookahead)
  split = int(len(df) * 0.8)
  X_train, X_val = X[:split], X[split:]
  y_train, y_val = y[:split], y[split:]

  clf = _build_classifier(model_type, _classifier_kwargs or {})
  clf.fit(X_train, y_train)

  val_probs: np.ndarray = clf.predict_proba(X_val)[:, 1]
  calibrator = fit_isotonic(val_probs, y_val)
  val_probs_cal: np.ndarray = calibrator.predict(val_probs)

  metrics = _compute_metrics(
    n_train=split,
    y_val=y_val,
    raw_probs=val_probs,
    cal_probs=val_probs_cal,
    clf=clf,
    feature_cols=feature_cols,
    model_type=model_type,
  )
  log.info(
    "train_complete",
    **{k: v for k, v in metrics.items() if isinstance(v, (int, float, str))},
  )

  with open(output_dir / "model.pkl", "wb") as f:
    pickle.dump({"classifier": clf, "feature_names": feature_cols}, f)
  save_calibrator(calibrator, output_dir / "calibrator.pkl")
  with open(output_dir / "metrics.json", "w") as f:
    json.dump(metrics, f, indent=2)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _add_derived_features(df: pd.DataFrame) -> pd.DataFrame:
  """Add threshold_f, direction, and deviation features from ticker/title."""
  df = df.copy()
  df["threshold_f"] = df["ticker"].apply(_parse_threshold_f)
  df["is_bucket_market"] = df["ticker"].astype(str).str.contains(
    r"-B\d", regex=True
  ).astype(float)

  if "title" in df.columns:
    df["is_above_threshold"] = df["title"].apply(_parse_market_direction)
  else:
    df["is_above_threshold"] = float("nan")

  for src in ("nws", "ow"):
    for lead in ("t24", "t12", "t6", "t3"):
      col = f"{src}_{lead}_forecast_high_f"
      if col not in df.columns:
        continue
      dev = df[col] - df["threshold_f"]
      df[f"{src}_{lead}_clim_dev"] = df[col] - df["clim_mean_high"]
      df[f"{src}_{lead}_threshold_dev"] = dev
      # Signed: positive = more likely YES regardless of market direction.
      # NaN for bucket markets (direction undefined).
      df[f"{src}_{lead}_threshold_dev_signed"] = np.where(
        df["is_above_threshold"].isna(),
        float("nan"),
        dev * (2 * df["is_above_threshold"].fillna(0) - 1),
      )

  return df


def _parse_threshold_f(ticker: str) -> float:
  """Extract temperature threshold from a Kalshi ticker string.

  Handles patterns like:
    KXHIGHNY-24JUN24-87    -> 87.0   (plain)
    KXHIGHNY-24JUN24-T90   -> 90.0   (T-prefix above/below)
    KXHIGHNY-24JUN24-B83.5 -> 83.5   (B-prefix bucket lower bound)
  Returns NaN if not parseable.
  """
  match = re.search(r"-[TB]?(\d+(?:\.\d+)?)$", str(ticker))
  return float(match.group(1)) if match else float("nan")


def _parse_market_direction(title: object) -> float:
  """Return 1.0 (above threshold), 0.0 (below threshold), or NaN (bucket/unknown)."""
  if not isinstance(title, str) or not title:
    return float("nan")
  if ">" in title:
    return 1.0
  if "<" in title:
    return 0.0
  return float("nan")


def _build_classifier(model_type: str, kwargs: dict[str, Any]) -> Any:
  defaults: dict[str, Any]
  if model_type == "xgboost":
    from xgboost import XGBClassifier

    defaults = dict(
      n_estimators=300,
      max_depth=4,
      learning_rate=0.05,
      subsample=0.8,
      colsample_bytree=0.8,
      eval_metric="logloss",
      random_state=42,
      n_jobs=-1,
    )
    return XGBClassifier(**{**defaults, **kwargs})

  if model_type == "lightgbm":
    from lightgbm import LGBMClassifier

    defaults = dict(
      n_estimators=300,
      max_depth=4,
      learning_rate=0.05,
      subsample=0.8,
      colsample_bytree=0.8,
      random_state=42,
      n_jobs=-1,
      verbose=-1,
    )
    return LGBMClassifier(**{**defaults, **kwargs})

  raise ValueError(f"Unknown model_type: {model_type!r}. Use 'xgboost' or 'lightgbm'.")


def _compute_metrics(
  n_train: int,
  y_val: np.ndarray,
  raw_probs: np.ndarray,
  cal_probs: np.ndarray,
  clf: Any,
  feature_cols: list[str],
  model_type: str,
) -> dict[str, Any]:
  brier_raw = float(brier_score_loss(y_val, raw_probs))
  brier_cal = float(brier_score_loss(y_val, cal_probs))
  ece = float(_expected_calibration_error(y_val, cal_probs))
  accuracy = float(np.mean((cal_probs >= 0.5) == y_val))

  importance: dict[str, float] = {}
  if hasattr(clf, "feature_importances_"):
    importance = dict(zip(feature_cols, [float(x) for x in clf.feature_importances_]))

  return {
    "model_type": model_type,
    "n_train": n_train,
    "n_val": int(len(y_val)),
    "brier_raw": brier_raw,
    "brier_calibrated": brier_cal,
    "ece": ece,
    "accuracy": accuracy,
    "feature_importance": importance,
  }


def _expected_calibration_error(y: np.ndarray, probs: np.ndarray, n_bins: int = 10) -> float:
  """Mean absolute difference between predicted confidence and empirical accuracy."""
  bins = np.linspace(0.0, 1.0, n_bins + 1)
  ece = 0.0
  for lo, hi in zip(bins[:-1], bins[1:]):
    mask = (probs >= lo) & (probs < hi)
    if mask.sum() == 0:
      continue
    ece += mask.sum() * abs(float(probs[mask].mean()) - float(y[mask].mean()))
  return ece / len(y)
