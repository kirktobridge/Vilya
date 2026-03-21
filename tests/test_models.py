"""Tests for src/models: calibrate, predict, train."""
import json
import math
import pickle
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sklearn.isotonic import IsotonicRegression

from src.models.calibrate import fit_isotonic, load_calibrator, save_calibrator
from src.models.predict import ModelBundle, load_model, predict_prob
from src.models.train import _parse_market_direction, _parse_threshold_f, train


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

RNG = np.random.default_rng(42)


def _make_training_df(n: int = 30) -> pd.DataFrame:
  """Create synthetic training data that looks like the pipeline CSV output."""
  rows = []
  for i in range(n):
    threshold = 85.0 + (i % 5) * 2.0
    true_high = threshold + RNG.normal(0, 3)
    yes_settlement = int(true_high > threshold)
    rows.append({
      "ticker": f"KXHIGHNY-{i:02d}JAN24-{int(threshold)}",
      "valid_date": f"2024-01-{(i % 28) + 1:02d}",
      "yes_settlement": yes_settlement,
      # T-24
      "nws_t24_forecast_high_f": true_high + RNG.normal(0, 1.5),
      "ow_t24_forecast_high_f": true_high + RNG.normal(0, 1.5),
      "nws_t24_forecast_low_f": true_high - 15.0,
      "ow_t24_forecast_low_f": true_high - 15.0,
      "nws_t24_precip_prob": 0.1,
      "ow_t24_precip_prob": 0.1,
      "nws_t24_humidity_pct": 60.0,
      "ow_t24_humidity_pct": 60.0,
      # T-12
      "nws_t12_forecast_high_f": true_high + RNG.normal(0, 1.0),
      "ow_t12_forecast_high_f": true_high + RNG.normal(0, 1.0),
      "nws_t12_forecast_low_f": true_high - 15.0,
      "ow_t12_forecast_low_f": true_high - 15.0,
      "nws_t12_precip_prob": 0.1,
      "ow_t12_precip_prob": 0.1,
      "nws_t12_humidity_pct": 60.0,
      "ow_t12_humidity_pct": 60.0,
      # T-6
      "nws_t6_forecast_high_f": true_high + RNG.normal(0, 0.5),
      "ow_t6_forecast_high_f": true_high + RNG.normal(0, 0.5),
      "nws_t6_forecast_low_f": true_high - 15.0,
      "ow_t6_forecast_low_f": true_high - 15.0,
      "nws_t6_precip_prob": 0.1,
      "ow_t6_precip_prob": 0.1,
      "nws_t6_humidity_pct": 60.0,
      "ow_t6_humidity_pct": 60.0,
      # T-3
      "nws_t3_forecast_high_f": true_high + RNG.normal(0, 0.2),
      "ow_t3_forecast_high_f": true_high + RNG.normal(0, 0.2),
      "nws_t3_forecast_low_f": true_high - 15.0,
      "ow_t3_forecast_low_f": true_high - 15.0,
      "nws_t3_precip_prob": 0.1,
      "ow_t3_precip_prob": 0.1,
      "nws_t3_humidity_pct": 60.0,
      "ow_t3_humidity_pct": 60.0,
      # Seasonal / climatology
      "day_of_year": float(i + 1),
      "month": 1.0,
      "clim_mean_high": 39.0,
      "clim_std_high": 8.0,
    })
  return pd.DataFrame(rows)


def _write_csv(df: pd.DataFrame, path: Path) -> Path:
  csv_path = path / "training.csv"
  df.to_csv(csv_path, index=False)
  return csv_path


# ---------------------------------------------------------------------------
# calibrate
# ---------------------------------------------------------------------------

class TestFitIsotonic:
  def test_returns_isotonic_regression(self) -> None:
    probs = np.array([0.1, 0.3, 0.5, 0.7, 0.9])
    labels = np.array([0, 0, 1, 1, 1])
    cal = fit_isotonic(probs, labels)
    assert isinstance(cal, IsotonicRegression)

  def test_output_is_monotone(self) -> None:
    probs = np.linspace(0, 1, 20)
    labels = (probs > 0.5).astype(float)
    cal = fit_isotonic(probs, labels)
    transformed = cal.predict(probs)
    assert np.all(np.diff(transformed) >= 0)

  def test_clips_below_zero(self) -> None:
    probs = np.array([0.0, 0.5, 1.0])
    labels = np.array([0, 1, 1])
    cal = fit_isotonic(probs, labels)
    result = cal.predict(np.array([-0.5]))
    assert result[0] >= 0.0

  def test_clips_above_one(self) -> None:
    probs = np.array([0.0, 0.5, 1.0])
    labels = np.array([0, 1, 1])
    cal = fit_isotonic(probs, labels)
    result = cal.predict(np.array([1.5]))
    assert result[0] <= 1.0


