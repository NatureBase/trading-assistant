from __future__ import annotations

import asyncio
import json
import time
import traceback
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests
import websockets

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


BINANCE_WS = (
    "wss://data-stream.binance.vision/stream?"
    "streams=btcusdt@aggTrade/btcusdt@kline_5m"
)

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


# ============================================================
# TIME HELPERS
# ============================================================

def _to_microseconds(value: int | float) -> int:
    """
    Normalize epoch timestamp to microseconds.

    Supported:
    - seconds      ~ 1e9
    - milliseconds ~ 1e12
    - microseconds ~ 1e15
    - nanoseconds  ~ 1e18
    """
    v = int(value)

    if v < 1e11:
        return v * 1_000_000

    if v < 1e14:
        return v * 1_000

    if v < 1e17:
        return v

    return v // 1_000


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _start_of_today_utc() -> datetime:
    now = _now_utc()
    return datetime(now.year, now.month, now.day, tzinfo=timezone.utc)


def _candidate_days(max_days_back: int = 4) -> list[str]:
    base = _now_utc().date()
    return [
        (base - timedelta(days=i)).strftime("%Y-%m-%d")
        for i in range(1, max_days_back + 1)
    ]


# ============================================================
# BINANCE REST API
# ============================================================

def _rest_get_klines(
    symbol: str,
    interval: str,
    start_ms: int | None = None,
    end_ms: int | None = None,
    limit: int = 1000,
) -> list[list[Any]]:
    """
    Low-level REST fetch with endpoint fallback.
    Timestamps here are milliseconds because Binance REST expects ms.
    """
    last_error = None

    for base_url in BINANCE_REST_CANDIDATES:
        try:
            url = f"{base_url}/api/v3/klines"
            params: dict[str, Any] = {
                "symbol": symbol,
                "interval": interval,
                "limit": limit,
            }

            if start_ms is not None:
                params["startTime"] = start_ms
            if end_ms is not None:
                params["endTime"] = end_ms

            print(
                f"[REST] Trying {base_url} for {symbol} {interval} "
                f"start={start_ms} end={end_ms} limit={limit}"
            )

            resp = requests.get(url, params=params, timeout=30)
            resp.raise_for_status()
            rows = resp.json()

            print(f"[REST] Success from {base_url}: fetched {len(rows)} rows")
            return rows

        except Exception as e:
            last_error = e
            print(f"[REST] Failed for {base_url}: {e}")

    raise RuntimeError(f"All Binance REST endpoints failed. Last error: {last_error}")


