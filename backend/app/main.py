from __future__ import annotations

import asyncio

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .live_engine import (
    run_live_loop,
    run_manual_prediction,
    warmup_session,
)
from .session_manager import session_state

app = FastAPI(title="On-Demand BTCUSDT Trading Assistant")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

clients: set[WebSocket] = set()

class StartSessionRequest(BaseModel):
    source: str = "public_data"

async def broadcast(payload):
    dead = []
    for ws in clients:
        try:
            await ws.send_json(payload)
        except Exception:
            dead.append(ws)

    for ws in dead:
        clients.discard(ws)


@app.get("/api/session/status")
def session_status():
    return {
        "is_active": session_state.is_active,
        "is_warming_up": session_state.is_warming_up,
        "historical_loaded": session_state.historical_loaded,
        "status": session_state.status,
        "reason": session_state.reason,
        "last_signal": session_state.last_signal,
        "last_prediction": session_state.last_prediction,
        "signal_history": session_state.signal_history[-50:],
        "closed_5m_candles": session_state.closed_5m_candles[-100:],
        "kline_5m_count": len(session_state.kline_5m_buffer),
        "kline_1h_count": len(session_state.kline_1h_buffer),
        "historical_source": session_state.historical_source,
    }


@app.post("/api/session/start")
async def start_session(payload: StartSessionRequest):
    if session_state.is_active:
        return {"ok": True, "message": "session already active"}

    session_state.reset_runtime_buffers()
    session_state.is_active = True

    warmup_session(payload.source)
    session_state.ws_task = asyncio.create_task(run_live_loop(broadcast))

    return {
        "ok": True,
        "message": "session started",
        "source": payload.source,
    }


@app.post("/api/predict")
async def predict_now():
    return run_manual_prediction()


@app.post("/api/session/stop")
async def stop_session():
    session_state.is_active = False
    session_state.status = "stopped"
    session_state.reason = "stopped by user"

    if session_state.ws_task and not session_state.ws_task.done():
        session_state.ws_task.cancel()

    session_state.reset_runtime_buffers()

    return {"ok": True, "message": "session stopped"}


@app.websocket("/ws/live")
async def ws_live(ws: WebSocket):
    await ws.accept()
    clients.add(ws)

    try:
        await ws.send_json(
            {
                "type": "session_state",
                "is_active": session_state.is_active,
                "status": session_state.status,
                "reason": session_state.reason,
                "last_signal": session_state.last_signal,
            }
        )

        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        clients.discard(ws)
    except Exception:
        clients.discard(ws)