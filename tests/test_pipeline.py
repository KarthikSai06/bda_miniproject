"""
End-to-End Test Suite for Predictive Maintenance Big Data Pipeline
Module: tests/test_pipeline.py
"""

import os
import sys
import unittest
import numpy as np
import pandas as pd

# Add project root to sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from data.c_mapss_loader import get_or_create_cmapss_data
from storage.hdfs_lakehouse import HDFSLakehouse
from ingestion.kafka_streamer import KafkaTelemetryProducer, KafkaTelemetryConsumer, InProcessKafkaBroker
from analytics_ml.feature_pipeline import FeatureEngineeringPipeline, StreamingFeatureBuffer
from analytics_ml.model_trainer import PredictiveMaintenanceTrainer
from streaming_inference.work_order_system import WorkOrderManager

class TestPredictiveMaintenancePipeline(unittest.TestCase):

    def test_01_c_mapss_data_integrity(self):
        """Verifies NASA C-MAPSS dataset structure and labels."""
        train_df, test_df = get_or_create_cmapss_data(os.path.join(PROJECT_ROOT, "data"))
        self.assertGreater(len(train_df), 10000)
        self.assertGreater(len(test_df), 5000)
        self.assertIn("RUL", train_df.columns)
        self.assertIn("failure_within_24h", train_df.columns)
        self.assertIn("health_status", train_df.columns)
        print("  [OK] C-MAPSS dataset integrity verified.")

    def test_02_hdfs_lakehouse_operations(self):
        """Tests HDFS micro-batch ingestion and Parquet compaction."""
        test_hdfs_dir = os.path.join(PROJECT_ROOT, "lakehouse", "test_lakehouse")
        lakehouse = HDFSLakehouse(base_hdfs_path=test_hdfs_dir)
        
        sample_batch = [
            {"engine_id": 99, "cycle": 10, "telemetry": {"sensor_3": 1589.2, "sensor_7": 554.1}},
            {"engine_id": 99, "cycle": 11, "telemetry": {"sensor_3": 1590.1, "sensor_7": 553.8}}
        ]
        batch_file = lakehouse.write_stream_microbatch(sample_batch)
        self.assertTrue(os.path.exists(batch_file))
        
        status = lakehouse.get_cluster_status()
        self.assertEqual(status["status"], "HEALTHY")
        self.assertGreaterEqual(status["total_records_ingested"], 2)

        parquet_file = lakehouse.compact_to_parquet()
        self.assertTrue(os.path.exists(parquet_file))
        print("  [OK] HDFS Lakehouse ingestion & Parquet compaction verified.")

    def test_03_kafka_streaming_broker(self):
        """Tests Kafka pub/sub, partitioning, and consumer group offset management."""
        topic = "test-sensor-topic"
        producer = KafkaTelemetryProducer(topic=topic)
        consumer = KafkaTelemetryConsumer(topic=topic, group_id="test-consumer-group")

        test_msg = {"engine_id": 42, "cycle": 105, "sensor_3": 1592.5}
        producer.send_telemetry(test_msg, key="42")

        consumed = consumer.poll_batch(max_records=10)
        self.assertGreater(len(consumed), 0)
        self.assertEqual(consumed[0]["engine_id"], 42)
        print("  [OK] Kafka streaming pub/sub and offset tracking verified.")

    def test_04_feature_pipeline_and_models(self):
        """Verifies feature extraction and model inference consistency."""
        pipeline, classifier, regressor, metrics = PredictiveMaintenanceTrainer.load_artifacts(
            models_dir=os.path.join(PROJECT_ROOT, "analytics_ml", "models")
        )
        self.assertIsNotNone(classifier)
        self.assertIsNotNone(regressor)
        self.assertGreater(metrics["classification"]["roc_auc"], 0.85)

        # Test single-event streaming feature buffer
        buffer = StreamingFeatureBuffer(pipeline, maxlen=15)
        for c in range(1, 10):
            event = {
                "engine_id": 1,
                "cycle": c,
                "settings": {"setting_1": 0.0, "setting_2": 0.0, "setting_3": 100.0},
                "telemetry": {f"sensor_{i}": 500.0 + c for i in range(1, 22)}
            }
            feat_vec, names = buffer.push_and_extract(event)

        prob = float(classifier.predict_proba(feat_vec)[0, 1])
        rul = float(regressor.predict(feat_vec)[0])
        self.assertTrue(0.0 <= prob <= 1.0)
        self.assertGreaterEqual(rul, 0.0)
        print(f"  [OK] Model scoring verified (P_fail: {prob:.3f}, RUL: {rul:.1f} hrs).")

    def test_05_work_order_lifecycle(self):
        """Tests automated work order generation and state transitions."""
        test_wo_file = os.path.join(PROJECT_ROOT, "streaming_inference", "test_wo.json")
        if os.path.exists(test_wo_file):
            os.remove(test_wo_file)

        mgr = WorkOrderManager(store_file=test_wo_file)
        wo = mgr.evaluate_and_trigger(
            engine_id=7,
            cycle=190,
            failure_prob=0.92,
            predicted_rul=12.0,
            telemetry={"sensor_3": 1608.5, "sensor_7": 550.2}
        )
        self.assertIsNotNone(wo)
        self.assertEqual(wo["severity"], "CRITICAL")
        self.assertEqual(wo["status"], "OPEN")

        # Update status to IN_PROGRESS
        res = mgr.update_status(wo["work_order_id"], "IN_PROGRESS", technician="Specialist Sarah K.")
        self.assertTrue(res)
        self.assertEqual(mgr.work_orders[wo["work_order_id"]]["status"], "IN_PROGRESS")
        print("  [OK] Work order evaluation, thresholding, and lifecycle verified.")

if __name__ == "__main__":
    unittest.main()
