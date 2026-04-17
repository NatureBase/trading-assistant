from __future__ import annotations

import asyncio
import io
import json
import time
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests
import websockets
import traceback

from .feature_engine import build_agg_row, get_latest_feature_vector
from .kline_features import add_kline_features
from .model_loader import load_models
from .risk_engine import get_sl_tp
from .session_manager import session_state
from .signal_engine import (
    filter_action_by_trend,
    get_dynamic_thresholds,
    get_higher_tf_trend,
    get_market_regime,
    position_size,
    raw_decision,
)

BINANCE_WS = "wss://data-stream.binance.vision/stream?streams=btcusdt@aggTrade/btcusdt@kline_5m"

BINANCE_REST_CANDIDATES = [
    "https://api.binance.com",
    "https://api1.binance.com",
    "https://api2.binance.com",
    "https://api3.binance.com",
    "https://api4.binance.com",
    "https://api-gcp.binance.com",
]

BASE_PUBLIC_DATA = "https://data.binance.vision/data/spot/daily"
CACHE_BASE_DIR = Path(__file__).resolve().parents[1] / "cache" / "binance_public_data"


def fetch_klines_rest(symbol: str, interval: str, limit: int = 200) -> list[dict[str, Any]]:
    last_error = None

    for base_url in BINANCE_REST_CANDIDATES:
        try:
            print(f"[REST] Trying {base_url} for {symbol} {interval} limit={limit}")
            url = f"{base_url}/api/v3/klines"
            params = {"symbol": symbol, "interval": interval, "limit": limit}
            resp = requests.get(url, params=params, timeout=30)
            resp.raise_for_status()
            rows = resp.json()

            out = []
            for r in rows:
                out.append(
                    {
                        # REST timestamps are milliseconds -> convert to microseconds
                        "open_time": int(r[0]) * 1000,
                        "open": float(r[1]),
                        "high": float(r[2]),
                        "low": float(r[3]),
                        "close": float(r[4]),
                        "volume": float(r[5]),
                        "close_time": int(r[6]) * 1000,
                        "quote_asset_volume": float(r[7]),
                        "num_trades": float(r[8]),
                        "taker_buy_base": float(r[9]),
                        "taker_buy_quote": float(r[10]),
                    }
                )

            print(f"[REST] Success from {base_url}: fetched {len(out)} rows")
            return out

        except Exception as e:
            last_error = e
            print(f"[REST] Failed for {base_url}: {e}")

    raise RuntimeError(f"All Binance REST endpoints failed. Last error: {last_error}")


def _download_bytes(url: str, retries: int = 3, sleep_seconds: int = 5) -> bytes:
    last_error = None

    for attempt in range(1, retries + 1):
        try:
            print(f"[DOWNLOAD] Attempt {attempt}/{retries}: {url}")
            resp = requests.get(url, timeout=60)
            resp.raise_for_status()
            return resp.content
        except Exception as e:
            last_error = e
            print(f"[DOWNLOAD] Failed attempt {attempt}: {e}")
            if attempt < retries:
                time.sleep(sleep_seconds)

    raise last_error


def _candidate_days(max_days_back: int = 4) -> list[str]:
    base = datetime.now(timezone.utc).date()
    out = []
    for i in range(1, max_days_back + 1):
        dt = base - timedelta(days=i)
        out.append(dt.strftime("%Y-%m-%d"))
    return out


def _find_available_day(max_days_back: int = 4) -> str:
    last_error = None

    for day_str in _candidate_days(max_days_back=max_days_back):
        test_url = (
            f"{BASE_PUBLIC_DATA}/klines/BTCUSDT/5m/"
            f"BTCUSDT-5m-{day_str}.zip"
        )

        try:
            print(f"[WARMUP] Checking availability for {day_str}")
            resp = requests.head(test_url, timeout=15)
            if resp.status_code == 200:
                print(f"[WARMUP] Found available day: {day_str}")
                return day_str
        except Exception as e:
            last_error = e
            print(f"[WARMUP] HEAD failed for {day_str}: {e}")

    raise RuntimeError(f"No available historical data found in last {max_days_back} days. Last error: {last_error}")


