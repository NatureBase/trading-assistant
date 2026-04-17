from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any
from pathlib import Path


@dataclass
class TradingSessionState:
    is_active: bool = False
    is_warming_up: bool = False
    status: str = "idle"
    reason: str = "not started"

    historical_source: str = "public_data"

    kline_5m_buffer: list[dict[str, Any]] = field(default_factory=list)
    kline_1h_buffer: list[dict[str, Any]] = field(default_factory=list)
    agg_trade_current_bucket: list[dict[str, Any]] = field(default_factory=list)
    agg_features_buffer: list[dict[str, Any]] = field(default_factory=list)
    closed_5m_candles: list[dict[str, Any]] = field(default_factory=list)

    last_signal: dict[str, Any] | None = None
    last_prediction: dict[str, Any] | None = None
    signal_history: list[dict[str, Any]] = field(default_factory=list)

    historical_loaded: bool = False
    session_temp_dir: Path | None = None
    ws_task: asyncio.Task | None = None

    def reset_runtime_buffers(self) -> None:
        self.kline_5m_buffer.clear()
        self.kline_1h_buffer.clear()
        self.agg_trade_current_bucket.clear()
        self.agg_features_buffer.clear()
        self.closed_5m_candles.clear()
        self.last_signal = None
        self.last_prediction = None
        self.signal_history.clear()
        self.historical_loaded = False
        self.session_temp_dir = None


session_state = TradingSessionState()