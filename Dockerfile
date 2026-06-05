FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libatlas3-base libjpeg62-turbo libopenblas0 liblapack3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir dlib-bin face-recognition-models \
    && pip install --no-cache-dir --no-deps face-recognition \
    && pip install --no-cache-dir -r requirements.txt gunicorn

COPY . .

ENV FLASK_HOST=0.0.0.0
ENV FLASK_PORT=5000
ENV FLASK_DEBUG=false
ENV ENABLE_PI_TTS=false

EXPOSE 5000

CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:5000", "app:app"]
