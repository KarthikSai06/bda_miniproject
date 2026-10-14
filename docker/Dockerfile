FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Ensure data and models are initialized
RUN python -c "from data.c_mapss_loader import get_or_create_cmapss_data; get_or_create_cmapss_data('data')"
RUN python -c "from analytics_ml.model_trainer import PredictiveMaintenanceTrainer; trainer = PredictiveMaintenanceTrainer(); trainer.train_models()"

EXPOSE 8000

CMD ["python", "run_pipeline.py", "--host", "0.0.0.0", "--port", "8000"]
