FROM python:3.13-slim
WORKDIR /app
# pdftotext leest de prijzenschema's van de loterij voor de update-controle
RUN apt-get update && apt-get install -y --no-install-recommends poppler-utils && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY rules ./rules
ENV DK_DB_PATH=/data/december-kalender.db
ENV DK_UPDATE_DIR=/data/updates
VOLUME /data
EXPOSE 8000
CMD ["uvicorn", "--factory", "app.main:create_app", "--host", "0.0.0.0", "--port", "8000"]
