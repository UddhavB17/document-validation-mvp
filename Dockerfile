# DMEF backend image (owned by ws-b-storage-db). Python 3.11 only.
#
# Entry commands:
#   uvicorn main:app --host 0.0.0.0 --port 8080
#   python -m services.worker
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System deps for the OCR/PDF stack: OpenCV needs libGL/libglib, Pillow and
# PyMuPDF need no extra libs on slim, curl is handy for health checks.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
