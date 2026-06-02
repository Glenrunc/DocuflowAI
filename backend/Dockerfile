# DocuFlow AI backend — FastAPI API + worker share this image (different CMD).
# CUDA wheels for torch/torchvision are pulled from PyPI (default cu12 build).
# For the documented CPU fallback set OCR_DEVICE=cpu; the same image still runs.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# docTR needs libGL/glib for image decoding.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt

COPY backend/app ./app
COPY shared /shared

# Paths resolved via env (config.py reads these); shared schema mounted at /shared.
ENV SHARED_SCHEMA_PATH=/shared/schemas.json \
    STORAGE_DIR=/app/storage

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
