from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.database import init_db
from app.simulator import simulator

init_db()


@asynccontextmanager
async def lifespan(_: FastAPI):
    simulator.start()
    yield


app = FastAPI(
    title="CANScope — Automotive Network Intelligence & Diagnostics Platform",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "service": "CANScope", "uptime_seconds": 0}


@app.get("/api/ecus")
def list_ecus() -> list[dict[str, Any]]:
    return [
        {"ecu_id": ecu.ecu_id, "name": ecu.name, "can_id": ecu.can_id, "interval_ms": ecu.interval_ms, "enabled": ecu.enabled}
        for ecu in simulator.ecus.values()
    ]


@app.get("/api/dashboard")
def dashboard() -> dict[str, Any]:
    return simulator.get_dashboard_snapshot()


@app.get("/api/traffic")
def traffic() -> dict[str, Any]:
    return {"frames": simulator.frames[-25:], "anomalies": simulator.anomalies[-10:]}


@app.post("/api/ecus/{ecu_id}/toggle")
def toggle_ecu(ecu_id: str) -> dict[str, Any]:
    try:
        return simulator.toggle_ecu(ecu_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/faults/inject")
def inject_fault(ecu_id: str, fault_kind: str = "drop") -> dict[str, Any]:
    try:
        return simulator.inject_fault(ecu_id, fault_kind=fault_kind)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.websocket("/ws/traffic")
async def websocket_traffic(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        while True:
            await websocket.send_json(simulator.get_dashboard_snapshot())
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        return


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
