def get_market_regime(volatility_24: float, atr_14: float, close_price: float) -> str:
    atr_pct = atr_14 / max(close_price, 1e-12)

    if volatility_24 < 0.002 and atr_pct < 0.003:
        return "calm"
    if volatility_24 < 0.005 and atr_pct < 0.006:
        return "normal"
    return "volatile"


def get_dynamic_thresholds(regime: str) -> tuple[float, float]:
    if regime == "calm":
        return 0.11, 0.09
    if regime == "normal":
        return 0.13, 0.11
    return 0.16, 0.14


def get_higher_tf_trend(close_1h: float, ema9_1h: float, ema21_1h: float) -> str:
    if close_1h > ema21_1h and ema9_1h > ema21_1h:
        return "bullish"
    if close_1h < ema21_1h and ema9_1h < ema21_1h:
        return "bearish"
    return "neutral"


def raw_decision(
    prob_buy: float,
    prob_sell: float,
    buy_th: float,
    sell_th: float,
    margin: float = 0.02,
) -> str:
    buy_on = prob_buy >= buy_th
    sell_on = prob_sell >= sell_th

    if buy_on and not sell_on:
        return "BUY"
    if sell_on and not buy_on:
        return "SELL"
    if buy_on and sell_on:
        if prob_buy - prob_sell > margin:
            return "BUY"
        if prob_sell - prob_buy > margin:
            return "SELL"
    return "HOLD"


def filter_action_by_trend(action: str, trend_1h: str) -> str:
    if action == "BUY" and trend_1h == "bearish":
        return "HOLD"
    if action == "SELL" and trend_1h == "bullish":
        return "HOLD"
    return action


def position_size(prob: float) -> float:
    if prob < 0.08:
        return 0.0
    if prob < 0.12:
        return 0.25
    if prob < 0.18:
        return 0.50
    return 0.75