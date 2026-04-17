import { useEffect, useRef } from "react";
import {
  CandlestickData,
  ColorType,
  IChartApi,
  ISeriesApi,
  LineStyle,
  Time,
  createChart
} from "lightweight-charts";

type ClosedCandle = {
  open_time: number;
  open: number;
  high: number;
  low: number;
  close: number;
};

type FormingCandle = {
  open_time: number;
  open: number;
  high: number;
  low: number;
  close: number;
};

type SignalMarker = {
  time: number;
  action: "BUY" | "SELL";
  prob_buy: number;
  prob_sell: number;
};

type TradeLevels = {
  entry?: number | null;
  stopLoss?: number | null;
  takeProfit?: number | null;
};

type Props = {
  closedCandles: ClosedCandle[];
  formingCandle?: FormingCandle | null;
  signalMarkers?: SignalMarker[];
  tradeLevels?: TradeLevels;
};

function toChartCandle(c: ClosedCandle | FormingCandle): CandlestickData<Time> {
  return {
    time: Math.floor(c.open_time / 1_000_000) as Time,
    open: c.open,
    high: c.high,
    low: c.low,
    close: c.close
  };
}

export default function LiveCandleChart({
  closedCandles,
  formingCandle,
  signalMarkers = [],
  tradeLevels
}: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const entryLineRef = useRef<ISeriesApi<"Line"> | null>(null);
  const slLineRef = useRef<ISeriesApi<"Line"> | null>(null);
  const tpLineRef = useRef<ISeriesApi<"Line"> | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height: 460,
      layout: {
        background: { type: ColorType.Solid, color: "#0f172a" },
        textColor: "#cbd5e1"
      },
      grid: {
        vertLines: { color: "#1e293b" },
        horzLines: { color: "#1e293b" }
      },
      rightPriceScale: {
        borderColor: "#334155"
      },
      timeScale: {
        borderColor: "#334155",
        timeVisible: true,
        secondsVisible: false
      }
    });

    const candleSeries = chart.addCandlestickSeries({
      upColor: "#22c55e",
      downColor: "#ef4444",
      borderUpColor: "#22c55e",
      borderDownColor: "#ef4444",
      wickUpColor: "#22c55e",
      wickDownColor: "#ef4444"
    });

    const entryLine = chart.addLineSeries({
      color: "#60a5fa",
      lineWidth: 2,
      lineStyle: LineStyle.Solid,
      priceLineVisible: false,
      lastValueVisible: true
    });

    const slLine = chart.addLineSeries({
      color: "#f87171",
      lineWidth: 2,
      lineStyle: LineStyle.Dashed,
      priceLineVisible: false,
      lastValueVisible: true
    });

    const tpLine = chart.addLineSeries({
      color: "#4ade80",
      lineWidth: 2,
      lineStyle: LineStyle.Dashed,
      priceLineVisible: false,
      lastValueVisible: true
    });

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    entryLineRef.current = entryLine;
    slLineRef.current = slLine;
    tpLineRef.current = tpLine;

    const handleResize = () => {
      if (containerRef.current && chartRef.current) {
        chartRef.current.applyOptions({
          width: containerRef.current.clientWidth
        });
      }
    };

    window.addEventListener("resize", handleResize);

    return () => {
      window.removeEventListener("resize", handleResize);
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      entryLineRef.current = null;
      slLineRef.current = null;
      tpLineRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!candleSeriesRef.current) return;

    const sortedClosed = [...closedCandles].sort((a, b) => a.open_time - b.open_time);
    const candleData = sortedClosed.map(toChartCandle);

    if (formingCandle) {
      candleData.push(toChartCandle(formingCandle));
    }

    candleSeriesRef.current.setData(candleData);

    const markers = signalMarkers.map((s) => {
      const time = Math.floor(s.time / 1_000_000) as Time;

      if (s.action === "BUY") {
        return {
          time,
          position: "belowBar" as const,
          color: "#22c55e",
          shape: "arrowUp" as const,
          text: `BUY ${Math.round(s.prob_buy * 100)}%`
        };
      }

      return {
        time,
        position: "aboveBar" as const,
        color: "#ef4444",
        shape: "arrowDown" as const,
        text: `SELL ${Math.round(s.prob_sell * 100)}%`
      };
    });

    candleSeriesRef.current.setMarkers(markers);

    const allCandles = [...sortedClosed];
    if (formingCandle) {
      allCandles.push(formingCandle);
    }

    const lineTimes = allCandles.map((c) => Math.floor(c.open_time / 1_000_000) as Time);

    const makeFlatLine = (price: number | null | undefined) => {
      if (price == null || lineTimes.length === 0) return [];
      return lineTimes.map((t) => ({ time: t, value: price }));
    };

    entryLineRef.current?.setData(makeFlatLine(tradeLevels?.entry ?? null));
    slLineRef.current?.setData(makeFlatLine(tradeLevels?.stopLoss ?? null));
    tpLineRef.current?.setData(makeFlatLine(tradeLevels?.takeProfit ?? null));

    chartRef.current?.timeScale().fitContent();
  }, [closedCandles, formingCandle, signalMarkers, tradeLevels]);

  return <div ref={containerRef} style={{ width: "100%" }} />;
}