import numpy as np
import pandas as pd


def add_kline_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    eps = 1e-12

    out["ret_1"] = out["close"].pct_change(1)
    out["ret_3"] = out["close"].pct_change(3)
    out["ret_6"] = out["close"].pct_change(6)
    out["ret_12"] = out["close"].pct_change(12)

    out["logret_1"] = np.log(out["close"] / out["close"].shift(1))
    out["logret_3"] = np.log(out["close"] / out["close"].shift(3))

    out["body"] = out["close"] - out["open"]
    out["abs_body"] = out["body"].abs()
    out["hl_range"] = out["high"] - out["low"]
    out["upper_wick"] = out["high"] - np.maximum(out["open"], out["close"])
    out["lower_wick"] = np.minimum(out["open"], out["close"]) - out["low"]

    out["body_ratio"] = out["abs_body"] / (out["hl_range"] + eps)
    out["upper_wick_ratio"] = out["upper_wick"] / (out["hl_range"] + eps)
    out["lower_wick_ratio"] = out["lower_wick"] / (out["hl_range"] + eps)
    out["range_pct"] = out["hl_range"] / (out["close"] + eps)

    out["volatility_6"] = out["ret_1"].rolling(6).std()
    out["volatility_12"] = out["ret_1"].rolling(12).std()
    out["volatility_24"] = out["ret_1"].rolling(24).std()

    prev_close = out["close"].shift(1)
    tr1 = out["high"] - out["low"]
    tr2 = (out["high"] - prev_close).abs()
    tr3 = (out["low"] - prev_close).abs()
    out["true_range"] = np.maximum.reduce([tr1, tr2, tr3])
    out["atr_14"] = out["true_range"].rolling(14).mean()

    out["ema_9"] = out["close"].ewm(span=9, adjust=False).mean()
    out["ema_21"] = out["close"].ewm(span=21, adjust=False).mean()
    out["ema_50"] = out["close"].ewm(span=50, adjust=False).mean()

    out["dist_ema_9"] = (out["close"] - out["ema_9"]) / (out["ema_9"] + eps)
    out["dist_ema_21"] = (out["close"] - out["ema_21"]) / (out["ema_21"] + eps)
    out["dist_ema_50"] = (out["close"] - out["ema_50"]) / (out["ema_50"] + eps)

    out["ema_spread_9_21"] = (out["ema_9"] - out["ema_21"]) / (out["ema_21"] + eps)
    out["ema_spread_21_50"] = (out["ema_21"] - out["ema_50"]) / (out["ema_50"] + eps)

    out["volume_ma_6"] = out["volume"].rolling(6).mean()
    out["volume_ma_12"] = out["volume"].rolling(12).mean()
    out["num_trades_ma_6"] = out["num_trades"].rolling(6).mean()
    out["num_trades_ma_12"] = out["num_trades"].rolling(12).mean()

    out["volume_ratio_6"] = out["volume"] / (out["volume_ma_6"] + eps)
    out["volume_ratio_12"] = out["volume"] / (out["volume_ma_12"] + eps)
    out["num_trades_ratio_6"] = out["num_trades"] / (out["num_trades_ma_6"] + eps)
    out["num_trades_ratio_12"] = out["num_trades"] / (out["num_trades_ma_12"] + eps)

    out["taker_buy_ratio"] = out["taker_buy_base"] / (out["volume"] + eps)
    out["taker_sell_base"] = out["volume"] - out["taker_buy_base"]
    out["kline_buy_sell_pressure"] = (
        (out["taker_buy_base"] - out["taker_sell_base"]) / (out["volume"] + eps)
    )

    # RSI 14
    delta = out["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()
    rs = avg_gain / (avg_loss + eps)
    out["rsi_14"] = 100 - (100 / (1 + rs))

    return out