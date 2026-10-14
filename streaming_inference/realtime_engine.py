"""
Real-Time Big Data Streaming Inference Engine
Module: streaming_inference/realtime_engine.py

Integrates Kafka consumer, HDFS Lakehouse micro-batch sinking,
sliding-window feature extraction, model inference, and work order triggers.
"""

import time
import threading
from typing import Dict, Any, List, Optional, Callable
from collections import deque

from ingestion.kafka_streamer import KafkaTelemetryConsumer, InProcessKafkaBroker
from storage.hdfs_lakehouse import HDFSLakehouse
from analytics_ml.feature_pipeline import StreamingFeatureBuffer
from analytics_ml.model_trainer import PredictiveMaintenanceTrainer
from streaming_inference.work_order_system import WorkOrderManager

class RealTimeInferenceEngine:
    """
    Continuous streaming processor executing low-latency ML scoring and
    HDFS lakehouse sinking over Kafka telemetry.
    """

    def __init__(self, hdfs_path: str = "lakehouse/turbofan"):
        self.lakehouse = HDFSLakehouse(base_hdfs_path=hdfs_path)
        self.work_order_mgr = WorkOrderManager()
        self.kafka_consumer = KafkaTelemetryConsumer(
            topic="sensor-telemetry-turbofan",
            group_id="realtime-scoring-engine"
        )
        
        # Load or train ML artifacts
        print("[Inference Engine] Loading predictive models...")
        self.pipeline, self.classifier, self.regressor, self.metrics = PredictiveMaintenanceTrainer.load_artifacts()
        self.feature_buffer = StreamingFeatureBuffer(self.pipeline, maxlen=20)
        
        # State tracking for fleet
        self.fleet_state: Dict[int, Dict[str, Any]] = {}
        self.live_telemetry_history: Dict[int, deque] = {}
        self.is_running = False
        self.thread: Optional[threading.Thread] = None
        self.live_callbacks: List[Callable[[Dict[str, Any]], None]] = []
        
        # Micro-batch buffering for HDFS
        self.hdfs_batch_buffer = []
        self.last_hdfs_flush = time.time()
        self.hdfs_flush_interval = 10.0  # seconds

    def register_live_callback(self, callback: Callable[[Dict[str, Any]], None]):
        """Registers a callback for pushing enriched predictions to WebSockets / Dashboard."""
        self.live_callbacks.append(callback)

    def start(self):
        if self.is_running:
            return
        self.is_running = True
        self.thread = threading.Thread(target=self._processing_loop, daemon=True)
        self.thread.start()
        print("[Inference Engine] Real-time streaming inference engine started.")

    def stop(self):
        self.is_running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2.0)
        # Flush remaining HDFS records
        self._flush_hdfs()
        print("[Inference Engine] Stopped.")

    def _processing_loop(self):
        while self.is_running:
            events = self.kafka_consumer.poll_batch(max_records=100)
            if not events:
                time.sleep(0.1)
                continue

            for event in events:
                self._process_single_event(event)

            # Check if HDFS flush interval elapsed
            if time.time() - self.last_hdfs_flush >= self.hdfs_flush_interval or len(self.hdfs_batch_buffer) >= 100:
                self._flush_hdfs()

    def _process_single_event(self, event: Dict[str, Any]):
        engine_id = event["engine_id"]
        cycle = event["cycle"]
        telemetry = event.get("telemetry", {})

        # Extract features from sliding window
        feature_vector, _ = self.feature_buffer.push_and_extract(event)

        # Execute Model Inference
        failure_proba = float(self.classifier.predict_proba(feature_vector)[0, 1])
        predicted_rul = float(max(0.0, self.regressor.predict(feature_vector)[0]))

        # Health tier classification
        if failure_proba >= 0.70 or predicted_rul <= 24:
            health_status = "CRITICAL"
        elif failure_proba >= 0.40 or predicted_rul <= 50:
            health_status = "WARNING"
        else:
            health_status = "HEALTHY"

        # Evaluate automated work order trigger
        triggered_wo = self.work_order_mgr.evaluate_and_trigger(
            engine_id=engine_id,
            cycle=cycle,
            failure_prob=failure_proba,
            predicted_rul=predicted_rul,
            telemetry=telemetry
        )

        # Enriched prediction payload
        enriched = {
            "engine_id": engine_id,
            "cycle": cycle,
            "timestamp": event.get("timestamp", time.time()),
            "failure_probability_24h": round(failure_proba, 4),
            "predicted_rul_hours": round(predicted_rul, 1),
            "health_status": health_status,
            "work_order_triggered": bool(triggered_wo),
            "active_work_order_id": triggered_wo.get("work_order_id") if triggered_wo else None,
            "key_sensors": {
                "T30_HPC_temp": round(telemetry.get("sensor_3", 0.0), 2),
                "P30_pressure": round(telemetry.get("sensor_7", 0.0), 2),
                "Nc_core_speed": round(telemetry.get("sensor_9", 0.0), 2),
                "BPR_bypass": round(telemetry.get("sensor_15", 0.0), 4),
                "ht_enthalpy": round(telemetry.get("sensor_17", 0.0), 2),
            }
        }

        # Update live fleet state
        self.fleet_state[engine_id] = enriched
        if engine_id not in self.live_telemetry_history:
            self.live_telemetry_history[engine_id] = deque(maxlen=60)
        self.live_telemetry_history[engine_id].append(enriched)

        # Buffer for HDFS persistence
        self.hdfs_batch_buffer.append(event)

        # Notify active web dashboard listeners
        for cb in self.live_callbacks:
            try:
                cb(enriched)
            except Exception as e:
                print(f"[Inference Engine] Listener notification error: {e}")

    def _flush_hdfs(self):
        if not self.hdfs_batch_buffer:
            return
        batch_to_write = list(self.hdfs_batch_buffer)
        self.hdfs_batch_buffer.clear()
        self.last_hdfs_flush = time.time()
        self.lakehouse.write_stream_microbatch(batch_to_write)

    def get_fleet_summary(self) -> Dict[str, Any]:
        """Provides a real-time status summary of all monitored fleet engines."""
        fleet_list = list(self.fleet_state.values())
        critical_count = sum(1 for e in fleet_list if e["health_status"] == "CRITICAL")
        warning_count = sum(1 for e in fleet_list if e["health_status"] == "WARNING")
        healthy_count = sum(1 for e in fleet_list if e["health_status"] == "HEALTHY")

        return {
            "total_engines_monitored": len(fleet_list),
            "critical_engines": critical_count,
            "warning_engines": warning_count,
            "healthy_engines": healthy_count,
            "fleet": sorted(fleet_list, key=lambda x: x["engine_id"]),
            "hdfs_status": self.lakehouse.get_cluster_status(),
            "kafka_metrics": InProcessKafkaBroker().get_metrics(),
            "model_metrics": self.metrics
        }

if __name__ == "__main__":
    engine = RealTimeInferenceEngine()
    engine.start()
    time.sleep(2)
    print("Fleet summary:", engine.get_fleet_summary())
    engine.stop()