class TestSaveLoadCalibrator:
  def test_roundtrip(self, tmp_path: Path) -> None:
    probs = np.array([0.1, 0.4, 0.6, 0.9])
    labels = np.array([0, 0, 1, 1])
    cal = fit_isotonic(probs, labels)
    path = tmp_path / "cal.pkl"
    save_calibrator(cal, path)
    loaded = load_calibrator(path)
    np.testing.assert_array_almost_equal(
      cal.predict(probs), loaded.predict(probs)
    )

  def test_creates_parent_dirs(self, tmp_path: Path) -> None:
    probs = np.array([0.2, 0.8])
    labels = np.array([0, 1])
    cal = fit_isotonic(probs, labels)
    path = tmp_path / "nested" / "dir" / "cal.pkl"
    save_calibrator(cal, path)
    assert path.exists()


# ---------------------------------------------------------------------------
# predict
# ---------------------------------------------------------------------------

def _make_bundle(feature_names: list[str]) -> ModelBundle:
  """Make a ModelBundle with a tiny XGBoost model trained on synthetic data."""
  from xgboost import XGBClassifier

  n = 20
  X = RNG.random((n, len(feature_names)))
  y = RNG.integers(0, 2, n)
  clf = XGBClassifier(n_estimators=5, random_state=42)
  clf.fit(X, y)

  probs_train = clf.predict_proba(X)[:, 1]
  cal = fit_isotonic(probs_train, y.astype(float))
  return ModelBundle(classifier=clf, calibrator=cal, feature_names=feature_names)


class TestPredictProb:
  def test_returns_float_in_unit_interval(self) -> None:
    bundle = _make_bundle(["feat_a", "feat_b"])
    p = predict_prob(bundle, {"feat_a": 0.5, "feat_b": 0.3})
    assert isinstance(p, float)
    assert 0.0 <= p <= 1.0

  def test_missing_feature_defaults_to_nan(self) -> None:
    bundle = _make_bundle(["feat_a", "feat_b"])
    # XGBoost treats NaN as missing — should not raise
    p = predict_prob(bundle, {"feat_a": 0.5})
    assert 0.0 <= p <= 1.0

  def test_all_features_present_vs_missing(self) -> None:
    bundle = _make_bundle(["feat_a", "feat_b"])
    p_full = predict_prob(bundle, {"feat_a": 0.9, "feat_b": 0.9})
    p_missing = predict_prob(bundle, {})
    # Just verify both return valid probabilities
    assert 0.0 <= p_full <= 1.0
    assert 0.0 <= p_missing <= 1.0


class TestLoadModel:
  def test_roundtrip(self, tmp_path: Path) -> None:
    from xgboost import XGBClassifier

    features = ["a", "b", "c"]
    clf = XGBClassifier(n_estimators=5, random_state=42)
    clf.fit(RNG.random((10, 3)), RNG.integers(0, 2, 10))

    model_path = tmp_path / "model.pkl"
    with open(model_path, "wb") as f:
      pickle.dump({"classifier": clf, "feature_names": features}, f)

    probs = np.array([0.3, 0.6])
    cal = fit_isotonic(probs, np.array([0, 1]))
    cal_path = tmp_path / "calibrator.pkl"
    save_calibrator(cal, cal_path)

    bundle = load_model(model_path, cal_path)
    assert bundle.feature_names == features
    p = predict_prob(bundle, {"a": 0.5, "b": 0.2, "c": 0.8})
    assert 0.0 <= p <= 1.0


# ---------------------------------------------------------------------------
# train — _parse_threshold_f
# ---------------------------------------------------------------------------

