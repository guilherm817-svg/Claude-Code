FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    RASTRO_PASTA_DADOS=/dados \
    PORT=8000

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY rastro ./rastro

RUN useradd --create-home rastro && mkdir -p /dados && chown rastro /dados
USER rastro
VOLUME /dados
EXPOSE 8000

# Um processo só: a sincronização com o Meta roda dentro dele.
CMD ["python", "-m", "rastro"]
