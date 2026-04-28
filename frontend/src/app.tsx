import { useEffect, useMemo, useRef, useState } from "react";
import LiveCandleChart from "./components/LiveCandleChart";

const API_BASE = "http://localhost:8000";
const WS_URL = "ws://localhost:8000/ws/live";

type ClosedCandle = {
  open_time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  close_time: number;
  quote_asset_volume: number;
  num_trades: number;
  taker_buy_base: number;
  taker_buy_quote: number;
};

type SessionStatusResponse = {
  is_active: boolean;
  is_warming_up: boolean;
  historical_loaded: boolean;
  status: string;
  reason: string;
  last_signal: SignalPayload | null;
  signal_history: SignalPayload[];
  closed_5m_candles: ClosedCandle[];
};

type SignalPayload = {
  time: number;
  close_price: number;
  prob_buy: number;
  prob_sell: number;
  regime: string;
  trend_1h: string;
  buy_threshold: number;
  sell_threshold: number;
  action: "BUY" | "SELL" | "HOLD";
  position_size: number;
  stop_loss: number;
  take_profit: number;
};


type FormingKline = {
  open_time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  close_time: number;
  quote_asset_volume: number;
  num_trades: number;
  taker_buy_base: number;
  taker_buy_quote: number;
};

type TradeRow = {
  price: number;
  qty: number;
  side: "BUY" | "SELL";
  trade_time: number;
};

type DisplaySettings = {
  showChart: boolean;
  showSignalMarkers: boolean;
  showEntryLine: boolean;
  showStopLossLine: boolean;
  showTakeProfitLine: boolean;
  showRecentTrades: boolean;
  showProbabilities: boolean;
  showMarketContext: boolean;
  showSignalHistory: boolean;
  showFormingCandle: boolean;
  showReasonPanel: boolean;
};

const defaultSettings: DisplaySettings = {
  showChart: true,
  showSignalMarkers: true,
  showEntryLine: true,
  showStopLossLine: true,
  showTakeProfitLine: true,
  showRecentTrades: true,
  showProbabilities: true,
  showMarketContext: true,
  showSignalHistory: true,
  showFormingCandle: true,
  showReasonPanel: true
};

const SETTINGS_KEY = "trading-assistant-display-settings";

function pct(x: number | null | undefined): string {
  if (x == null || Number.isNaN(x)) return "-";
  return `${(x * 100).toFixed(2)}%`;
}

