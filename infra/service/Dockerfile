# Build from the repo root so this can COPY both src/ and outputs/:
#   docker build -f infra/service/Dockerfile -t <image> .
FROM python:3.11-slim

WORKDIR /app

COPY infra/service/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download the sentence-transformer weights at build time so cold start
# never depends on Hugging Face Hub availability or rate limits.
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

# Application code + the small set of src/ modules the service imports.
COPY infra/service/main.py infra/service/report.py ./
COPY src/taxonomy.py src/taxonomy.yaml src/classifiers.py src/classifier_router.py src/predict_service.py src/gemini_classifier.py src/text_features.py ./src/

# Training data for the router, bundled into the image — there's no
# persisted model artifact (see classifier_router.py), the TF-IDF+LogReg
# router retrains from this file at cold start, which takes ~1-2s.
COPY outputs/tickets.csv ./outputs/tickets.csv

ENV PYTHONUNBUFFERED=1
ENV PORT=8080
EXPOSE 8080

CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "--timeout", "120", "main:app"]
