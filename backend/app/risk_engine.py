def get_sl_tp(
    entry_price: float,
    atr_14: float,
    side: str,
    sl_mult: float = 1.2,
    tp_mult: float = 2.0,
):
    if side == "BUY":
        stop_loss = entry_price - sl_mult * atr_14
        take_profit = entry_price + tp_mult * atr_14
    elif side == "SELL":
        stop_loss = entry_price + sl_mult * atr_14
        take_profit = entry_price - tp_mult * atr_14
    else:
        stop_loss = entry_price
        take_profit = entry_price

    return stop_loss, take_profit