function fmtPrice(x: number | null | undefined): string {
  if (x == null || Number.isNaN(x)) return "-";
  return x.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function normalizeEpochToMs(value: number): number {
  // seconds
  if (value < 1e11) return value * 1000;

  // milliseconds
  if (value < 1e14) return value;

  // microseconds
  if (value < 1e17) return Math.floor(value / 1000);

  // nanoseconds
  return Math.floor(value / 1_000_000);
}

function fmtTime(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "-";
  return new Date(normalizeEpochToMs(value)).toLocaleString();
}

export default function App() {
  const [session, setSession] = useState<SessionStatusResponse | null>(null);
  const [lastSignal, setLastSignal] = useState<SignalPayload | null>(null);
  const [signalHistory, setSignalHistory] = useState<SignalPayload[]>([]);
  const [formingKline, setFormingKline] = useState<FormingKline | null>(null);
  const [recentTrades, setRecentTrades] = useState<TradeRow[]>([]);
  const [connected, setConnected] = useState(false);
  const [closedCandles, setClosedCandles] = useState<ClosedCandle[]>([]);
  const [starting, setStarting] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [predicting, setPredicting] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [historicalSource, setHistoricalSource] = useState<"rest_api" | "public_data">("public_data");
  const [settings, setSettings] = useState<DisplaySettings>(() => {
    const raw = localStorage.getItem(SETTINGS_KEY);
    if (!raw) return defaultSettings;

    try {
      return { ...defaultSettings, ...JSON.parse(raw) };
    } catch {
      return defaultSettings;
    }
  });

  const wsRef = useRef<WebSocket | null>(null);
  const keepAliveRef = useRef<number | null>(null);

  useEffect(() => {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
  }, [settings]);

  // const predictNow = async () => {
  //   const res = await fetch(`${API_BASE}/api/predict`, { method: "POST" });
  //   const data = await res.json();
  //   console.log("[PREDICT]", data);

  //   if (data.ok && data.prediction) {
  //     setLastSignal(data.prediction);
  //     setSignalHistory((prev) => [data.prediction, ...prev].slice(0, 100));
  //   } else {
  //     alert(data.message ?? "Prediction failed");
  //   }
  // };

  const fetchStatus = async () => {
    const res = await fetch(`${API_BASE}/api/session/status`);
    if (!res.ok) {
      throw new Error(`Failed to fetch status: ${res.status}`);
    }

    const data: SessionStatusResponse = await res.json();
    setSession(data);
    setLastSignal(data.last_signal);
    setSignalHistory(data.signal_history ?? []);
    setClosedCandles(data.closed_5m_candles ?? []);
  };

  const startSession = async () => {
    const res = await fetch(`${API_BASE}/api/session/start`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        source: historicalSource,
      }),
    });

    if (!res.ok) {
      throw new Error(`Failed to start session: ${res.status}`);
    }

    setClosedCandles([]);
    setSignalHistory([]);
    setLastSignal(null);
    setFormingKline(null);
    setRecentTrades([]);

    await fetchStatus();
  };

  const stopSession = async () => {
    try {
      setStopping(true);
      const res = await fetch(`${API_BASE}/api/session/stop`, { method: "POST" });
      if (!res.ok) {
        throw new Error(`Failed to stop session: ${res.status}`);
      }
      await fetchStatus();
    } finally {
      setStopping(false);
    }
  };

  const predictNow = async () => {
    try {
      setPredicting(true);
      const res = await fetch(`${API_BASE}/api/predict`, { method: "POST" });
      const data = await res.json();
      console.log("[PREDICT]", data);

      if (data.ok && data.prediction) {
        setLastSignal(data.prediction);
        setSignalHistory((prev) => [data.prediction, ...prev].slice(0, 100));
      } else {
        alert(data.message ?? "Prediction failed");
      }
    } finally {
      setPredicting(false);
    }
  };

  const refreshStatus = async () => {
    try {
      setRefreshing(true);
      await fetchStatus();
    } finally {
      setRefreshing(false);
    }
  };

  function toggleSetting(key: keyof DisplaySettings) {
    setSettings((prev) => ({
      ...prev,
      [key]: !prev[key]
    }));
  }

  function applyPreset(preset: "minimal" | "standard" | "full") {
    if (preset === "minimal") {
      setSettings({
        showChart: true,
        showSignalMarkers: true,
        showEntryLine: false,
        showStopLossLine: false,
        showTakeProfitLine: false,
        showRecentTrades: false,
        showProbabilities: true,
        showMarketContext: true,
        showSignalHistory: false,
        showFormingCandle: false,
        showReasonPanel: false
      });
      return;
    }

    if (preset === "standard") {
      setSettings({
        showChart: true,
        showSignalMarkers: true,
        showEntryLine: true,
        showStopLossLine: true,
        showTakeProfitLine: true,
        showRecentTrades: true,
        showProbabilities: true,
        showMarketContext: true,
        showSignalHistory: true,
        showFormingCandle: true,
        showReasonPanel: false
      });
      return;
    }

    setSettings(defaultSettings);
  }

  useEffect(() => {
    fetchStatus().catch(console.error);

    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen = () => {
      setConnected(true);
      ws.send("ping");
      keepAliveRef.current = window.setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send("ping");
        }
      }, 15000);
    };

    ws.onclose = () => {
      setConnected(false);
      if (keepAliveRef.current) {
        clearInterval(keepAliveRef.current);
      }
      keepAliveRef.current = null;
    };

    ws.onerror = () => {
      setConnected(false);
    };

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      console.log("[WS] message received:", data);

      if (data.type === "session_state") {
        console.log("[WS] session_state");
        setSession((prev) => ({
          is_active: data.is_active,
          is_warming_up: data.is_warming_up ?? false,
          historical_loaded: data.historical_loaded ?? prev?.historical_loaded ?? false,
          status: data.status,
          reason: data.reason,
          last_signal: data.last_signal,
          signal_history: prev?.signal_history ?? [],
          closed_5m_candles: data.closed_5m_candles ?? prev?.closed_5m_candles ?? []
        }));
        setLastSignal(data.last_signal);
        return;
      }
    
      if (data.type === "agg_trade") {
        console.log("[WS] agg_trade");
        const row: TradeRow = {
          price: data.price,
          qty: data.qty,
          side: data.is_buyer_maker ? "SELL" : "BUY",
          trade_time: data.trade_time
        };
      
        setRecentTrades((prev) => [row, ...prev].slice(0, 80));
        return;
      }
    
      if (data.type === "forming_kline") {
        console.log("[WS] forming_kline", data.kline);
        setFormingKline(data.kline);
        return;
      }
    
      if (data.type === "warmup_progress") {
        console.log("[WS] warmup_progress", data);
        return;
      }

      if (data.type === "closed_kline") {
        console.log("[WS] closed_kline", data);
        if (data.closed_kline) {
          setClosedCandles((prev) => [...prev, data.closed_kline].slice(-100));
        }
        return;
      }
    
      if (data.type === "signal") {
        console.log("[WS] signal", data.signal);
        setLastSignal(data.signal);
        setSignalHistory((prev) => [data.signal, ...prev].slice(0, 100));
      
        if (data.closed_kline) {
          setClosedCandles((prev) => [...prev, data.closed_kline].slice(-100));
        }
      
        setSession((prev) =>
          prev
            ? {
                ...prev,
                last_signal: data.signal,
                signal_history: [data.signal, ...(prev.signal_history ?? [])].slice(0, 100)
              }
            : prev
        );
      }
    };    

    return () => {
      if (keepAliveRef.current) {
        clearInterval(keepAliveRef.current);
      }
      keepAliveRef.current = null;
      ws.close();
    };
  }, []);

  const statusLabel = session?.status ?? "loading";

  const statusClass = !session
    ? "badge neutral"
    : session.status === "live"
      ? "badge green"
      : session.status === "warming_up"
        ? "badge yellow"
        : session.status === "ready"
          ? "badge blue"
          : session.status === "stopped"
            ? "badge red"
            : "badge neutral";

  const actionClass =
    lastSignal?.action === "BUY"
      ? "text-buy"
      : lastSignal?.action === "SELL"
        ? "text-sell"
        : "text-hold";

  const chartMarkers = useMemo(() => {
    return signalHistory
      .filter((s) => s.action !== "HOLD")
      .slice(0, 30)
      .reverse()
      .map((s) => ({
        time: s.time,
        action: s.action as "BUY" | "SELL",
        prob_buy: s.prob_buy,
        prob_sell: s.prob_sell
      }));
  }, [signalHistory]);

  const tradeLevels = useMemo(() => {
    if (!lastSignal || lastSignal.action === "HOLD") {
      return {
        entry: null,
        stopLoss: null,
        takeProfit: null
      };
    }

    return {
      entry: lastSignal.close_price,
      stopLoss: lastSignal.stop_loss,
      takeProfit: lastSignal.take_profit
    };
  }, [lastSignal]);

  return (
    <div className="page">
      <header className="hero">
        <div>
          <h1>BTCUSDT Trading Assistant</h1>
          <p>Session-based live decision support for discretionary trading</p>
        </div>

        <div className="hero-right">
          <div className={statusClass}>{statusLabel}</div>
          <div className={connected ? "badge green" : "badge red"}>
            {connected ? "ws connected" : "ws disconnected"}
          </div>
        </div>
      </header>

      <div style={{ display: "flex", gap: 12, alignItems: "center", marginBottom: 12 }}>
        <label>Historical Source:</label>
        <select
          value={historicalSource}
          onChange={(e) => setHistoricalSource(e.target.value as "rest_api" | "public_data")}
        >
          <option value="public_data">Binance Public Data</option>
          <option value="rest_api">Binance REST API</option>
        </select>
      </div>

      <section className="toolbar">
        <button
          className="btn btn-start"
          onClick={() => startSession().catch(console.error)}
          disabled={starting || stopping || predicting}
        >
          {starting ? "Starting..." : "Start Session"}
        </button>

        <button
          className="btn btn-stop"
          onClick={() => stopSession().catch(console.error)}
          disabled={stopping || starting}
        >
          {stopping ? "Stopping..." : "Stop Session"}
        </button>

        <button
          className="btn btn-secondary"
          onClick={() => predictNow().catch(console.error)}
          disabled={predicting || !session?.is_active}
        >
          {predicting ? "Predicting..." : "Predict"}
        </button>

        <button
          className="btn btn-secondary"
          onClick={() => refreshStatus().catch(console.error)}
          disabled={refreshing}
        >
          {refreshing ? "Refreshing..." : "Refresh Status"}
        </button>
      </section>

      <section className="grid grid-4">
        <Card title="Session Status">
          <KV label="Active" value={String(session?.is_active ?? false)} />
          <KV label="Warming Up" value={String(session?.is_warming_up ?? false)} />
          <KV label="Status" value={session?.status ?? "-"} />
          <KV label="Reason" value={session?.reason ?? "-"} />
        </Card>

        <Card title="Last Signal Action">
          <div className={`big-value ${actionClass}`}>{lastSignal?.action ?? "-"}</div>
          <KV label="Signal Time" value={fmtTime(lastSignal?.time)} />
          <KV label="Close Price" value={fmtPrice(lastSignal?.close_price)} />
        </Card>

        {settings.showProbabilities && (
          <Card title="Probabilities">
            <KV label="Buy Prob" value={pct(lastSignal?.prob_buy)} />
            <KV label="Sell Prob" value={pct(lastSignal?.prob_sell)} />
            <KV label="Buy Threshold" value={pct(lastSignal?.buy_threshold)} />
            <KV label="Sell Threshold" value={pct(lastSignal?.sell_threshold)} />
          </Card>
        )}

        <Card title="Position Suggestion">
          <KV label="Suggested Size" value={String(lastSignal?.position_size ?? 0)} />
          <KV label="Stop Loss" value={fmtPrice(lastSignal?.stop_loss)} />
          <KV label="Take Profit" value={fmtPrice(lastSignal?.take_profit)} />
        </Card>
      </section>

      <section className="grid grid-2">
        <Card title="Display Settings">
          <div className="preset-row">
            <button onClick={() => applyPreset("minimal")}>Minimal</button>
            <button onClick={() => applyPreset("standard")}>Standard</button>
            <button onClick={() => applyPreset("full")}>Full</button>
          </div>

          <div className="toggle-list">
            <label>
              <input
                type="checkbox"
                checked={settings.showChart}
                onChange={() => toggleSetting("showChart")}
              />
              Show Chart
            </label>

            <label>
              <input
                type="checkbox"
                checked={settings.showSignalMarkers}
                onChange={() => toggleSetting("showSignalMarkers")}
              />
              Show Signal Markers
            </label>

            <label>
              <input
                type="checkbox"
                checked={settings.showEntryLine}
                onChange={() => toggleSetting("showEntryLine")}
              />
              Show Entry Line
            </label>

            <label>
              <input
                type="checkbox"
                checked={settings.showStopLossLine}
                onChange={() => toggleSetting("showStopLossLine")}
              />
              Show Stop Loss Line
            </label>

            <label>
              <input
                type="checkbox"
                checked={settings.showTakeProfitLine}
                onChange={() => toggleSetting("showTakeProfitLine")}
              />
              Show Take Profit Line
            </label>

            <label>
              <input
                type="checkbox"
                checked={settings.showRecentTrades}
                onChange={() => toggleSetting("showRecentTrades")}
              />
              Show Recent Trades
            </label>

            <label>
              <input
                type="checkbox"
                checked={settings.showProbabilities}
                onChange={() => toggleSetting("showProbabilities")}
              />
              Show Probabilities
            </label>

            <label>
              <input
                type="checkbox"
                checked={settings.showMarketContext}
                onChange={() => toggleSetting("showMarketContext")}
              />
              Show Market Context
            </label>

            <label>
              <input
                type="checkbox"
                checked={settings.showSignalHistory}
                onChange={() => toggleSetting("showSignalHistory")}
              />
              Show Signal History
            </label>

            <label>
              <input
                type="checkbox"
                checked={settings.showFormingCandle}
                onChange={() => toggleSetting("showFormingCandle")}
              />
              Show Forming Candle
            </label>

            <label>
              <input
                type="checkbox"
                checked={settings.showReasonPanel}
                onChange={() => toggleSetting("showReasonPanel")}
              />
              Show Reason Panel
            </label>
          </div>
        </Card>

        {settings.showMarketContext && (
          <Card title="Market Context">
            <KV label="Regime" value={lastSignal?.regime ?? "-"} />
            <KV label="Trend 1H" value={lastSignal?.trend_1h ?? "-"} />
            <KV label="Decision" value={lastSignal?.action ?? "-"} />
            <KV label="Buy Prob" value={pct(lastSignal?.prob_buy)} />
            <KV label="Sell Prob" value={pct(lastSignal?.prob_sell)} />
            <KV label="Stop Loss" value={fmtPrice(lastSignal?.stop_loss)} />
            <KV label="Take Profit" value={fmtPrice(lastSignal?.take_profit)} />
          </Card>
        )}
      </section>

      {settings.showChart && (
        <section className="grid grid-chart">
          <Card title="BTCUSDT Live 5m Candlestick">
            <LiveCandleChart
              closedCandles={closedCandles}
              formingCandle={formingKline}
              signalMarkers={settings.showSignalMarkers ? chartMarkers : []}
              tradeLevels={{
                entry: settings.showEntryLine ? tradeLevels.entry : null,
                stopLoss: settings.showStopLossLine ? tradeLevels.stopLoss : null,
                takeProfit: settings.showTakeProfitLine ? tradeLevels.takeProfit : null
              }}
            />

            <div className="chart-legend">
              <div>
                <span className="legend-line entry-line" /> Entry
              </div>
              <div>
                <span className="legend-line sl-line" /> Stop Loss
              </div>
              <div>
                <span className="legend-line tp-line" /> Take Profit
              </div>
            </div>
          </Card>
        </section>
      )}

      <section className="grid grid-2">
        {settings.showRecentTrades && (
          <Card title="Recent Live Trades">
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Time</th>
                    <th>Price</th>
                    <th>Qty</th>
                    <th>Side</th>
                  </tr>
                </thead>
                <tbody>
                  {recentTrades.map((t, i) => (
                    <tr key={`${t.trade_time}-${i}`}>
                      <td>{fmtTime(t.trade_time)}</td>
                      <td>{fmtPrice(t.price)}</td>
                      <td>{t.qty.toFixed(6)}</td>
                      <td className={t.side === "BUY" ? "text-buy" : "text-sell"}>
                        {t.side}
                      </td>
                    </tr>
                  ))}

                  {recentTrades.length === 0 && (
                    <tr>
                      <td colSpan={4} className="empty-cell">
                        Waiting for live trades...
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </Card>
        )}

        {settings.showSignalHistory && (
          <Card title="Signal History">
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Time</th>
                    <th>Action</th>
                    <th>Buy</th>
                    <th>Sell</th>
                    <th>Regime</th>
                    <th>Trend</th>
                  </tr>
                </thead>
                <tbody>
                  {signalHistory.map((s, i) => (
                    <tr key={`${s.time}-${i}`}>
                      <td>{fmtTime(s.time)}</td>
                      <td
                        className={
                          s.action === "BUY"
                            ? "text-buy"
                            : s.action === "SELL"
                              ? "text-sell"
                              : "text-hold"
                        }
                      >
                        {s.action}
                      </td>
                      <td>{pct(s.prob_buy)}</td>
                      <td>{pct(s.prob_sell)}</td>
                      <td>{s.regime}</td>
                      <td>{s.trend_1h}</td>
                    </tr>
                  ))}

                  {signalHistory.length === 0 && (
                    <tr>
                      <td colSpan={6} className="empty-cell">
                        No signals yet.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </Card>
        )}
      </section>

      <section className="grid grid-2">
        {settings.showFormingCandle && (
          <Card title="Forming 5m Candle">
            <KV label="Open Time" value={fmtTime(formingKline?.open_time)} />
            <KV label="Close Time" value={fmtTime(formingKline?.close_time)} />
            <KV label="Open" value={fmtPrice(formingKline?.open)} />
            <KV label="High" value={fmtPrice(formingKline?.high)} />
            <KV label="Low" value={fmtPrice(formingKline?.low)} />
            <KV label="Close" value={fmtPrice(formingKline?.close)} />
            <KV label="Volume" value={formingKline?.volume?.toFixed(4) ?? "-"} />
            <KV label="Trades" value={formingKline?.num_trades?.toString() ?? "-"} />
          </Card>
        )}

        {settings.showReasonPanel && (
          <Card title="How to Read">
            <p className="helper-text">
              BUY atau SELL di sini adalah rekomendasi model, bukan eksekusi otomatis.
              Gunakan sebagai bantuan keputusan bersama chart, trend 1H, dan manajemen
              risiko Anda.
            </p>
          </Card>
        )}
      </section>
    </div>
  );
}

function Card({
  title,
  children
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="card">
      <div className="card-title">{title}</div>
      <div>{children}</div>
    </div>
  );
}

function KV({ label, value }: { label: string; value: string }) {
  return (
    <div className="kv-row">
      <span className="kv-label">{label}</span>
      <strong className="kv-value">{value}</strong>
    </div>
  );
}