def _get_cache_paths(day_str: str) -> dict[str, Path]:
    kline_dir = CACHE_BASE_DIR / "klines"
    agg_dir = CACHE_BASE_DIR / "aggtrades"

    kline_dir.mkdir(parents=True, exist_ok=True)
    agg_dir.mkdir(parents=True, exist_ok=True)

    return {
        "kline_zip": kline_dir / f"BTCUSDT-5m-{day_str}.zip",
        "kline_csv": kline_dir / f"BTCUSDT-5m-{day_str}.csv",
        "agg_zip": agg_dir / f"BTCUSDT-aggTrades-{day_str}.zip",
        "agg_csv": agg_dir / f"BTCUSDT-aggTrades-{day_str}.csv",
    }


def _extract_first_csv(zip_path: Path, out_csv_path: Path) -> None:
    with zipfile.ZipFile(zip_path, "r") as zf:
        csv_names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        if not csv_names:
            raise RuntimeError(f"No CSV found in zip: {zip_path}")

        csv_name = csv_names[0]
        with zf.open(csv_name) as src, open(out_csv_path, "wb") as dst:
            dst.write(src.read())


def _load_or_download_public_data(day_str: str) -> tuple[Path, Path]:
    paths = _get_cache_paths(day_str)

    kline_url = (
        f"{BASE_PUBLIC_DATA}/klines/BTCUSDT/5m/BTCUSDT-5m-{day_str}.zip"
    )
    agg_url = (
        f"{BASE_PUBLIC_DATA}/aggTrades/BTCUSDT/BTCUSDT-aggTrades-{day_str}.zip"
    )

    # KLINE
    if paths["kline_csv"].exists():
        print(f"[CACHE] Using cached kline csv: {paths['kline_csv']}")
    else:
        if not paths["kline_zip"].exists():
            print(f"[CACHE] Kline zip not found, downloading: {kline_url}")
            kline_zip_bytes = _download_bytes(kline_url)
            with open(paths["kline_zip"], "wb") as f:
                f.write(kline_zip_bytes)
        else:
            print(f"[CACHE] Using cached kline zip: {paths['kline_zip']}")

        _extract_first_csv(paths["kline_zip"], paths["kline_csv"])
        print(f"[CACHE] Extracted kline csv: {paths['kline_csv']}")

    # AGGTRADES
    if paths["agg_csv"].exists():
        print(f"[CACHE] Using cached aggTrades csv: {paths['agg_csv']}")
    else:
        if not paths["agg_zip"].exists():
            print(f"[CACHE] aggTrades zip not found, downloading: {agg_url}")
            agg_zip_bytes = _download_bytes(agg_url)
            with open(paths["agg_zip"], "wb") as f:
                f.write(agg_zip_bytes)
        else:
            print(f"[CACHE] Using cached aggTrades zip: {paths['agg_zip']}")

        _extract_first_csv(paths["agg_zip"], paths["agg_csv"])
        print(f"[CACHE] Extracted aggTrades csv: {paths['agg_csv']}")

    return paths["kline_csv"], paths["agg_csv"]


def _read_kline_csv(csv_path: Path) -> list[dict[str, Any]]:
    cols = [
        "open_time",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "close_time",
        "quote_asset_volume",
        "num_trades",
        "taker_buy_base",
        "taker_buy_quote",
        "ignore",
    ]

    df = pd.read_csv(csv_path, header=None, names=cols)

    # public spot data timestamps are microseconds
    df["open_time"] = df["open_time"].astype("int64")
    df["close_time"] = df["close_time"].astype("int64")

    numeric_cols = [
        "open",
        "high",
        "low",
        "close",
        "volume",
        "quote_asset_volume",
        "num_trades",
        "taker_buy_base",
        "taker_buy_quote",
    ]
    for c in numeric_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    df = df.drop(columns=["ignore"])
    df = df.sort_values("open_time").reset_index(drop=True)

    return df.to_dict(orient="records")


