import pandas as pd


def add_agg_rolling_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    eps = 1e-12

    out["orderflow_imbalance_ma_3"] = out["orderflow_imbalance"].rolling(3).mean()
    out["orderflow_imbalance_ma_6"] = out["orderflow_imbalance"].rolling(6).mean()

    out["buyer_taker_ratio_ma_3"] = out["buyer_taker_ratio"].rolling(3).mean()
    out["buyer_taker_ratio_ma_6"] = out["buyer_taker_ratio"].rolling(6).mean()

    out["agg_count_ma_6"] = out["agg_count"].rolling(6).mean()
    out["agg_avg_qty_ma_6"] = out["agg_avg_qty"].rolling(6).mean()

    out["agg_count_ratio_6"] = out["agg_count"] / (out["agg_count_ma_6"] + eps)
    out["agg_avg_qty_ratio_6"] = out["agg_avg_qty"] / (out["agg_avg_qty_ma_6"] + eps)
    out["vwap_close_diff"] = (out["close"] - out["agg_vwap"]) / (out["agg_vwap"] + eps)

    return out