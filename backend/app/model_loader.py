from pathlib import Path
import joblib

BASE_DIR = Path(__file__).resolve().parents[1]
BUY_MODEL_PATH = BASE_DIR / "model_buy.pkl"
SELL_MODEL_PATH = BASE_DIR / "model_sell.pkl"

FEATURE_COLUMNS = [
    "ret_1", "ret_3", "ret_6", "ret_12", "logret_1", "logret_3", "body",
    "abs_body", "hl_range", "upper_wick", "lower_wick", "body_ratio",
    "upper_wick_ratio", "lower_wick_ratio", "range_pct", "volatility_6",
    "volatility_12", "volatility_24", "atr_14", "dist_ema_9", "dist_ema_21",
    "dist_ema_50", "ema_spread_9_21", "ema_spread_21_50", "volume_ratio_6",
    "volume_ratio_12", "num_trades_ratio_6", "num_trades_ratio_12",
    "taker_buy_ratio", "kline_buy_sell_pressure", "agg_count",
    "agg_total_qty", "agg_total_quote", "agg_avg_qty", "agg_avg_quote",
    "buyer_taker_qty", "seller_taker_qty", "buyer_taker_ratio",
    "seller_taker_ratio", "orderflow_imbalance", "buyer_taker_count",
    "seller_taker_count", "buyer_taker_count_ratio",
    "seller_taker_count_ratio", "agg_vwap", "agg_price_std",
    "agg_price_range", "vwap_close_diff", "orderflow_imbalance_ma_3",
    "orderflow_imbalance_ma_6", "buyer_taker_ratio_ma_3",
    "buyer_taker_ratio_ma_6", "agg_count_ratio_6",
    "agg_avg_qty_ratio_6", "rsi_14"
]

_buy_model = None
_sell_model = None


def load_models():
    global _buy_model, _sell_model

    print(f"[MODEL] BASE_DIR={BASE_DIR}")
    print(f"[MODEL] BUY_MODEL_PATH={BUY_MODEL_PATH}")
    print(f"[MODEL] SELL_MODEL_PATH={SELL_MODEL_PATH}")
    print(f"[MODEL] BUY exists? {BUY_MODEL_PATH.exists()}")
    print(f"[MODEL] SELL exists? {SELL_MODEL_PATH.exists()}")

    if _buy_model is None:
        print("[MODEL] Loading buy model with joblib...")
        _buy_model = joblib.load(BUY_MODEL_PATH)
        print(f"[MODEL] Buy model loaded: {type(_buy_model)}")

    if _sell_model is None:
        print("[MODEL] Loading sell model with joblib...")
        _sell_model = joblib.load(SELL_MODEL_PATH)
        print(f"[MODEL] Sell model loaded: {type(_sell_model)}")

    return _buy_model, _sell_model