def _read_aggtrades_csv(csv_path: Path) -> pd.DataFrame:
    cols = [
        "agg_trade_id",
        "price",
        "qty",
        "first_trade_id",
        "last_trade_id",
        "timestamp",
        "is_buyer_maker",
        "is_best_match",
    ]

    df = pd.read_csv(csv_path, header=None, names=cols)

    df["timestamp"] = df["timestamp"].astype("int64")
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    df["qty"] = pd.to_numeric(df["qty"], errors="coerce")
    df["is_buyer_maker"] = (
        df["is_buyer_maker"]
        .astype(str)
        .str.lower()
        .map({"true": True, "false": False})
    )

    df = df.sort_values("timestamp").reset_index(drop=True)
    return df


def _build_agg_features_from_daily_aggtrades(
    kline_records: list[dict[str, Any]],
    agg_df: pd.DataFrame,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for k in kline_records:
        open_us = int(k["open_time"])
        close_us = int(k["close_time"])

        bucket = agg_df[(agg_df["timestamp"] >= open_us) & (agg_df["timestamp"] <= close_us)]

        trades = []
        for _, r in bucket.iterrows():
            trades.append(
                {
                    "price": float(r["price"]),
                    "qty": float(r["qty"]),
                    "is_buyer_maker": bool(r["is_buyer_maker"]),
                    "trade_time": int(r["timestamp"]),
                }
            )

        rows.append(build_agg_row(trades))

    return rows


def _build_1h_from_5m_records(kline_5m_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not kline_5m_records:
        return []

    df = pd.DataFrame(kline_5m_records).copy()
    df["open_dt"] = pd.to_datetime(df["open_time"], unit="us", utc=True)
    df = df.sort_values("open_dt").reset_index(drop=True)
    df = df.set_index("open_dt")

    agg = df.resample("1h").agg(
        {
            "open_time": "first",
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
            "close_time": "last",
            "quote_asset_volume": "sum",
            "num_trades": "sum",
            "taker_buy_base": "sum",
            "taker_buy_quote": "sum",
        }
    )

    agg = agg.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)
    return agg.to_dict(orient="records")


def update_1h_from_5m() -> None:
    if len(session_state.kline_5m_buffer) < 12:
        return

    last_12 = session_state.kline_5m_buffer[-12:]

    candle_1h = {
        "open_time": last_12[0]["open_time"],
        "open": last_12[0]["open"],
        "high": max(x["high"] for x in last_12),
        "low": min(x["low"] for x in last_12),
        "close": last_12[-1]["close"],
        "volume": sum(x["volume"] for x in last_12),
        "close_time": last_12[-1]["close_time"],
        "quote_asset_volume": sum(x["quote_asset_volume"] for x in last_12),
        "num_trades": sum(x["num_trades"] for x in last_12),
        "taker_buy_base": sum(x["taker_buy_base"] for x in last_12),
        "taker_buy_quote": sum(x["taker_buy_quote"] for x in last_12),
    }

    if (
        len(session_state.kline_1h_buffer) == 0
        or session_state.kline_1h_buffer[-1]["open_time"] != candle_1h["open_time"]
    ):
        session_state.kline_1h_buffer.append(candle_1h)
        session_state.kline_1h_buffer = session_state.kline_1h_buffer[-120:]
    else:
        session_state.kline_1h_buffer[-1] = candle_1h


def warmup_from_rest_api() -> None:
    print("[WARMUP] Using source = rest_api")

    k5 = fetch_klines_rest("BTCUSDT", "5m", 288)
    k1h = fetch_klines_rest("BTCUSDT", "1h", 120)

    session_state.kline_5m_buffer = k5
    session_state.kline_1h_buffer = k1h
    session_state.closed_5m_candles = k5[-100:]
    session_state.agg_trade_current_bucket = []
    session_state.agg_features_buffer = [build_agg_row([]) for _ in range(len(k5))]
    session_state.historical_loaded = True

    session_state.status = "ready"
    session_state.reason = "historical loaded from rest api"

    print(
        f"[WARMUP] Success (rest_api): 5m={len(session_state.kline_5m_buffer)}, "
        f"1h={len(session_state.kline_1h_buffer)}"
    )


def warmup_from_public_data() -> None:
    print("[WARMUP] Using source = public_data")

    day_str = _find_available_day(max_days_back=4)
    print(f"[WARMUP] Using historical date: {day_str}")

    kline_csv, agg_csv = _load_or_download_public_data(day_str)

    k5 = _read_kline_csv(kline_csv)
    agg_df = _read_aggtrades_csv(agg_csv)
    agg_features = _build_agg_features_from_daily_aggtrades(k5, agg_df)
    k1h = _build_1h_from_5m_records(k5)

    session_state.kline_5m_buffer = k5
    session_state.kline_1h_buffer = k1h
    session_state.closed_5m_candles = k5[-100:]
    session_state.agg_trade_current_bucket = []
    session_state.agg_features_buffer = agg_features
    session_state.historical_loaded = True

    session_state.status = "ready"
    session_state.reason = f"historical loaded from public_data ({day_str})"

    print(
        f"[WARMUP] Success (public_data): day={day_str}, "
        f"5m={len(session_state.kline_5m_buffer)}, "
        f"1h={len(session_state.kline_1h_buffer)}, "
        f"agg={len(session_state.agg_features_buffer)}"
    )


def warmup_session(source: str = "public_data") -> None:
    session_state.is_warming_up = True
    session_state.status = "warming_up"
    session_state.reason = f"loading historical data from {source}"
    session_state.historical_source = source

    try:
        if source == "rest_api":
            try:
                warmup_from_rest_api()
            except Exception as e:
                print(f"[WARMUP] REST FAILED -> fallback to public_data: {e}")
                warmup_from_public_data()
                session_state.historical_source = "public_data"
                session_state.reason = "REST failed -> fallback to public_data"

        elif source == "public_data":
            warmup_from_public_data()

        else:
            raise ValueError(f"Unknown source: {source}")

    finally:
        session_state.is_warming_up = False


def build_signal_payload(prob_buy: float, prob_sell: float, df_5m: pd.DataFrame, df_1h: pd.DataFrame) -> dict:
    row_5m = df_5m.iloc[-1]
    row_1h = df_1h.iloc[-1]

    regime = get_market_regime(
        float(row_5m["volatility_24"]),
        float(row_5m["atr_14"]),
        float(row_5m["close"]),
    )
    buy_th, sell_th = get_dynamic_thresholds(regime)

    trend_1h = get_higher_tf_trend(
        float(row_1h["close"]),
        float(row_1h["ema_9"]),
        float(row_1h["ema_21"]),
    )

    action_raw = raw_decision(prob_buy, prob_sell, buy_th, sell_th, margin=0.02)
    action = filter_action_by_trend(action_raw, trend_1h)

    if action == "BUY":
        size = position_size(prob_buy)
    elif action == "SELL":
        size = position_size(prob_sell)
    else:
        size = 0.0

    sl, tp = get_sl_tp(float(row_5m["close"]), float(row_5m["atr_14"]), action)

    return {
        "time": int(row_5m["open_time"]),
        "close_price": float(row_5m["close"]),
        "prob_buy": float(prob_buy),
        "prob_sell": float(prob_sell),
        "regime": regime,
        "trend_1h": trend_1h,
        "buy_threshold": buy_th,
        "sell_threshold": sell_th,
        "action": action,
        "position_size": size,
        "stop_loss": float(sl),
        "take_profit": float(tp),
    }


def run_manual_prediction() -> dict[str, Any]:
    min_5m_bars = 55
    min_1h_bars = 12

    if len(session_state.kline_5m_buffer) < min_5m_bars:
        return {
            "ok": False,
            "message": "Not enough 5m history for prediction",
            "kline_5m_count": len(session_state.kline_5m_buffer),
            "required_5m": min_5m_bars,
        }

    if len(session_state.kline_1h_buffer) < min_1h_bars:
        return {
            "ok": False,
            "message": "Not enough 1h history for prediction",
            "kline_1h_count": len(session_state.kline_1h_buffer),
            "required_1h": min_1h_bars,
        }

    buy_model, sell_model = load_models()

    X_5m, df_5m = get_latest_feature_vector(
        session_state.kline_5m_buffer,
        session_state.agg_features_buffer,
    )

    df_1h = pd.DataFrame(session_state.kline_1h_buffer).copy()
    df_1h = add_kline_features(df_1h).replace([float("inf"), float("-inf")], 0).fillna(0)

    prob_buy = float(buy_model.predict_proba(X_5m)[0][1])
    prob_sell = float(sell_model.predict_proba(X_5m)[0][1])

    signal = build_signal_payload(prob_buy, prob_sell, df_5m, df_1h)
    session_state.last_prediction = signal
    session_state.last_signal = signal
    session_state.signal_history.append(signal)
    session_state.signal_history = session_state.signal_history[-200:]

    print(
        f"[PREDICT] prob_buy={prob_buy:.4f}, prob_sell={prob_sell:.4f}, action={signal['action']}"
    )

    return {"ok": True, "prediction": signal}


async def run_live_loop(broadcast_cb):
    reconnect_delay_seconds = 5

    while session_state.is_active:
        try:
            print("[LIVE] Connecting to Binance websocket...")
            session_state.status = "connecting"
            session_state.reason = "connecting websocket"

            async with websockets.connect(
                BINANCE_WS,
                ping_interval=20,
                ping_timeout=20,
                close_timeout=10,
            ) as ws:
                session_state.status = "live"
                session_state.reason = f"historical loaded + live stream connected ({session_state.historical_source})"
                print("[LIVE] Binance websocket connected")

                while session_state.is_active:
                    raw = await ws.recv()
                    msg = json.loads(raw)
                    data = msg.get("data", {})
                    event_type = data.get("e")

                    if event_type == "aggTrade":
                        trade_item = {
                            "price": float(data["p"]),
                            "qty": float(data["q"]),
                            "is_buyer_maker": bool(data["m"]),
                            "trade_time": int(data["T"]) * 1000,  # ms -> µs
                        }

                        session_state.agg_trade_current_bucket.append(trade_item)

                        await broadcast_cb(
                            {
                                "type": "agg_trade",
                                "price": trade_item["price"],
                                "qty": trade_item["qty"],
                                "is_buyer_maker": trade_item["is_buyer_maker"],
                                "trade_time": trade_item["trade_time"],
                            }
                        )

                    elif event_type == "kline":
                        k = data["k"]

                        forming = {
                            "open_time": int(k["t"]) * 1000,   # ms -> µs
                            "open": float(k["o"]),
                            "high": float(k["h"]),
                            "low": float(k["l"]),
                            "close": float(k["c"]),
                            "volume": float(k["v"]),
                            "close_time": int(k["T"]) * 1000,  # ms -> µs
                            "quote_asset_volume": float(k["q"]),
                            "num_trades": float(k["n"]),
                            "taker_buy_base": float(k["V"]),
                            "taker_buy_quote": float(k["Q"]),
                        }

                        await broadcast_cb(
                            {
                                "type": "forming_kline",
                                "kline": forming,
                            }
                        )

                        if bool(k["x"]):
                            session_state.kline_5m_buffer.append(forming)
                            session_state.kline_5m_buffer = session_state.kline_5m_buffer[-288:]

                            session_state.closed_5m_candles.append(forming)
                            session_state.closed_5m_candles = session_state.closed_5m_candles[-100:]

                            agg_row = build_agg_row(session_state.agg_trade_current_bucket)
                            session_state.agg_features_buffer.append(agg_row)
                            session_state.agg_features_buffer = session_state.agg_features_buffer[-288:]
                            session_state.agg_trade_current_bucket = []

                            update_1h_from_5m()

                            await broadcast_cb(
                                {
                                    "type": "closed_kline",
                                    "closed_kline": forming,
                                    "kline_5m_count": len(session_state.kline_5m_buffer),
                                    "kline_1h_count": len(session_state.kline_1h_buffer),
                                }
                            )

        except asyncio.CancelledError:
            print("[LIVE] Websocket task cancelled")
            session_state.status = "stopped"
            session_state.reason = "websocket task cancelled"
            raise

        except Exception as e:
            print("[LIVE][ERROR] websocket disconnected")
            print(f"[LIVE][ERROR] {e}")
            traceback.print_exc()

            if not session_state.is_active:
                break

            session_state.status = "reconnecting"
            session_state.reason = f"websocket disconnected: {e}"

            try:
                await broadcast_cb(
                    {
                        "type": "ws_status",
                        "status": "reconnecting",
                        "reason": str(e),
                    }
                )
            except Exception:
                pass

            print(f"[LIVE] Reconnecting in {reconnect_delay_seconds} seconds...")
            await asyncio.sleep(reconnect_delay_seconds)