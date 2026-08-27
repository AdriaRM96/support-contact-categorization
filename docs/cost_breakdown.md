# Cost breakdown

Real figures below, captured during Stage 2-3 of the one-off `infra/deploy.sh`
→ demo → capture cycle (Terraform apply through the live `simulate_tickets.py`
run and the weekly report), pulled directly from **Cloud Monitoring**
(`aiplatform.googleapis.com/publisher/online_serving/token_count`,
`run.googleapis.com/container/billable_instance_time`) and Artifact
Registry's own size reporting — not re-estimated. Window covered: 2026-08-26
00:00 UTC to 2026-08-27 12:00 UTC, i.e. the entire Phase 4 work session.

## Actual vs. estimated

| Resource/operation | Estimated (pre-Stage-2) | **Actual** | Source |
|---|---|---|---|
| Gemini input tokens | ~6.04M tokens, $0.10/1M assumed → $0.604 | **8,168,304 tokens** | Cloud Monitoring token_count metric |
| Gemini output tokens | ~0.249M tokens, $0.40/1M assumed → $0.100 | **273,047 tokens** | Cloud Monitoring token_count metric |
| Gemini cost (input) | $0.604 | **$1.225** (at $0.15/1M, real published rate) | 8,168,304 × $0.15 / 1M |
| Gemini cost (output) | $0.100 | **~$0.164** (at an assumed $0.60/1M — see note below) | 273,047 × $0.60 / 1M |
| Cloud Run compute (all services combined) | ~650-2,158 vCPU-sec, free tier | **26,301 vCPU-sec total** | `run.googleapis.com/container/billable_instance_time`, summed across triage-classifier + final-classifier + throwaway test services |
| Cloud Run compute cost | $0.00 | **$0.00** — 26,301 sec is still well inside the 180,000 vCPU-sec/month free tier | — |
| Artifact Registry storage | ~1.2-1.8GB, ~$0.01-0.02 | **6.32GB** (2 image versions retained: the pre-fix and post-`/status`-fix builds) | `gcloud artifacts repositories describe` |
| Artifact Registry cost | $0.01-0.02 | **~$0.02/day prorated** (5.82GB over the 0.5GB free tier × ~$0.10/GB-month ÷ 30) | — |
| BigQuery storage + queries | $0.00 | **$0.00** — a few thousand rows, query scans well under the 1TB/month free tier | — |
| Cloud Scheduler | $0.00 | **$0.00** — 1 job, first 3/month free | — |
| **Total Gemini spend** | ~$0.70-1.20 | **≈ $1.39** | — |
| **Total (everything)** | ~$0.72-1.22 | **≈ $1.41** | — |

**Why actual came in higher than estimated:** not because per-call cost was
underestimated for the *planned* work — it's because the real request count
ended up well above what was originally scoped, due to three real bugs
found and fixed during Stage 2 (wrong Gemini model name for the `global`
endpoint, rate-limit backoff, insufficient Cloud Run memory) each requiring
a partial or full re-run: the evaluation notebook ran 3 times (1 failed
immediately with 0 cost, 2 completed fully), plus a dedicated fix run for
the new-category test (800 calls) and a detailed-predictions capture (600
calls) requested separately. Total Gemini calls across the whole session:
roughly 5,100 (vs. the ~3,358 originally planned for Stage 2 alone). See
`docs/engineering_log.md` for the full bug list.

**Note on the output token price:** the user confirmed Gemini 2.5 Flash
input pricing directly from the Vertex AI pricing page ($0.15/1M standard,
$0.075/1M Batch API) mid-session, but output pricing wasn't independently
confirmed the same way — the $0.60/1M figure above is a commonly published
rate for this model tier, not verified against the live pricing page the
way the input rate was. Treat the output-cost line (and therefore the
~$1.39 Gemini total) as accurate to roughly ±15-20% until cross-checked
against Billing Reports directly.

**To get the true, GCP-billed dollar figure** (not the token-rate
calculation above): GCP Console → Billing → Reports, filtered to
`contacts-classification` and the 2026-08-26–2026-08-27 window. This
requires opening the console UI — it wasn't accessible via the CLI/API in
this session (no BigQuery billing export was configured for this project),
so the numbers above are the best available without that step.

## What incurs cost (reference)

| Resource | Pricing basis | Notes |
|---|---|---|
| Vertex AI — Gemini 2.5 Flash | per input/output token | `gemini_classifier.py`, thinking disabled (`thinking_budget=0`) to avoid hidden reasoning-token cost |
| Cloud Run (2 services + 1 job) | per vCPU-second / memory-GB-second while handling requests, scales to zero | `min_instance_count = 0` — no cost while idle |
| BigQuery | storage (negligible at this scale) + query bytes scanned | the weekly report query scans a 7-day window |
| Cloud Scheduler | per job | first 3 jobs/month are free |
| Artifact Registry | storage for the container image | grows with each pushed image version — worth pruning old digests before a long-running deployment |

## Real request counts (from Cloud Run's own request_count metric)

| Service | 2xx | 5xx (transient, all recovered on retry) | 4xx |
|---|---|---|---|
| triage-classifier | ~1,210 | 4 | 1 |
| final-classifier | ~967 | 141 (the OOM crash loop before the 2Gi memory fix) | — |

The 141 `final-classifier` 5xx responses were all before the memory fix
(1Gi → 2Gi); after that change the remaining run had only isolated,
successfully-retried failures. See `docs/engineering_log.md`.

This replaces the placeholder cost section in the README.
