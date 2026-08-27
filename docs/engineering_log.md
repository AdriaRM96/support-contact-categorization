# Engineering log

Running log of notable decisions, bugs, and findings as the project was built —
source material for the eventual repo wiki/roadmap section. Newest first.

## Phase 4 — Cloud pipeline + Gemini comparison

**Gemini beats every other approach, but the headline number hides real variation.**
Zero-shot Gemini 2.5 Flash (taxonomy embedded in-prompt) scored 98.7% final
accuracy / 98.3% macro F1 on the held-out test set — ahead of the hybrid
router (92.7%/91.9%), which was the router-based recommendation from Phase 2.
But broken down by ticket difficulty: 98.3% on the full set drops to **92.5%**
on drift cases (conversation reveals a different issue than the subject
implied) and **80.0%** on deliberately ambiguous cases — the dataset's
hard-case buckets are doing their job. On inspection, several of the
"misclassified" tickets look like *label noise in the synthetic drift
generator* rather than genuine Gemini errors — the drift target category is
picked semi-randomly in `data_generation.py` without checking it's a
coherent match for the grafted text, so some `true_category_id_final` values
are themselves questionable. Worth a caveat in the README results section,
and possibly a future fix to the generator (ensure the drift target text
actually supports the assigned label).

**The `/healthz` path is silently reserved by Cloud Run's platform infrastructure.**
Both deployed Cloud Run services (`triage-classifier`, `final-classifier`)
were reported "Ready" and passed Cloud Run's own internal startup probes
against `/healthz` — but every external request to that exact path returned
a generic Google-branded 404, with zero server-side logs, regardless of
deployment method (Terraform or `gcloud run deploy`), memory allocation, or
probe configuration. Root-caused via A/B testing a trivial control Flask
image: `/status` and `/ping` worked instantly, `/healthz` consistently
404'd. Conclusion: `/healthz` is intercepted by Cloud Run's own
infrastructure before reaching the container. Fixed by renaming the
endpoint to `/status` in `infra/service/main.py`. This cost several hours of
debugging — logged here so nobody re-derives it from scratch.

**Third real deploy bug: 1Gi memory was insufficient under real request load.**
The `simulate_tickets.py` full run against the live services crashed
`final-classifier` in a repeated OOM loop (~1030-1120MiB used against a
1024MiB limit), even though the same image had passed lighter earlier
tests fine — actual production-shaped traffic (longer final-stage text,
sustained requests) pushed memory past what looked adequate in a handful of
manual test calls. Fixed by raising the limit to 2Gi in `infra/main.tf`.
Lesson: a memory limit validated only against a few manual test requests
isn't validated against real load — the full simulator run is what caught
this, not the earlier smoke tests.

**Two other real deploy bugs, fixed along the way:**
- Container images must be built with `--platform linux/amd64` explicitly;
  Docker on Apple Silicon defaults to arm64, which Cloud Run rejects with a
  clear error. Fixed in `infra/deploy.sh`.
- Cloud Run CLI's default memory (512MiB) is too small for this image
  (~600MB actual usage from torch + sentence-transformers) — causes an OOM
  crash loop. Terraform's explicit `memory = "1Gi"` avoids this; worth
  remembering if anyone ever deploys manually via `gcloud run deploy`
  without an explicit `--memory` flag.

**Gemini API cost-efficiency fixes:**
- `gemini-2.0-flash-001` isn't served on the `global` Vertex AI endpoint for
  this project (404 NOT_FOUND) — switched to `gemini-2.5-flash`, confirmed
  available via `client.models.list()`.
- Gemini 2.5's default "thinking" mode adds hidden reasoning tokens billed
  as output (35 vs 6 tokens on a trivial test call) — disabled via
  `thinking_config=ThinkingConfig(thinking_budget=0)` in
  `gemini_classifier.py`, appropriate since this is simple structured
  classification, not a task needing extended reasoning.
- The Free Trial project's Vertex AI quota is low enough that a tight
  sequential loop hits `429 RESOURCE_EXHAUSTED` quickly. Fixed with a 2s
  pacing delay between requests plus exponential backoff retry (up to 6
  attempts) in `GeminiClassifier._classify_one`.