class TestParseThresholdF:
  def test_integer_threshold(self) -> None:
    assert _parse_threshold_f("KXHIGHNY-24JAN24-87") == pytest.approx(87.0)

  def test_decimal_threshold(self) -> None:
    assert _parse_threshold_f("KXHIGHNY-24JAN24-87.5") == pytest.approx(87.5)

  def test_no_threshold_returns_nan(self) -> None:
    assert math.isnan(_parse_threshold_f("KXHIGHNY-24JAN24"))

  def test_non_numeric_suffix_returns_nan(self) -> None:
    assert math.isnan(_parse_threshold_f("KXHIGHNY-ABCDEF"))

  def test_empty_string_returns_nan(self) -> None:
    assert math.isnan(_parse_threshold_f(""))

  def test_t_prefix_threshold(self) -> None:
    assert _parse_threshold_f("KXHIGHNY-24JUN12-T90") == pytest.approx(90.0)

  def test_t_prefix_decimal_threshold(self) -> None:
    assert _parse_threshold_f("KXHIGHNY-24JUN12-T87.5") == pytest.approx(87.5)

  def test_b_prefix_bucket_lower_bound(self) -> None:
    assert _parse_threshold_f("KXHIGHNY-24JUN12-B83.5") == pytest.approx(83.5)

  def test_b_prefix_integer(self) -> None:
    assert _parse_threshold_f("KXHIGHNY-24JUN12-B80") == pytest.approx(80.0)


# ---------------------------------------------------------------------------
# train — _parse_market_direction
# ---------------------------------------------------------------------------

class TestParseMarketDirection:
  def test_above_market_returns_one(self) -> None:
    assert _parse_market_direction("Will the high temp be >85°F on Jun 12?") == pytest.approx(1.0)

  def test_below_market_returns_zero(self) -> None:
    assert _parse_market_direction("Will the high temp be <73°F on May 31?") == pytest.approx(0.0)

  def test_bucket_market_returns_nan(self) -> None:
    assert math.isnan(_parse_market_direction("Will the high temp be 83-84°F?"))

  def test_empty_string_returns_nan(self) -> None:
    assert math.isnan(_parse_market_direction(""))

  def test_non_string_returns_nan(self) -> None:
    assert math.isnan(_parse_market_direction(None))


# ---------------------------------------------------------------------------
# train — full pipeline
# ---------------------------------------------------------------------------

