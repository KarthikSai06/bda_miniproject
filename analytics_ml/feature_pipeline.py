"""
Big Data Feature Engineering Pipeline
Module: analytics_ml/feature_pipeline.py

Extracts temporal window statistics, rolling aggregations, rate-of-change deltas,
and sensor normalization required for high-accuracy turbofan failure classification.
Supports both distributed batch processing and real-time streaming feature extraction.
"""

import numpy as np
import pandas as pd
from typing import List, Dict, Any, Tuple
from collections import deque

INFORMATIVE_SENSORS = [
    "sensor_2", "sensor_3", "sensor_4", "sensor_7", "sensor_8",
    "sensor_9", "sensor_11", "sensor_12", "sensor_13", "sensor_14",
    "sensor_15", "sensor_17", "sensor_20", "sensor_21"
]

class FeatureEngineeringPipeline:
    """
    Transforms raw sensor streams into ML-ready predictive feature vectors
    using temporal rolling windows (mean, std, rate-of-change).
    """

    def __init__(self, window_short: int = 5, window_long: int = 15):
        self.window_short = window_short
        self.window_long = window_long
        self.feature_names: List[str] = []
        self.means = {}
        self.stds = {}
        self.is_fitted = False

    def fit_transform(self, df: pd.DataFrame) -> Tuple[pd.DataFrame, List[str]]:
        """Extracts features across full historical training dataset and fits normalizers."""
        engineered_df = self._compute_rolling_features(df)
        self.feature_names = [c for c in engineered_df.columns 
                              if c not in ["unit_number", "time_in_cycles", "RUL", 
                                          "failure_within_24h", "health_status"]]

        # Calculate normalization statistics
        for col in self.feature_names:
            self.means[col] = float(engineered_df[col].mean())
            std_val = float(engineered_df[col].std())
            self.stds[col] = std_val if std_val > 1e-6 else 1.0
            engineered_df[col] = (engineered_df[col] - self.means[col]) / self.stds[col]

        self.is_fitted = True
        return engineered_df, self.feature_names

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """Transforms a test/validation dataframe using fitted statistics."""
        if not self.is_fitted:
            raise ValueError("Pipeline must be fitted first.")
        engineered_df = self._compute_rolling_features(df)
        for col in self.feature_names:
            if col in engineered_df.columns:
                engineered_df[col] = (engineered_df[col] - self.means[col]) / self.stds[col]
            else:
                engineered_df[col] = 0.0
        return engineered_df

    def _compute_rolling_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Computes lag deltas, rolling means, and rolling stds grouped by engine."""
        df = df.copy().sort_values(["unit_number", "time_in_cycles"])
        grouped = df.groupby("unit_number")

        feature_cols = {}
        # Keep operational settings
        for s in ["setting_1", "setting_2", "setting_3"]:
            if s in df.columns:
                feature_cols[s] = df[s]

        # Compute rolling stats for informative sensors
        for s in INFORMATIVE_SENSORS:
            if s not in df.columns:
                continue
            # Raw sensor reading
            feature_cols[s] = df[s]
            # Short-term rolling mean
            feature_cols[f"{s}_mean_w{self.window_short}"] = (
                grouped[s].rolling(self.window_short, min_periods=1).mean().reset_index(0, drop=True)
            )
            # Short-term rolling std (vibration / volatility indicator)
            feature_cols[f"{s}_std_w{self.window_short}"] = (
                grouped[s].rolling(self.window_short, min_periods=1).std().fillna(0).reset_index(0, drop=True)
            )
            # Long-term rolling mean
            feature_cols[f"{s}_mean_w{self.window_long}"] = (
                grouped[s].rolling(self.window_long, min_periods=1).mean().reset_index(0, drop=True)
            )
            # Rate of change / degradation delta
            feature_cols[f"{s}_delta_w{self.window_short}"] = (
                df[s] - grouped[s].shift(self.window_short).fillna(df[s])
            )

        features_df = pd.DataFrame(feature_cols, index=df.index)
        
        # Attach identifiers and targets if available
        for col in ["unit_number", "time_in_cycles", "RUL", "failure_within_24h", "health_status"]:
            if col in df.columns:
                features_df[col] = df[col]

        return features_df


class StreamingFeatureBuffer:
    """
    Maintains low-latency sliding state buffers for real-time Kafka telemetry streams.
    Enables single-event real-time inference without requiring database round-trips.
    """
    def __init__(self, pipeline: FeatureEngineeringPipeline, maxlen: int = 20):
        self.pipeline = pipeline
        self.maxlen = maxlen
        self.buffers: Dict[int, deque] = {}

    def push_and_extract(self, event: Dict[str, Any]) -> Tuple[np.ndarray, List[str]]:
        """
        Pushes a new sensor event into the engine's rolling buffer and returns
        the normalized feature vector ready for model inference.
        """
        engine_id = event["engine_id"]
        if engine_id not in self.buffers:
            self.buffers[engine_id] = deque(maxlen=self.maxlen)

        flat_record = {
            "unit_number": engine_id,
            "time_in_cycles": event["cycle"],
            "setting_1": event.get("settings", {}).get("setting_1", 0.0),
            "setting_2": event.get("settings", {}).get("setting_2", 0.0),
            "setting_3": event.get("settings", {}).get("setting_3", 100.0),
        }
        for s_name, s_val in event.get("telemetry", {}).items():
            flat_record[s_name] = s_val

        self.buffers[engine_id].append(flat_record)
        recent_df = pd.DataFrame(list(self.buffers[engine_id]))
        
        # Transform the single window
        transformed_df = self.pipeline.transform(recent_df)
        latest_features = transformed_df[self.pipeline.feature_names].iloc[-1].values
        
        return latest_features.reshape(1, -1), self.pipeline.feature_names
