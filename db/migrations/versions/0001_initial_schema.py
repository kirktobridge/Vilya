"""Initial schema — all five tables and indexes.

Revision ID: 0001
Revises:
Create Date: 2026-03-20
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
  # -- kalshi_markets: discovered weather markets --------------------------
  op.create_table(
    "kalshi_markets",
    sa.Column("ticker", sa.Text(), primary_key=True),
    sa.Column("series_ticker", sa.Text(), nullable=False),
    sa.Column("event_ticker", sa.Text(), nullable=False),
    sa.Column("title", sa.Text(), nullable=True),
    sa.Column("open_date", sa.Date(), nullable=True),
    sa.Column("close_time", sa.DateTime(timezone=True), nullable=True),
    sa.Column("settlement_value", sa.Text(), nullable=True),
    sa.Column("yes_settlement", sa.Boolean(), nullable=True),
    sa.Column(
      "created_at",
      sa.DateTime(timezone=True),
      server_default=sa.text("now()"),
      nullable=False,
    ),
  )

  # -- kalshi_prices: intraday price snapshots ------------------------------
  op.create_table(
    "kalshi_prices",
    sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
    sa.Column("ticker", sa.Text(), sa.ForeignKey("kalshi_markets.ticker"), nullable=True),
    sa.Column("yes_price", sa.SmallInteger(), nullable=True),
    sa.Column("volume", sa.Integer(), nullable=True),
    sa.Column("snapshot_at", sa.DateTime(timezone=True), nullable=False),
  )
  op.create_index(
    "idx_kalshi_prices_ticker_time",
    "kalshi_prices",
    ["ticker", sa.text("snapshot_at DESC")],
  )

  # -- weather_forecasts: timestamped forecast snapshots -------------------
  op.create_table(
    "weather_forecasts",
    sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
    sa.Column("location", sa.Text(), nullable=False),
    sa.Column("source", sa.Text(), nullable=False),
    sa.Column("valid_date", sa.Date(), nullable=False),
    sa.Column("forecast_high_f", sa.Numeric(5, 2), nullable=True),
    sa.Column("forecast_low_f", sa.Numeric(5, 2), nullable=True),
    sa.Column("precip_prob", sa.Numeric(4, 3), nullable=True),
    sa.Column("humidity_pct", sa.SmallInteger(), nullable=True),
    sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
  )
  op.create_index(
    "idx_weather_forecasts_location_date",
    "weather_forecasts",
    ["location", sa.text("valid_date DESC")],
  )

  # -- weather_observations: actual outcomes --------------------------------
  op.create_table(
    "weather_observations",
    sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
    sa.Column("location", sa.Text(), nullable=False),
    sa.Column("obs_date", sa.Date(), nullable=False),
    sa.Column("actual_high_f", sa.Numeric(5, 2), nullable=True),
    sa.Column("actual_low_f", sa.Numeric(5, 2), nullable=True),
    sa.Column("actual_precip_in", sa.Numeric(5, 3), nullable=True),
    sa.Column("source", sa.Text(), nullable=True),
    sa.UniqueConstraint("location", "obs_date", name="uq_weather_obs_location_date"),
  )

  # -- trade_log: every signal and order decision --------------------------
  op.create_table(
    "trade_log",
    sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
    sa.Column("ticker", sa.Text(), nullable=True),
    sa.Column("decision", sa.Text(), nullable=True),
    sa.Column("model_prob", sa.Numeric(5, 4), nullable=True),
    sa.Column("market_implied", sa.Numeric(5, 4), nullable=True),
    sa.Column("edge", sa.Numeric(5, 4), nullable=True),
    sa.Column("contracts", sa.Integer(), nullable=True),
    sa.Column("order_id", sa.Text(), nullable=True),
    sa.Column("forecasts_snapshot", JSONB(), nullable=True),
    sa.Column(
      "logged_at",
      sa.DateTime(timezone=True),
      server_default=sa.text("now()"),
      nullable=False,
    ),
  )
  op.create_index(
    "idx_trade_log_ticker",
    "trade_log",
    ["ticker", sa.text("logged_at DESC")],
  )


def downgrade() -> None:
  op.drop_table("trade_log")
  op.drop_table("weather_observations")
  op.drop_table("weather_forecasts")
  op.drop_table("kalshi_prices")
  op.drop_table("kalshi_markets")