def _convert_rest_klines_to_records(rows: list[list[Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    for r in rows:
        out.append(
            {
                "open_time": _to_microseconds(int(r[0])),
                "open": float(r[1]),
                "high": float(r[2]),
                "low": float(r[3]),
                "close": float(r[4]),
                "volume": float(r[5]),
                "close_time": _to_microseconds(int(r[6])),
                "quote_asset_volume": float(r[7]),
                "num_trades": float(r[8]),
                "taker_buy_base": float(r[9]),
                "taker_buy_quote": float(r[10]),
            }
        )

    return out


def fetch_klines_rest(symbol: str, interval: str, limit: int = 200) -> list[dict[str, Any]]:
    rows = _rest_get_klines(symbol=symbol, interval=interval, limit=limit)
    return _convert_rest_klines_to_records(rows)


def fetch_klines_rest_range(
    symbol: str,
    interval: str,
    start_ms: int,
    end_ms: int,
) -> list[dict[str, Any]]:
    """
    Fetch klines in a time range using REST.
    For 5m from yesterday 00:00 UTC to now, total rows are normally < 1000,
    so one request is enough. This function still supports pagination.
    """
    all_rows: list[list[Any]] = []
    current_start = start_ms

    while current_start < end_ms:
        rows = _rest_get_klines(
            symbol=symbol,
            interval=interval,
            start_ms=current_start,
            end_ms=end_ms,
            limit=1000,
        )

        if not rows:
            break

        all_rows.extend(rows)

        last_open_ms = int(rows[-1][0])
        next_start = last_open_ms + 1

        if next_start <= current_start:
            break

        current_start = next_start

        if len(rows) < 1000:
            break

    return _convert_rest_klines_to_records(all_rows)


def fetch_rest_1d_plus_today(symbol: str = "BTCUSDT", interval: str = "5m") -> list[dict[str, Any]]:
    """
    Fetch:
    - yesterday full day UTC
    - today from 00:00 UTC until now

    Result: roughly 288 + current-day candles.
    """
    now = _now_utc()
    start_today = _start_of_today_utc()
    start_yesterday = start_today - timedelta(days=1)

    start_ms = int(start_yesterday.timestamp() * 1000)
    end_ms = int(now.timestamp() * 1000)

    print(f"[REST] Fetching {symbol} {interval} from {start_yesterday} -> {now}")

    return fetch_klines_rest_range(
        symbol=symbol,
        interval=interval,
        start_ms=start_ms,
        end_ms=end_ms,
    )


# ============================================================
# PUBLIC DATA CACHE
# ============================================================

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

    raise RuntimeError(f"Download failed after {retries} attempts. Last error: {last_error}")


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

            print(f"[WARMUP] Not available yet: {day_str}, status={resp.status_code}")

        except Exception as e:
            last_error = e
            print(f"[WARMUP] HEAD failed for {day_str}: {e}")

    raise RuntimeError(
        f"No available historical data found in last {max_days_back} days. "
        f"Last error: {last_error}"
    )


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

    kline_url = f"{BASE_PUBLIC_DATA}/klines/BTCUSDT/5m/BTCUSDT-5m-{day_str}.zip"
    agg_url = f"{BASE_PUBLIC_DATA}/aggTrades/BTCUSDT/BTCUSDT-aggTrades-{day_str}.zip"

    # KLINES
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


# ============================================================
# PUBLIC DATA READERS
# ============================================================

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

    df["open_time"] = df["open_time"].astype("int64").map(_to_microseconds)
    df["close_time"] = df["close_time"].astype("int64").map(_to_microseconds)

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

    df["timestamp"] = df["timestamp"].astype("int64").map(_to_microseconds)
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

        bucket = agg_df[
            (agg_df["timestamp"] >= open_us)
            & (agg_df["timestamp"] <= close_us)
        ]

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

        row = build_agg_row(trades)
        row["open_time"] = open_us
        rows.append(row)

    return rows

def _upsert_agg_feature_row(
    buffer: list[dict[str, Any]],
    row: dict[str, Any],
    open_time: int,
    maxlen: int,
) -> list[dict[str, Any]]:
    row = dict(row)
    row["open_time"] = int(open_time)

    by_open_time: dict[int, dict[str, Any]] = {}

    for item in buffer:
        if "open_time" in item:
            by_open_time[int(item["open_time"])] = item

    by_open_time[int(open_time)] = row

    out = sorted(by_open_time.values(), key=lambda x: int(x["open_time"]))

    if len(out) > maxlen:
        out = out[-maxlen:]

    buffer[:] = out
    return buffer

def _count_duplicate_open_times(candles: list[dict[str, Any]]) -> int:
    times = [int(c["open_time"]) for c in candles if "open_time" in c]
    return len(times) - len(set(times))

# ============================================================
# CANDLE HELPERS
# ============================================================

def _dedupe_sort_candles(
    candles: list[dict[str, Any]],
    maxlen: int | None = None,
) -> list[dict[str, Any]]:
    by_open_time: dict[int, dict[str, Any]] = {}

    for c in candles:
        by_open_time[int(c["open_time"])] = c

    out = sorted(by_open_time.values(), key=lambda x: int(x["open_time"]))

    if maxlen is not None:
        out = out[-maxlen:]

    return out


def _upsert_candle(
    buffer: list[dict[str, Any]],
    candle: dict[str, Any],
    maxlen: int,
) -> tuple[list[dict[str, Any]], bool]:
    """
    Return (buffer, replaced_existing_last)
    """
    if buffer and int(buffer[-1]["open_time"]) == int(candle["open_time"]):
        buffer[-1] = candle
        return buffer, True

    buffer.append(candle)

    if len(buffer) > maxlen:
        buffer[:] = buffer[-maxlen:]

    return buffer, False


def _upsert_feature_row(
    buffer: list[dict[str, Any]],
    row: dict[str, Any],
    replaced_last: bool,
    maxlen: int,
) -> list[dict[str, Any]]:
    if replaced_last and buffer:
        buffer[-1] = row
        return buffer

    buffer.append(row)

    if len(buffer) > maxlen:
        buffer[:] = buffer[-maxlen:]

    return buffer


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
        or int(session_state.kline_1h_buffer[-1]["open_time"])
        != int(candle_1h["open_time"])
    ):
        session_state.kline_1h_buffer.append(candle_1h)
        session_state.kline_1h_buffer = session_state.kline_1h_buffer[-120:]
    else:
        session_state.kline_1h_buffer[-1] = candle_1h


# ============================================================
# WARMUP SOURCES
# ============================================================

def warmup_from_rest_api() -> None:
    print("[WARMUP] Using source = rest_api")

    # Kemarin 00:00 UTC sampai sekarang
    k5 = fetch_rest_1d_plus_today("BTCUSDT", "5m")
    k1h = fetch_rest_1d_plus_today("BTCUSDT", "1h")

    # keep roughly two days max, because yesterday + today can exceed 288 candles
    k5 = _dedupe_sort_candles(k5, maxlen=600)
    k1h = _dedupe_sort_candles(k1h, maxlen=120)

    session_state.kline_5m_buffer = k5
    session_state.kline_1h_buffer = k1h
    session_state.closed_5m_candles = _dedupe_sort_candles(k5[-100:], maxlen=100)
    session_state.agg_trade_current_bucket = []

    # REST kline tidak menyediakan historical aggTrades.
    # Placeholder agar feature vector tetap punya panjang yang sama.
    session_state.agg_features_buffer = [build_agg_row([]) for _ in range(len(k5))]

    session_state.historical_loaded = True
    session_state.status = "ready"
    session_state.reason = "historical loaded from rest api"

    print(
        f"[WARMUP] Success (rest_api): "
        f"5m={len(session_state.kline_5m_buffer)}, "
        f"1h={len(session_state.kline_1h_buffer)}, "
        f"agg={len(session_state.agg_features_buffer)}"
    )

    print(
        f"[DEBUG] duplicates: "
        f"k5={_count_duplicate_open_times(session_state.kline_5m_buffer)}, "
        f"closed={_count_duplicate_open_times(session_state.closed_5m_candles)}, "
        f"agg={_count_duplicate_open_times(session_state.agg_features_buffer)}"
    )


def warmup_from_public_data() -> None:
    print("[WARMUP] Using source = public_data")

    day_str = _find_available_day(max_days_back=4)
    print(f"[WARMUP] Using historical date: {day_str}")

    kline_csv, agg_csv = _load_or_download_public_data(day_str)

    k5 = _read_kline_csv(kline_csv)
    k5 = _dedupe_sort_candles(k5, maxlen=288)

    agg_df = _read_aggtrades_csv(agg_csv)
    agg_features = _build_agg_features_from_daily_aggtrades(k5, agg_df)

    k1h = _build_1h_from_5m_records(k5)
    k1h = _dedupe_sort_candles(k1h, maxlen=120)

    session_state.kline_5m_buffer = k5
    session_state.kline_1h_buffer = k1h
    session_state.closed_5m_candles = _dedupe_sort_candles(k5[-100:], maxlen=100)
    session_state.agg_trade_current_bucket = []
    session_state.agg_features_buffer = agg_features[-288:]

    session_state.historical_loaded = True
    session_state.status = "ready"
    session_state.reason = f"historical loaded from public_data ({day_str})"

    print(
        f"[WARMUP] Success (public_data): day={day_str}, "
        f"5m={len(session_state.kline_5m_buffer)}, "
        f"1h={len(session_state.kline_1h_buffer)}, "
        f"agg={len(session_state.agg_features_buffer)}"
    )

    print(
        f"[DEBUG] duplicates: "
        f"k5={_count_duplicate_open_times(session_state.kline_5m_buffer)}, "
        f"closed={_count_duplicate_open_times(session_state.closed_5m_candles)}, "
        f"agg={_count_duplicate_open_times(session_state.agg_features_buffer)}"
    )


def warmup_session(source: str = "public_data") -> None:
    session_state.is_warming_up = True
    session_state.status = "warming_up"
    session_state.reason = f"loading historical data from {source}"
    session_state.historical_source = source

    try:
        if source == "rest_api":
            try:
                print("[WARMUP] Using REST Binance")
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


# ============================================================
# PREDICTION
# ============================================================

def build_signal_payload(
    prob_buy: float,
    prob_sell: float,
    df_5m: pd.DataFrame,
    df_1h: pd.DataFrame,
) -> dict:
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

    action_raw = raw_decision(
        prob_buy,
        prob_sell,
        buy_th,
        sell_th,
        margin=0.02,
    )

    action = filter_action_by_trend(action_raw, trend_1h)

    print(
        f"[DECISION] prob_buy={prob_buy:.4f}, prob_sell={prob_sell:.4f}, "
        f"regime={regime}, buy_th={buy_th:.4f}, sell_th={sell_th:.4f}, "
        f"trend_1h={trend_1h}, raw_action={action_raw}, final_action={action}"
    )

    if action == "BUY":
        size = position_size(prob_buy)
    elif action == "SELL":
        size = position_size(prob_sell)
    else:
        size = 0.0

    sl, tp = get_sl_tp(
        float(row_5m["close"]),
        float(row_5m["atr_14"]),
        action,
    )

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
        "raw_action": action_raw,
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
    df_1h = (
        add_kline_features(df_1h)
        .replace([float("inf"), float("-inf")], 0)
        .fillna(0)
    )

    prob_buy = float(buy_model.predict_proba(X_5m)[0][1])
    prob_sell = float(sell_model.predict_proba(X_5m)[0][1])

    signal = build_signal_payload(prob_buy, prob_sell, df_5m, df_1h)

    session_state.last_prediction = signal
    session_state.last_signal = signal
    session_state.signal_history.append(signal)
    session_state.signal_history = session_state.signal_history[-200:]

    print(
        f"[PREDICT] prob_buy={prob_buy:.4f}, "
        f"prob_sell={prob_sell:.4f}, action={signal['action']}"
    )

    return {"ok": True, "prediction": signal}


# ============================================================
# LIVE WEBSOCKET LOOP WITH AUTO RECONNECT
# ============================================================

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
                session_state.reason = (
                    f"historical loaded + live stream connected "
                    f"({session_state.historical_source})"
                )
                print("[LIVE] Binance websocket connected")

                await broadcast_cb(
                    {
                        "type": "ws_status",
                        "status": "live",
                        "reason": "websocket connected",
                    }
                )

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
                            "trade_time": _to_microseconds(int(data["T"])),
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
                            "open_time": _to_microseconds(int(k["t"])),
                            "open": float(k["o"]),
                            "high": float(k["h"]),
                            "low": float(k["l"]),
                            "close": float(k["c"]),
                            "volume": float(k["v"]),
                            "close_time": _to_microseconds(int(k["T"])),
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
                            last_closed_open_time = (
                                int(session_state.closed_5m_candles[-1]["open_time"])
                                if session_state.closed_5m_candles
                                else None
                            )

                            print(
                                f"[LIVE][CLOSE] incoming open_time={forming['open_time']} "
                                f"last_closed_open_time={last_closed_open_time}"
                            )

                            session_state.kline_5m_buffer, _ = _upsert_candle(
                                session_state.kline_5m_buffer,
                                forming,
                                maxlen=600,
                            )

                            session_state.closed_5m_candles, _ = _upsert_candle(
                                session_state.closed_5m_candles,
                                forming,
                                maxlen=100,
                            )

                            agg_row = build_agg_row(session_state.agg_trade_current_bucket)

                            session_state.agg_features_buffer = _upsert_agg_feature_row(
                                session_state.agg_features_buffer,
                                agg_row,
                                open_time=int(forming["open_time"]),
                                maxlen=600,
                            )

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