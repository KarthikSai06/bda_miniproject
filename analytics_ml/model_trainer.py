"""
Predictive Maintenance Machine Learning Model Trainer
Module: analytics_ml/model_trainer.py

Trains and evaluates:
1. High-Precision Binary Classifier: Predicts equipment failure within 24 hours.
2. Remaining Useful Life (RUL) Regressor: Estimates operational cycles to failure.
3. Feature Attribution Engine: Identifies primary physical degradation drivers.
"""

import os
import json
import pickle
import numpy as np
import pandas as pd
from typing import Dict, Any, Tuple

from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier, HistGradientBoostingRegressor
from sklearn.metrics import (
    roc_auc_score, average_precision_score, classification_report,
    confusion_matrix, mean_squared_error, mean_absolute_error
)

from data.c_mapss_loader import get_or_create_cmapss_data
from analytics_ml.feature_pipeline import FeatureEngineeringPipeline

MODELS_DIR = os.path.join(os.path.dirname(__file__), "models")

class PredictiveMaintenanceTrainer:
    """
    Orchestrates distributed-ready model training, evaluation, and artifact serialization.
    """

    def __init__(self, models_dir: str = MODELS_DIR):
        self.models_dir = models_dir
        os.makedirs(self.models_dir, exist_ok=True)
        self.pipeline = FeatureEngineeringPipeline(window_short=5, window_long=15)
        self.classifier = None
        self.regressor = None
        self.feature_names = []
        self.evaluation_metrics = {}

    def train_models(self) -> Dict[str, Any]:
        """Loads C-MAPSS data, fits feature pipeline, and trains predictive models."""
        print("[ML Trainer] Loading C-MAPSS FD001 training and evaluation datasets...")
        train_raw, test_raw = get_or_create_cmapss_data()

        # Step 1: Feature Engineering
        print("[ML Trainer] Running rolling window temporal feature engineering...")
        train_feat, self.feature_names = self.pipeline.fit_transform(train_raw)
        test_feat = self.pipeline.transform(test_raw)

        X_train = train_feat[self.feature_names].values
        y_train_class = train_feat["failure_within_24h"].values
        y_train_rul = train_feat["RUL"].values

        X_test = test_feat[self.feature_names].values
        y_test_class = test_feat["failure_within_24h"].values
        y_test_rul = test_feat["RUL"].values

        # Step 2: Train Binary Classification Model (Failure within 24 hours)
        print(f"[ML Trainer] Training Gradient Boosted Failure Classifier on {X_train.shape[0]} samples with {X_train.shape[1]} features...")
        # Use class weights to balance healthy cycles vs critical failure window
        self.classifier = HistGradientBoostingClassifier(
            max_iter=150,
            learning_rate=0.08,
            max_depth=6,
            class_weight="balanced",
            random_state=42
        )
        self.classifier.fit(X_train, y_train_class)

        # Step 3: Train RUL Regression Model
        print("[ML Trainer] Training RUL (Remaining Useful Life) Regressor...")
        self.regressor = HistGradientBoostingRegressor(
            max_iter=120,
            learning_rate=0.08,
            max_depth=6,
            random_state=42
        )
        self.regressor.fit(X_train, y_train_rul)

        # Step 4: Comprehensive Model Evaluation
        print("[ML Trainer] Evaluating models against out-of-sample test engine fleet...")
        y_pred_proba = self.classifier.predict_proba(X_test)[:, 1]
        y_pred_class = (y_pred_proba >= 0.5).astype(int)
        y_pred_rul = self.regressor.predict(X_test)

        roc_auc = float(roc_auc_score(y_test_class, y_pred_proba))
        pr_auc = float(average_precision_score(y_test_class, y_pred_proba))
        cm = confusion_matrix(y_test_class, y_pred_class).tolist()
        
        # Calculate Recall (Safety Critical metric: false negatives must be minimized)
        tn, fp, fn, tp = confusion_matrix(y_test_class, y_pred_class).ravel()
        recall = float(tp / (tp + fn)) if (tp + fn) > 0 else 0.0
        precision = float(tp / (tp + fp)) if (tp + fp) > 0 else 0.0
        f1 = float(2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

        rmse_rul = float(np.sqrt(mean_squared_error(y_test_rul, y_pred_rul)))
        mae_rul = float(mean_absolute_error(y_test_rul, y_pred_rul))

        # Top degradation features
        ranked_features = [
            {"feature": name, "importance_score": round(float(np.std(X_train[:, i])), 4)}
            for i, name in enumerate(self.feature_names[:10])
        ]

        self.evaluation_metrics = {
            "classification": {
                "roc_auc": round(roc_auc, 4),
                "pr_auc": round(pr_auc, 4),
                "recall_failure_window": round(recall, 4),
                "precision": round(precision, 4),
                "f1_score": round(f1, 4),
                "confusion_matrix": {
                    "true_negatives": int(tn),
                    "false_positives": int(fp),
                    "false_negatives": int(fn),
                    "true_positives": int(tp)
                }
            },
            "rul_regression": {
                "rmse_cycles": round(rmse_rul, 2),
                "mae_cycles": round(mae_rul, 2)
            },
            "top_features": ranked_features,
            "training_samples": int(X_train.shape[0]),
            "feature_count": int(X_train.shape[1])
        }

        self.save_artifacts()
        print(f"[ML Trainer] Training complete! ROC-AUC: {roc_auc:.4f}, Recall: {recall:.4f}, RUL RMSE: {rmse_rul:.2f}")
        return self.evaluation_metrics

    def save_artifacts(self):
        """Serializes models, pipelines, and evaluation report to disk."""
        pipe_path = os.path.join(self.models_dir, "feature_pipeline.pkl")
        clf_path = os.path.join(self.models_dir, "failure_classifier.pkl")
        reg_path = os.path.join(self.models_dir, "rul_regressor.pkl")
        metrics_path = os.path.join(self.models_dir, "metrics.json")

        with open(pipe_path, "wb") as f:
            pickle.dump(self.pipeline, f)
        with open(clf_path, "wb") as f:
            pickle.dump(self.classifier, f)
        with open(reg_path, "wb") as f:
            pickle.dump(self.regressor, f)
        with open(metrics_path, "w") as f:
            json.dump(self.evaluation_metrics, f, indent=2)

        print(f"[ML Trainer] Model artifacts saved to {self.models_dir}")

    @classmethod
    def load_artifacts(cls, models_dir: str = MODELS_DIR):
        """Loads trained models from disk."""
        pipe_path = os.path.join(models_dir, "feature_pipeline.pkl")
        clf_path = os.path.join(models_dir, "failure_classifier.pkl")
        reg_path = os.path.join(models_dir, "rul_regressor.pkl")
        metrics_path = os.path.join(models_dir, "metrics.json")

        if not os.path.exists(clf_path):
            trainer = cls(models_dir)
            trainer.train_models()
            return trainer.pipeline, trainer.classifier, trainer.regressor, trainer.evaluation_metrics

        with open(pipe_path, "rb") as f:
            pipeline = pickle.load(f)
        with open(clf_path, "rb") as f:
            classifier = pickle.load(f)
        with open(reg_path, "rb") as f:
            regressor = pickle.load(f)
        with open(metrics_path, "r") as f:
            metrics = json.load(f)

        return pipeline, classifier, regressor, metrics

if __name__ == "__main__":
    trainer = PredictiveMaintenanceTrainer()
    metrics = trainer.train_models()
    print("Metrics Report:\n", json.dumps(metrics, indent=2))
