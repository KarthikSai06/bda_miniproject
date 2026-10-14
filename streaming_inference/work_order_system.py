"""
Automated Maintenance Work Order Management Subsystem
Module: streaming_inference/work_order_system.py

Evaluates machine risk probabilities against industrial thresholds,
deduplicates alerts, generates compliant maintenance tickets, and
publishes dispatch events to Kafka topic 'maintenance-work-orders'.
"""

import os
import json
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from ingestion.kafka_streamer import KafkaTelemetryProducer

WORK_ORDERS_STORE_FILE = os.path.join(os.path.dirname(__file__), "work_orders.json")

class WorkOrderManager:
    """
    Manages the lifecycle of automated predictive maintenance work orders.
    """

    def __init__(self, store_file: str = WORK_ORDERS_STORE_FILE):
        self.store_file = store_file
        self.work_orders: Dict[str, Dict[str, Any]] = {}
        self.kafka_producer = KafkaTelemetryProducer(topic="maintenance-work-orders")
        self._load_store()

    def _load_store(self):
        if os.path.exists(self.store_file):
            try:
                with open(self.store_file, "r") as f:
                    self.work_orders = json.load(f)
            except Exception:
                self.work_orders = {}

    def _save_store(self):
        with open(self.store_file, "w") as f:
            json.dump(self.work_orders, f, indent=2)

    def evaluate_and_trigger(
        self,
        engine_id: int,
        cycle: int,
        failure_prob: float,
        predicted_rul: float,
        telemetry: Dict[str, float]
    ) -> Optional[Dict[str, Any]]:
        """
        Evaluates risk score and creates or updates a work order when threshold is exceeded.
        """
        # Threshold: Probability of failure within 24 hours >= 0.70
        if failure_prob < 0.70:
            return None

        # Determine severity tier
        if failure_prob >= 0.88 or predicted_rul <= 12:
            severity = "CRITICAL"
        elif failure_prob >= 0.75 or predicted_rul <= 24:
            severity = "HIGH"
        else:
            severity = "MEDIUM"

        now_utc = datetime.now(timezone.utc)

        # Check for existing open work order for this engine
        for wo in self.work_orders.values():
            if wo["engine_id"] == engine_id and wo["status"] in ["OPEN", "IN_PROGRESS"]:
                # Update existing order with newer readings
                wo["latest_failure_prob"] = round(failure_prob, 4)
                wo["latest_predicted_rul"] = round(predicted_rul, 1)
                wo["latest_cycle"] = cycle
                wo["severity"] = severity
                wo["updated_at"] = now_utc.isoformat()
                self._save_store()
                return wo

        # Synthesize physical degradation explanations based on telemetry
        indicators = []
        t30 = telemetry.get("sensor_3", 0.0)
        p30 = telemetry.get("sensor_7", 0.0)
        nc = telemetry.get("sensor_9", 0.0)
        bpr = telemetry.get("sensor_15", 0.0)

        if t30 > 1595.0:
            indicators.append(f"HPC Outlet Temp T30 elevated ({t30:.1f} K vs baseline 1585 K)")
        if p30 < 552.0:
            indicators.append(f"HPC Outlet Pressure P30 drop ({p30:.1f} psia vs baseline 554 psia)")
        if nc < 9045.0:
            indicators.append(f"Physical Core Speed Nc loss ({nc:.1f} rpm vs baseline 9060 rpm)")
        if bpr > 8.48:
            indicators.append(f"Bypass Ratio BPR anomalous drift ({bpr:.3f} vs baseline 8.42)")

        if not indicators:
            indicators = ["Multi-sensor multivariate statistical degradation signature detected"]

        # Formulate industrial action checklist
        actions = [
            f"Perform immediate borescope inspection on High-Pressure Compressor (HPC) stage 3-5",
            f"Verify cooling air bleed valve W31 and thermocouple calibration",
            f"Schedule turbine replacement / overhaul before cycle {cycle + int(predicted_rul)}"
        ]

        wo_id = f"WO-ENG{engine_id:02d}-CYC{cycle}-{now_utc.strftime('%Y%m%d%H%M')}"
        work_order = {
            "work_order_id": wo_id,
            "engine_id": engine_id,
            "asset_name": f"Turbofan CFM-Engine #{engine_id}",
            "created_cycle": cycle,
            "latest_cycle": cycle,
            "failure_probability": round(failure_prob, 4),
            "latest_failure_prob": round(failure_prob, 4),
            "predicted_remaining_hours": round(predicted_rul, 1),
            "severity": severity,
            "status": "OPEN",
            "primary_degradation_indicators": indicators,
            "recommended_actions": actions,
            "assigned_technician": "Turbomachinery Rapid Response Team",
            "created_at": now_utc.isoformat(),
            "updated_at": now_utc.isoformat()
        }

        self.work_orders[wo_id] = work_order
        self._save_store()

        # Publish work order alert to Kafka topic
        self.kafka_producer.send_telemetry(work_order, key=str(engine_id))
        print(f"[WorkOrderEngine] Triggered {severity} Work Order {wo_id} for Engine #{engine_id} (P={failure_prob:.2f})")
        return work_order

    def get_all_work_orders(self) -> List[Dict[str, Any]]:
        self._load_store()
        return sorted(list(self.work_orders.values()), key=lambda x: x["created_at"], reverse=True)

    def update_status(self, work_order_id: str, new_status: str, technician: Optional[str] = None) -> bool:
        if work_order_id in self.work_orders:
            self.work_orders[work_order_id]["status"] = new_status
            if technician:
                self.work_orders[work_order_id]["assigned_technician"] = technician
            self.work_orders[work_order_id]["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._save_store()
            return True
        return False

if __name__ == "__main__":
    mgr = WorkOrderManager()
    wo = mgr.evaluate_and_trigger(
        engine_id=3,
        cycle=165,
        failure_prob=0.91,
        predicted_rul=18.5,
        telemetry={"sensor_3": 1602.1, "sensor_7": 551.2}
    )
    print("Created work order:", wo)
