"""Weekly summary report — run as a Cloud Run Job, triggered by the Cloud
Scheduler job defined in infra/main.tf.

Queries the classified_tickets BigQuery table and logs a summary (category
volumes, router/Gemini agreement rate) to stdout, which Cloud Run Jobs
sends to Cloud Logging — no extra reporting infrastructure needed for a
project that's deployed for a short demo window and then torn down.
"""
from __future__ import annotations

import os

from google.cloud import bigquery

PROJECT_ID = os.environ["GCP_PROJECT_ID"]
BQ_DATASET = os.environ["BQ_DATASET"]
BQ_TABLE = f"{PROJECT_ID}.{BQ_DATASET}.classified_tickets"

QUERY = f"""
SELECT
  stage,
  router_category,
  COUNT(*) AS contacts,
  COUNTIF(gemini_category IS NOT NULL AND gemini_category != router_category) AS router_gemini_disagreements
FROM `{BQ_TABLE}`
WHERE classified_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
GROUP BY stage, router_category
ORDER BY stage, contacts DESC
"""


def main() -> None:
    client = bigquery.Client(project=PROJECT_ID)
    rows = list(client.query(QUERY).result())

    if not rows:
        print("No classified tickets in the last 7 days.")
        return

    print(f"Weekly summary — {len(rows)} (stage, category) rows in the last 7 days")
    print(f"{'stage':<8} {'category':<12} {'contacts':>8} {'router/gemini disagreements':>28}")
    for row in rows:
        print(f"{row.stage:<8} {row.router_category:<12} {row.contacts:>8} {row.router_gemini_disagreements:>28}")


if __name__ == "__main__":
    main()
