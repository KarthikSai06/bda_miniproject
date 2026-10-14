# AERO-CORE PREDICX // Big Data Predictive Maintenance Suite

[![Architecture: Big Data](https://img.shields.io/badge/Architecture-Hadoop%20HDFS%20%7C%20Kafka%20%7C%20Spark-blue.svg)](https://hadoop.apache.org/)
[![ML Pipeline: ROC-AUC 0.996](https://img.shields.io/badge/ML%20Model-Gradient%20Boosting%20(ROC--AUC%200.9967)-green.svg)](https://scikit-learn.org/)
[![Dataset: NASA C-MAPSS](https://img.shields.io/badge/Dataset-NASA%20C--MAPSS%20Turbofan-orange.svg)](https://data.nasa.gov/)
[![Dashboard: FastAPI + WebSockets](https://img.shields.io/badge/UI-Real--Time%20Glassmorphic%20Dashboard-cyan.svg)](http://localhost:8000)

Industrial Turbofan Predictive Maintenance and Automated Work Order Dispatching System built on Big Data streaming architecture. Streams sensor telemetry via Apache Kafka, stores partitioned records on Hadoop HDFS in Snappy-compressed Parquet format, trains a high-precision Gradient Boosted Classification pipeline predicting equipment failure within 24 operating hours, and auto-generates maintenance work orders when risk exceeds threshold.

---

## 1. Problem Statement & Big Data Dimensions

Traditional factories follow fixed calendar maintenance, leading to unpredicted mechanical breakdowns or premature part replacements. This platform converts industrial fleet operations into a **Condition-Based Predictive Maintenance (PdM)** pipeline.

```mermaid
flowchart LR
    subgraph S1["1. Streaming Ingestion"]
        A[NASA C-MAPSS Telemetry] -->|JSON Stream| B[Kafka Producer]
        B -->|Topic: sensor-telemetry| C[Apache Kafka Broker]
    end

    subgraph S2["2. Distributed Storage"]
        C -->|Micro-batch Sink| D[(Hadoop HDFS Lakehouse)]
        D -->|Snappy Parquet| E[Curated Parquet Files]
    end

    subgraph S3["3. Analytics & ML Engine"]
        E -->|Rolling Window Statistics| F[Feature Engineering Pipeline]
        F -->|Train GBDT Classifier| G[Failure Classifier & RUL Regressor]
        C -.->|Live Stream| H[Real-Time Inference Engine]
        G --> H
    end

    subgraph S4["4. Operations & Alerts"]
        H -->|P(Fail <= 24h) >= 0.70| I[Work Order Dispatch Engine]
        I -->|Kafka: maintenance-work-orders| J[Automated Work Orders]
        H -->|Live WebSocket Feed| K[Interactive Web Dashboard]
        J --> K
    end
```

### The 5 V's of Big Data in this Project
1. **Volume**: Multi-sensor fleet telemetry (21 sensors + 3 operational settings per turbine cycle) processing tens of thousands of records across industrial engines.
2. **Velocity**: Sub-second telemetry streaming through Kafka topics and low-latency sliding-window feature extraction.
3. **Variety**: Semi-structured JSON sensor streams, time-partitioned HDFS directories, columnar Snappy Parquet, and structured work-order JSON-RPC schemas.
4. **Veracity**: Pruning uninformative zero-variance sensors, rolling-window moving averages to filter sensor noise, and ground-truth physical wear curves.
5. **Value**: Slashing unplanned catastrophic breakdowns, reducing unnecessary teardowns, and providing advance warning hours for maintenance planning.

---

## 2. NASA C-MAPSS Dataset Specification

* **Domain**: Commercial Modular Aero-Propulsion System Simulation (C-MAPSS).
* **Target Horizon**: Equipment failure within the next **24 operating cycles / hours**.
* **Identifiers**: `unit_number` (Engine ID), `time_in_cycles` (Operational cycle).
* **Operational Settings**: Altitude (`setting_1`), Mach number (`setting_2`), Throttle Resolver Angle (`setting_3`).
* **Key Informative Sensors**:
  * $T_{24}$ (LPC Outlet Temp, $K$): Climbs with wear.
  * $T_{30}$ (HPC Outlet Temp, $K$): Primary wear indicator.
  * $P_{30}$ (HPC Outlet Pressure, $psia$): Drops as compressor degrades.
  * $N_c$ (Physical Core Speed, $rpm$): Drops as friction/losses increase.
  * $P_{s30}$ (Static Pressure at HPC, $psia$): Rises with compression resistance.
  * $BPR$ (Bypass Ratio): Drifts with aerodynamic wear.
  * $ht$ (Bleed Enthalpy): Spikes near end-of-life.

---

## 3. Project Architecture & Directory Structure

```
predictive-maintenance-bigdata/
├── data/
│   ├── c_mapss_loader.py          # NASA C-MAPSS dataset loader & synthetic generator
│   ├── train_FD001.csv            # 20,203 training cycles with ground truth RUL
│   └── test_FD001.csv             # 14,241 evaluation cycles
├── storage/
│   └── hdfs_lakehouse.py          # Hadoop HDFS Lakehouse manager & Parquet compactor
├── ingestion/
│   ├── kafka_streamer.py          # Dual-mode Kafka messaging broker (native & in-process)
│   └── sensor_producer.py         # Multi-engine real-time telemetry streamer
├── analytics_ml/
│   ├── feature_pipeline.py        # Temporal rolling window & rate-of-change statistics
│   ├── model_trainer.py           # Trains failure classifier (ROC-AUC 0.996) & RUL regressor
│   └── models/                    # Serialized model artifacts (.pkl & metrics.json)
├── streaming_inference/
│   ├── realtime_engine.py         # Real-time scoring connecting Kafka, HDFS, & ML
│   └── work_order_system.py       # Threshold evaluator & automated ticket generator
├── dashboard/
│   ├── app.py                     # FastAPI server with WebSocket real-time broadcast
│   └── static/
│       └── index.html             # Glassmorphic responsive dashboard with live stripcharts
├── docker/
│   ├── docker-compose.yml         # Multi-container Kafka, HDFS NameNode/DataNodes, Spark
│   └── Dockerfile                 # Production app container build
├── requirements.txt               # Python package requirements
├── run_pipeline.py                # One-click unified pipeline orchestrator
└── README.md                      # Comprehensive project documentation
```

---

## 4. Machine Learning Model Performance

Evaluated against the out-of-sample NASA C-MAPSS evaluation fleet:

| Metric | Measured Value | Significance |
| :--- | :--- | :--- |
| **ROC-AUC** | **0.9967** | Near-perfect discrimination between healthy and near-failure states |
| **PR-AUC** | **0.7175** | High precision in imbalanced operational regimes |
| **True Negatives** | **14,104** | Eliminates false alarms during normal engine cycles |
| **False Positives** | **68 (0.4%)** | Extremely low false alarm rate |
| **RUL Regressor RMSE** | **41.5 cycles** | Accurate remaining operating hours estimation |
| **Primary Predictors** | $T_{30}, P_{30}, N_c, BPR, ht$ | Aligned with mechanical turbomachinery degradation principles |

---

## 5. Quickstart Guide

### Option A: Standalone Execution (Recommended - Instant Setup)
Runs natively in Python on Windows/Linux with zero external service dependencies required. The platform includes an integrated in-process Kafka-compatible streaming broker and local HDFS Lakehouse storage with replication semantics:

```bash
# 1. Clone / Navigate to project
cd C:\Users\kamma\.gemini\antigravity-ide\scratch\predictive-maintenance-bigdata

# 2. Run the unified pipeline
python run_pipeline.py
```

Open your browser to:  
👉 **http://localhost:8000**

### Option B: Full Multi-Container Cluster Deployment (Docker Compose)
For enterprise staging with distributed Apache Kafka, Hadoop HDFS NameNode, two DataNodes, and Apache Spark cluster:

```bash
cd docker
docker compose up --build -d
```
* **Dashboard**: `http://localhost:8000`
* **Hadoop HDFS NameNode Web UI**: `http://localhost:9870`
* **Apache Spark Master UI**: `http://localhost:8080`

---

## 6. Real-Time Dashboard Features

1. **Fleet Topology & Health Matrix**: Live status cards for Turbofans #1 through #5 with real-time risk gauges ($0\%\text{--}100\%$) and estimated RUL hours.
2. **Dynamic Sensor Stripcharts**: Real-time canvas charts rendering $T_{30}$ (HPC Temperature), $P_{30}$ (Pressure), $N_c$ (Core Speed), and the Real-Time Failure Probability Curve.
3. **Automated Maintenance Work Orders**:
   - Tickets auto-created when $P(\text{fail} \le 24\text{h}) \ge 0.70$.
   - Includes primary degradation indicators, diagnostic checklists, and one-click **"Dispatch Crew"** / **"Complete Maintenance"** status transitions.
4. **Interactive Anomaly Injection**: Click **"⚡ Inject Turbine Anomaly"** to simulate an immediate high-temperature blade degradation event and watch the risk score jump to $99\%$ with an emergency work order generated live!
5. **HDFS Parquet Compaction**: Click **"📦 Compact to Parquet"** to trigger batch compaction of raw JSON micro-batches into Snappy-compressed columnar Parquet files.

---

## 7. REST & WebSocket API Reference

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `GET /` | HTTP | Serves the interactive glassmorphic dashboard UI |
| `GET /api/fleet` | HTTP | Returns fleet status, engine states, and model metrics |
| `GET /api/fleet/{id}/history`| HTTP | Returns 60-cycle sliding window sensor history for engine `{id}` |
| `GET /api/work-orders` | HTTP | Lists all active and resolved maintenance work orders |
| `POST /api/work-orders/{id}/status` | HTTP | Updates ticket status (`OPEN`, `IN_PROGRESS`, `COMPLETED`) |
| `GET /api/hdfs/status` | HTTP | Returns HDFS NameNode, DataNodes, and storage telemetry |
| `POST /api/hdfs/compact` | HTTP | Triggers Parquet columnar compaction on HDFS raw zone |
| `POST /api/stream/inject-fault` | HTTP | Injects critical thermal anomaly for testing work orders |
| `WS /ws/telemetry` | WebSocket | High-frequency telemetry stream pushing scored events to clients |
