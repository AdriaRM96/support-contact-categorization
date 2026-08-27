"""Cloud Run classification service.

Deployed twice (see infra/main.tf) as `triage-classifier` and
`final-classifier`, distinguished only by the STAGE env var — both run the
same code, the only difference is which text field the caller sends and
which BigQuery `stage` value gets written.

On the one-time deploy window this project uses for its demo, each request
runs classification through BOTH paths:
  - the router (src/predict_service.py) — a sanity check, should reproduce
    the Phase 2 offline numbers.
  - Gemini via Vertex AI (src/gemini_classifier.py) — gated by
    USE_LLM_CLASSIFIER, its first real execution in the project.
Both predictions are written to BigQuery so the two can be compared later;
the dashboard itself only reads the router's prediction (see
dashboard/app.py) since that's the production default.
"""
from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from flask import Flask, jsonify, request  # noqa: E402
from google.cloud import bigquery  # noqa: E402

from predict_service import TicketClassifierService  # noqa: E402
from taxonomy import load_taxonomy  # noqa: E402

STAGE = os.environ.get("STAGE", "triage")  # "triage" or "final"
PROJECT_ID = os.environ["GCP_PROJECT_ID"]
BQ_DATASET = os.environ["BQ_DATASET"]
BQ_TABLE = f"{PROJECT_ID}.{BQ_DATASET}.classified_tickets"
USE_LLM_CLASSIFIER = os.environ.get("USE_LLM_CLASSIFIER", "false").lower() == "true"

app = Flask(__name__)

taxonomy = load_taxonomy()
router_service = TicketClassifierService(taxonomy=taxonomy)
bq_client = bigquery.Client(project=PROJECT_ID)

gemini = None
if USE_LLM_CLASSIFIER:
    from gemini_classifier import GeminiClassifier

    gemini = GeminiClassifier(taxonomy, project=PROJECT_ID)


@app.get("/status")
def status():
    # Not named /healthz: that path is reserved by Cloud Run's own internal
    # health-check infrastructure and never actually reaches the container
    # on this platform version -- confirmed by A/B testing a trivial control
    # image where /healthz consistently 404'd at the edge while every other
    # path routed through correctly.
    return jsonify({"status": "ok", "stage": STAGE, "gemini_enabled": USE_LLM_CLASSIFIER})


@app.post("/classify")
def classify():
    payload = request.get_json(force=True)
    ticket_id = payload["ticket_id"]
    subject = payload.get("subject", "")

    if STAGE == "triage":
        text = f"{subject}. {payload.get('first_message', '')}".strip()
        router_category = router_service.classify_triage(subject, payload.get("first_message", ""))
    else:
        messages = payload.get("messages", [])
        text = (subject + ". " + " ".join(messages)).strip()
        router_category = router_service.classify_final(subject, messages)

    gemini_category = gemini_confidence = gemini_reasoning = None
    gemini_latency_ms = None
    if gemini is not None:
        t0 = time.time()
        gemini_result = gemini._classify_one(text)
        gemini_latency_ms = int((time.time() - t0) * 1000)
        gemini_category = gemini_result.get("category_id")
        gemini_confidence = gemini_result.get("confidence")
        gemini_reasoning = gemini_result.get("reasoning")

    row = {
        "ticket_id": ticket_id,
        "stage": STAGE,
        "router_category": router_category,
        "gemini_category": gemini_category,
        "gemini_confidence": gemini_confidence,
        "gemini_reasoning": gemini_reasoning,
        "gemini_latency_ms": gemini_latency_ms,
        "taxonomy_version": taxonomy.taxonomy_version,
        "classified_at": datetime.now(timezone.utc).isoformat(),
    }
    errors = bq_client.insert_rows_json(BQ_TABLE, [row])
    if errors:
        return jsonify({"error": "bigquery insert failed", "details": errors}), 500

    return jsonify(row)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