class TestTrain:
  def test_creates_output_files(self, tmp_path: Path) -> None:
    csv = _write_csv(_make_training_df(30), tmp_path)
    out = tmp_path / "models"
    train(csv, out, _classifier_kwargs={"n_estimators": 5})
    assert (out / "model.pkl").exists()
    assert (out / "calibrator.pkl").exists()
    assert (out / "metrics.json").exists()

  def test_metrics_json_has_required_keys(self, tmp_path: Path) -> None:
    csv = _write_csv(_make_training_df(30), tmp_path)
    out = tmp_path / "models"
    train(csv, out, _classifier_kwargs={"n_estimators": 5})
    metrics = json.loads((out / "metrics.json").read_text())
    for key in ("model_type", "n_train", "n_val", "brier_raw", "brier_calibrated", "ece", "accuracy"):
      assert key in metrics, f"missing key: {key}"

  def test_brier_score_is_valid(self, tmp_path: Path) -> None:
    csv = _write_csv(_make_training_df(30), tmp_path)
    out = tmp_path / "models"
    train(csv, out, _classifier_kwargs={"n_estimators": 5})
    metrics = json.loads((out / "metrics.json").read_text())
    assert 0.0 <= metrics["brier_calibrated"] <= 1.0

  def test_accuracy_is_valid(self, tmp_path: Path) -> None:
    csv = _write_csv(_make_training_df(30), tmp_path)
    out = tmp_path / "models"
    train(csv, out, _classifier_kwargs={"n_estimators": 5})
    metrics = json.loads((out / "metrics.json").read_text())
    assert 0.0 <= metrics["accuracy"] <= 1.0

  def test_model_type_recorded(self, tmp_path: Path) -> None:
    csv = _write_csv(_make_training_df(30), tmp_path)
    out = tmp_path / "models"
    train(csv, out, model_type="xgboost", _classifier_kwargs={"n_estimators": 5})
    metrics = json.loads((out / "metrics.json").read_text())
    assert metrics["model_type"] == "xgboost"

  def test_lightgbm_model_type(self, tmp_path: Path) -> None:
    csv = _write_csv(_make_training_df(30), tmp_path)
    out = tmp_path / "models"
    train(csv, out, model_type="lightgbm", _classifier_kwargs={"n_estimators": 5})
    metrics = json.loads((out / "metrics.json").read_text())
    assert metrics["model_type"] == "lightgbm"

  def test_raises_on_too_few_rows(self, tmp_path: Path) -> None:
    csv = _write_csv(_make_training_df(5), tmp_path)
    with pytest.raises(ValueError, match="at least 20 rows"):
      train(csv, tmp_path / "models", _classifier_kwargs={"n_estimators": 5})

  def test_raises_on_unknown_model_type(self, tmp_path: Path) -> None:
    csv = _write_csv(_make_training_df(30), tmp_path)
    with pytest.raises(ValueError, match="Unknown model_type"):
      train(csv, tmp_path / "models", model_type="catboost")

  def test_model_pkl_is_loadable(self, tmp_path: Path) -> None:
    csv = _write_csv(_make_training_df(30), tmp_path)
    out = tmp_path / "models"
    train(csv, out, _classifier_kwargs={"n_estimators": 5})
    bundle = load_model(out / "model.pkl", out / "calibrator.pkl")
    assert len(bundle.feature_names) > 0

  def test_predict_prob_after_train(self, tmp_path: Path) -> None:
    df = _make_training_df(30)
    csv = _write_csv(df, tmp_path)
    out = tmp_path / "models"
    train(csv, out, _classifier_kwargs={"n_estimators": 5})
    bundle = load_model(out / "model.pkl", out / "calibrator.pkl")
    features = {col: df[col].iloc[0] for col in df.columns if col not in ("ticker", "valid_date", "yes_settlement")}
    p = predict_prob(bundle, features)
    assert 0.0 <= p <= 1.0

  def test_n_train_plus_n_val_equals_total(self, tmp_path: Path) -> None:
    n = 30
    csv = _write_csv(_make_training_df(n), tmp_path)
    out = tmp_path / "models"
    train(csv, out, _classifier_kwargs={"n_estimators": 5})
    metrics = json.loads((out / "metrics.json").read_text())
    assert metrics["n_train"] + metrics["n_val"] == n

  def test_feature_importance_present_for_xgboost(self, tmp_path: Path) -> None:
    csv = _write_csv(_make_training_df(30), tmp_path)
    out = tmp_path / "models"
    train(csv, out, _classifier_kwargs={"n_estimators": 5})
    metrics = json.loads((out / "metrics.json").read_text())
    assert isinstance(metrics["feature_importance"], dict)
    assert len(metrics["feature_importance"]) > 0

  def test_threshold_f_feature_added(self, tmp_path: Path) -> None:
    csv = _write_csv(_make_training_df(30), tmp_path)
    out = tmp_path / "models"
    train(csv, out, _classifier_kwargs={"n_estimators": 5})
    bundle = load_model(out / "model.pkl", out / "calibrator.pkl")
    assert "threshold_f" in bundle.feature_names

  def test_threshold_dev_features_added(self, tmp_path: Path) -> None:
    csv = _write_csv(_make_training_df(30), tmp_path)
    out = tmp_path / "models"
    train(csv, out, _classifier_kwargs={"n_estimators": 5})
    bundle = load_model(out / "model.pkl", out / "calibrator.pkl")
    assert any("threshold_dev" in f for f in bundle.feature_names)

  def test_is_bucket_market_feature_added(self, tmp_path: Path) -> None:
    csv = _write_csv(_make_training_df(30), tmp_path)
    out = tmp_path / "models"
    train(csv, out, _classifier_kwargs={"n_estimators": 5})
    bundle = load_model(out / "model.pkl", out / "calibrator.pkl")
    assert "is_bucket_market" in bundle.feature_names

  def test_is_above_threshold_feature_added(self, tmp_path: Path) -> None:
    csv = _write_csv(_make_training_df(30), tmp_path)
    out = tmp_path / "models"
    train(csv, out, _classifier_kwargs={"n_estimators": 5})
    bundle = load_model(out / "model.pkl", out / "calibrator.pkl")
    assert "is_above_threshold" in bundle.feature_names

  def test_threshold_dev_signed_added_when_title_present(self, tmp_path: Path) -> None:
    df = _make_training_df(30)
    df["title"] = "Will the high temp be >85°F?"
    csv = _write_csv(df, tmp_path)
    out = tmp_path / "models"
    train(csv, out, _classifier_kwargs={"n_estimators": 5})
    bundle = load_model(out / "model.pkl", out / "calibrator.pkl")
    assert any("threshold_dev_signed" in f for f in bundle.feature_names)
