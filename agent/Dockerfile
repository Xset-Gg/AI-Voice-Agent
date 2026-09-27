FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends gcc g++ && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home --uid 10001 agent
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY voice_agent ./voice_agent
USER agent
# Bake VAD + turn-detector model weights into the image so cold starts are fast.
RUN python -m voice_agent.worker download-files

CMD ["python", "-m", "voice_agent.worker", "start"]