**Design principle confirmed: triage-vs-final disagreement is a first-class
signal, not two independent accuracy numbers.** In real support workflows,
an email subject/opener frequently doesn't match what the ticket is
actually about once the full thread plays out. That's exactly why the
pipeline classifies twice (creation and close) — not to report two
separate error rates, but to measure how often the pipeline's own
understanding *changes* between the two passes. This is implemented as
`category_disagreement` in `classification_pipeline.py` (computed per
ticket, not aggregated blindly) and surfaced as a dedicated dashboard KPI
("pipeline health") plus a drill-down showing which category pairs disagree
most often. The synthetic dataset's `is_drift_case` flag exists specifically
to give this signal something real to detect.

**`simulate_tickets.py` needed resilience for a real batch run.** The
original version crashed the entire run on the first HTTP failure (a 90s
client timeout hit during the OOM crash loop above). Fixed to catch
per-ticket request exceptions, log and continue, and added `--start-id` to
resume a partial run without redoing already-completed tickets. Full run
against the live deployed services: 1200/1200 triage classifications,
958/958 final classifications, both router and Gemini populated for every
ticket in BigQuery — a handful of transient 500s (Gemini took 30s on one
call) were caught and individually retried rather than requiring a full
re-run.

## Stage 4 — teardown

`google_bigquery_table` defaults to `deletion_protection = true` in this
provider version — `terraform destroy` would have failed on the table
without setting it to `false` first (a deliberate, separate apply, not
folded into destroy itself, since flipping deletion protection is worth its
own explicit step). Full teardown then completed cleanly: 20 resources
destroyed, independently verified via `gcloud run services/jobs list`,
`bq ls`, `gcloud artifacts repositories list`, and `gcloud scheduler jobs
list` all returning empty, plus `terraform state list` empty. Real total
cost for the entire deploy → demo → teardown cycle: ≈ $1.41 (see
`docs/cost_breakdown.md`).

## Stage 3 — capture

**`weekly-report` Job failed on first two executions: `bigquery.dataEditor`
doesn't include `bigquery.jobs.create`.** The runtime service account could
write classified rows fine (that's what the Cloud Run services do), but
`report.py`'s summary query needs to actually *run* a BigQuery query, which
requires `roles/bigquery.jobUser` separately. Fixed in `infra/main.tf`.
Third execution succeeded — real output saved to
`docs/weekly_report_sample.txt`, including genuine per-category
router/Gemini disagreement counts from the live simulation data.

**Real Gemini token usage, pulled from Cloud Monitoring
(`aiplatform.googleapis.com/publisher/online_serving/token_count`), not
estimated:** across the full Stage 2 window (evaluation notebook + fixes +
detailed capture + live simulation), actual usage was 8,168,304 input
tokens and 273,047 output tokens for `gemini-2.5-flash`. See
`docs/cost_breakdown.md` for the full breakdown — this ended up higher than
the original estimate because of the extra debugging/fix runs (rerunning
the eval after the model-name and new-category bugs, the detailed
predictions capture, the gap-fill passes), not because per-call cost was
underestimated.

## Phase 3 — Dashboard

Redesigned around 3 questions an ops manager needs answered in under 5
seconds ("what's driving contacts", "is anything spiking", "is the pipeline
healthy") after the original build was judged too generic. Colour encodes
taxonomy *group* (7 fixed hues), not all 26 categories individually — tested
with the user, who agreed a 26-colour legend stops being readable.

## Phase 2 — Classifier comparison

Built and compared 4 approaches: TF-IDF+LogReg, embeddings+nearest-centroid,
embeddings+LogReg, and a hybrid router combining TF-IDF (known categories)
with the centroid (fallback for anything never seen). The router was chosen
as the production recommendation specifically because trained classifiers
structurally cannot predict a category they've never seen — the new-category
test showed 0% accuracy for trained approaches vs 100% for the
centroid/router, a stronger point than any accuracy percentage alone.
