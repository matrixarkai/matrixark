FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
ENV MATRIXARK_EMBEDDING_PROVIDER=sentence-transformers
ENV MATRIXARK_EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
ENV MATRIXARK_EXTRACTION_PROVIDER=oss-llm
ENV MATRIXARK_EXTRACTION_MODEL=google/flan-t5-small
ENV MATRIXARK_VLM_PROVIDER=hf-vlm
ENV MATRIXARK_VLM_MODEL=Salesforce/blip-image-captioning-base

WORKDIR /app

COPY requirements-models.txt /tmp/requirements-models.txt
RUN pip install --no-cache-dir -r /tmp/requirements-models.txt

COPY . /app

CMD ["python", "-m", "unittest", "discover", "-s", "tests", "-v"]
