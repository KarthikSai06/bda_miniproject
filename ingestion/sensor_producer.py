"""
Real-Time Turbofan Sensor Telemetry Producer
Module: ingestion/sensor_producer.py

Simulates real-time multi-engine industrial fleet telemetry streaming
into Apache Kafka topic 'sensor-telemetry-turbofan'.
"""

import time
import threading
from datetime import datetime, timezone
from typing import Optional
import pandas as pd
from data.c_mapss_loader import get_or_create_cmapss_data
from ingestion.kafka_streamer import KafkaTelemetryProducer

class SensorTelemetryStreamer:
    """
    Continuous background streaming simulator for industrial turbofan engines.
    """
    def __init__(self, data_path: str = "data", topic: str = "sensor-telemetry-turbofan"):
        self.data_path = data_path
        self.topic = topic
        self.producer = KafkaTelemetryProducer(topic=self.topic)
        self.is_running = False
        self.thread: Optional[threading.Thread] = None
        self.stream_speed_sec = 0.5  # Seconds per cycle emission
        self.current_cycle_by_engine = {}
        self.total_emitted = 0

        # Load test engines for streaming
        _, test_df = get_or_create_cmapss_data(self.data_path)
        self.stream_data = test_df

    def start_streaming(self, engine_ids: list[int] = None, speed_sec: float = 0.5):
        """Starts asynchronous background streaming."""
        if self.is_running:
            return
        
        self.stream_speed_sec = speed_sec
        self.is_running = True
        self.thread = threading.Thread(target=self._run_loop, args=(engine_ids,), daemon=True)
        self.thread.start()
        print(f"[Sensor Streamer] Background streaming started for engines {engine_ids or '1..5'} at {speed_sec}s interval")

    def stop_streaming(self):
        self.is_running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2.0)
        print("[Sensor Streamer] Streaming stopped.")

    def _run_loop(self, engine_ids: list[int] = None):
        target_engines = engine_ids or [1, 2, 3, 4, 5]
        subset = self.stream_data[self.stream_data["unit_number"].isin(target_engines)]
        grouped = {uid: group.sort_values("time_in_cycles").to_dict("records") 
                   for uid, group in subset.groupby("unit_number")}

        indices = {uid: 0 for uid in target_engines}

        while self.is_running:
            all_done = True
            for uid in target_engines:
                records = grouped.get(uid, [])
                idx = indices[uid]

                if idx < len(records):
                    all_done = False
                    row = records[idx]
                    
                    # Construct Big Data event payload
                    event = {
                        "engine_id": int(row["unit_number"]),
                        "cycle": int(row["time_in_cycles"]),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "settings": {
                            "setting_1": float(row["setting_1"]),
                            "setting_2": float(row["setting_2"]),
                            "setting_3": float(row["setting_3"]),
                        },
                        "telemetry": {
                            f"sensor_{i}": float(row[f"sensor_{i}"]) for i in range(1, 22)
                        },
                        "ground_truth_rul": float(row["RUL"]),
                        "ground_truth_failure_within_24h": int(row["failure_within_24h"])
                    }

                    self.producer.send_telemetry(event, key=str(uid))
                    self.current_cycle_by_engine[uid] = int(row["time_in_cycles"])
                    self.total_emitted += 1
                    indices[uid] += 1

            if all_done:
                # Reset indices for infinite loop demonstration
                indices = {uid: 0 for uid in target_engines}

            time.sleep(self.stream_speed_sec)

    def get_status(self):
        return {
            "is_streaming": self.is_running,
            "emission_interval_sec": self.stream_speed_sec,
            "total_events_emitted": self.total_emitted,
            "monitored_engines": self.current_cycle_by_engine
        }

if __name__ == "__main__":
    streamer = SensorTelemetryStreamer()
    streamer.start_streaming(engine_ids=[1, 2], speed_sec=0.2)
    time.sleep(1.5)
    print("Streamer status:", streamer.get_status())
    streamer.stop_streaming()
