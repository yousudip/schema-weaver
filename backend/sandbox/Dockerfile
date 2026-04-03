FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN adduser --disabled-password --gecos "" sandbox
WORKDIR /sandbox

# Keep image minimal; add libs as needed for processing.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr poppler-utils \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir pandas numpy

USER sandbox

CMD ["python", "-c", "print('sandbox ready')"]
