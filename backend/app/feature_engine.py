from __future__ import annotations

import numpy as np
import pandas as pd

from .aggtrade_features import add_agg_rolling_features
from .kline_features import add_kline_features
from .model_loader import FEATURE_COLUMNS


def build_agg_row(trades: list[dict]) -> dict:
    eps = 1e-12

    if not trades:
        return {
            "agg_count": 0.0,
            "agg_total_qty": 0.0,
            "agg_total_quote": 0.0,
            "agg_avg_qty": 0.0,
            "agg_avg_quote": 0.0,
            "buyer_taker_qty": 0.0,
            "seller_taker_qty": 0.0,
            "buyer_taker_ratio": 0.0,
            "seller_taker_ratio": 0.0,
            "orderflow_imbalance": 0.0,
            "buyer_taker_count": 0.0,
            "seller_taker_count": 0.0,
            "buyer_taker_count_ratio": 0.0,
            "seller_taker_count_ratio": 0.0,
            "agg_vwap": 0.0,
            "agg_price_std": 0.0,
            "agg_price_range": 0.0,
        }

    prices = np.array([t["price"] for t in trades], dtype=float)
    qtys = np.array([t["qty"] for t in trades], dtype=float)

    buyer_mask = np.array([not t["is_buyer_maker"] for t in trades], dtype=bool)
    seller_mask = ~buyer_mask

    agg_count = len(trades)
    agg_total_qty = qtys.sum()
    agg_total_quote = (prices * qtys).sum()

    buyer_taker_qty = qtys[buyer_mask].sum()
    seller_taker_qty = qtys[seller_mask].sum()

    buyer_taker_count = float(buyer_mask.sum())
    seller_taker_count = float(seller_mask.sum())

    return {
        "agg_count": float(agg_count),
        "agg_total_qty": float(agg_total_qty),
        "agg_total_quote": float(agg_total_quote),
        "agg_avg_qty": float(agg_total_qty / (agg_count + eps)),
        "agg_avg_quote": float(agg_total_quote / (agg_count + eps)),
        "buyer_taker_qty": float(buyer_taker_qty),
        "seller_taker_qty": float(seller_taker_qty),
        "buyer_taker_ratio": float(buyer_taker_qty / (agg_total_qty + eps)),
        "seller_taker_ratio": float(seller_taker_qty / (agg_total_qty + eps)),
        "orderflow_imbalance": float((buyer_taker_qty - seller_taker_qty) / (agg_total_qty + eps)),
        "buyer_taker_count": buyer_taker_count,
        "seller_taker_count": seller_taker_count,
        "buyer_taker_count_ratio": float(buyer_taker_count / (agg_count + eps)),
        "seller_taker_count_ratio": float(seller_taker_count / (agg_count + eps)),
        "agg_vwap": float(agg_total_quote / (agg_total_qty + eps)),
        "agg_price_std": float(prices.std()),
        "agg_price_range": float(prices.max() - prices.min()),
    }


def build_feature_frame(
    kline_5m_buffer: list[dict],
    agg_features_buffer: list[dict],
) -> pd.DataFrame:
    df_k = pd.DataFrame(kline_5m_buffer).copy()
    df_a = pd.DataFrame(agg_features_buffer).copy()

    df = pd.concat([df_k.reset_index(drop=True), df_a.reset_index(drop=True)], axis=1)
    df = add_kline_features(df)
    df = add_agg_rolling_features(df)

    return df


def get_latest_feature_vector(
    kline_5m_buffer: list[dict],
    agg_features_buffer: list[dict],
):
    df = build_feature_frame(kline_5m_buffer, agg_features_buffer)
    X = df[FEATURE_COLUMNS].iloc[[-1]].copy()
    X = X.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return X, df