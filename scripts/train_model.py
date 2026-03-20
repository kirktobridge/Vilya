"""
Train the probability model from a pipeline-generated CSV.

Usage:
  poetry run python scripts/train_model.py --csv data/training.csv --output models/
  poetry run python scripts/train_model.py --csv data/training.csv --model-type lightgbm
"""
import argparse
from pathlib import Path

from src.models.train import train


def main() -> None:
  parser = argparse.ArgumentParser(description="Train Kalshi weather model")
  parser.add_argument("--csv", required=True, help="Path to training CSV from pipeline")
  parser.add_argument("--output", default="models", help="Output directory for artifacts")
  parser.add_argument(
    "--model-type", default="xgboost", choices=["xgboost", "lightgbm"],
    help="Classifier backend (default: xgboost)",
  )
  args = parser.parse_args()
  train(Path(args.csv), Path(args.output), model_type=args.model_type)


if __name__ == "__main__":
  main()
