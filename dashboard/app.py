"""
Predictive Maintenance Big Data Alert Dashboard & API Server
Module: dashboard/app.py

FastAPI application providing:
- Real-time WebSocket streaming telemetry & risk scores
- Industrial Fleet Health Monitoring REST APIs
- Automated Work Order dispatch & lifecycle management
- Hadoop HDFS Lakehouse cluster telemetry & compaction controls
"""

import os
import asyncio
import json
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from ingestion.sensor_producer import SensorTelemetryStreamer
from streaming_inference.realtime_engine import RealTimeInferenceEngine
from streaming_inference.work_order_system import WorkOrderManager
from storage.hdfs_lakehouse import HDFSLakehouse

app = FastAPI(
    title="AERO-CORE PREDICX // Industrial Turbofan Predictive Maintenance",
    version="2.0.0"
)

# Base Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
os.makedirs(STATIC_DIR, exist_ok=True)

# Mount static files
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Shared Subsystems
streamer = SensorTelemetryStreamer(data_path="data")
inference_engine = RealTimeInferenceEngine(hdfs_path="lakehouse/turbofan")
work_order_mgr = inference_engine.work_order_mgr
lakehouse = inference_engine.lakehouse

# WebSocket Connection Manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: Dict[str, Any]):
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception:
                self.disconnect(connection)

ws_manager = ConnectionManager()
loop = None

def on_realtime_prediction(enriched_event: Dict[str, Any]):
    """Callback invoked by the streaming inference engine upon scoring each cycle."""
    global loop
    if loop and loop.is_running() and ws_manager.active_connections:
        asyncio.run_coroutine_threadsafe(
            ws_manager.broadcast({
                "type": "TELEMETRY_UPDATE",
                "data": enriched_event
            }),
            loop
        )

inference_engine.register_live_callback(on_realtime_prediction)


@app.on_event("startup")
async def startup_event():
    global loop
    loop = asyncio.get_running_loop()
    print("[Dashboard API] Starting real-time streaming engines...")
    inference_engine.start()
    # Stream test engines #1, #2, #3, #4, #5
    streamer.start_streaming(engine_ids=[1, 2, 3, 4, 5], speed_sec=0.6)


@app.on_event("shutdown")
def shutdown_event():
    streamer.stop_streaming()
    inference_engine.stop()


# ---------------- REST ENDPOINTS ----------------

@app.get("/")
def get_dashboard_ui():
    index_file = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return JSONResponse({"status": "Dashboard UI compiling... refresh in 5 seconds."})


@app.get("/api/fleet")
def get_fleet_status():
    """Returns overview of all engines in the monitored industrial fleet."""
    summary = inference_engine.get_fleet_summary()
    summary["active_work_orders_count"] = len(
        [wo for wo in work_order_mgr.get_all_work_orders() if wo["status"] in ["OPEN", "IN_PROGRESS"]]
    )
    return summary


@app.get("/api/fleet/{engine_id}/history")
def get_engine_history(engine_id: int):
    """Returns sliding window historical telemetry for detailed stripcharts."""
    history = list(inference_engine.live_telemetry_history.get(engine_id, []))
    return {
        "engine_id": engine_id,
        "sample_count": len(history),
        "history": history
    }


@app.get("/api/work-orders")
def get_work_orders():
    """Returns all automated maintenance work orders."""
    return work_order_mgr.get_all_work_orders()


class StatusUpdateReq(BaseModel):
    status: str
    technician: Optional[str] = None

@app.post("/api/work-orders/{wo_id}/status")
def update_work_order_status(wo_id: str, req: StatusUpdateReq):
    success = work_order_mgr.update_status(wo_id, req.status, req.technician)
    if not success:
        raise HTTPException(status_code=404, detail="Work Order not found")
    return {"status": "SUCCESS", "work_order_id": wo_id, "new_status": req.status}


@app.get("/api/hdfs/status")
def get_hdfs_status():
    """Returns Hadoop HDFS NameNode, DataNodes, and storage telemetry."""
    return lakehouse.get_cluster_status()


@app.post("/api/hdfs/compact")
def trigger_parquet_compaction():
    """Triggers batch compaction of raw streaming logs into Parquet format."""
    target_parquet = lakehouse.compact_to_parquet()
    return {
        "status": "COMPACTION_COMPLETE",
        "target_file": target_parquet,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


class StreamControlReq(BaseModel):
    action: str  # "start" or "stop"
    speed_sec: Optional[float] = 0.5
    engine_ids: Optional[List[int]] = None

@app.post("/api/stream/control")
def control_streaming(req: StreamControlReq):
    if req.action.lower() == "start":
        streamer.start_streaming(engine_ids=req.engine_ids, speed_sec=req.speed_sec or 0.5)
    elif req.action.lower() == "stop":
        streamer.stop_streaming()
    return streamer.get_status()


class FaultInjectionReq(BaseModel):
    engine_id: int = 1

@app.post("/api/stream/inject-fault")
def inject_fault_anomaly(req: FaultInjectionReq):
    """
    Simulates sudden high-thermal blade wear degradation on an engine,
    instantly elevating risk and validating automated work order generation.
    """
    engine_id = req.engine_id
    anomaly_event = {
        "engine_id": engine_id,
        "cycle": 185,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "settings": {"setting_1": 0.002, "setting_2": 0.0001, "setting_3": 100.0},
        "telemetry": {
            "sensor_1": 518.67,
            "sensor_2": 645.8,   # High LPC temp
            "sensor_3": 1612.4,  # Critical HPC temp spike!
            "sensor_4": 1428.0,  # Critical LPT temp
            "sensor_5": 14.62,
            "sensor_6": 21.61,
            "sensor_7": 549.5,   # Critical pressure drop!
            "sensor_8": 2387.8,
            "sensor_9": 9028.0,  # Severe core speed drop
            "sensor_10": 1.30,
            "sensor_11": 48.6,   # Critical static pressure rise
            "sensor_12": 519.0,
            "sensor_13": 2387.8,
            "sensor_14": 8105.0,
            "sensor_15": 8.58,   # High bypass ratio
            "sensor_16": 0.03,
            "sensor_17": 398.0,  # Elevated bleed enthalpy
            "sensor_18": 2388.0,
            "sensor_19": 100.0,
            "sensor_20": 38.1,
            "sensor_21": 22.8
        },
        "ground_truth_rul": 4.0,
        "ground_truth_failure_within_24h": 1
    }
    # Send to Kafka producer and immediately process in inference engine
    streamer.producer.send_telemetry(anomaly_event, key=str(engine_id))
    inference_engine._process_single_event(anomaly_event)

    return {
        "status": "FAULT_INJECTED",
        "engine_id": engine_id,
        "message": f"Critical thermal blade wear signature injected for Engine #{engine_id}. Work Order triggered immediately."
    }


# ---------------- WEBSOCKET ENDPOINT ----------------

@app.websocket("/ws/telemetry")
async def websocket_telemetry_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        # Send initial fleet state immediately upon connection
        fleet_data = inference_engine.get_fleet_summary()
        await websocket.send_json({
            "type": "INITIAL_STATE",
            "data": fleet_data
        })
        while True:
            # Keep socket alive and receive client commands (e.g. ping)
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception:
        ws_manager.disconnect(websocket)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=False)
