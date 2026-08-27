# NovaCart support contact categorisation — cloud pipeline.
#
# Deploy-once pattern: this is meant to run for a short demo window (long
# enough to run infra/simulate_tickets.py and capture screenshots/a GIF for
# the README), then be torn down with destroy.sh. It is not meant to run
# 24/7 — the free-trial billing account only makes sense for a bounded run.

locals {
  services = {
    triage = "triage-classifier"
    final  = "final-classifier"
  }
}

resource "google_project_service" "apis" {
  for_each = toset([
    "run.googleapis.com",
    "aiplatform.googleapis.com",
    "bigquery.googleapis.com",
    "cloudscheduler.googleapis.com",
    "artifactregistry.googleapis.com",
  ])
  service            = each.value
  disable_on_destroy = false
}

resource "google_artifact_registry_repository" "images" {
  location      = var.gcp_region
  repository_id = "novacart"
  format        = "DOCKER"
  depends_on    = [google_project_service.apis]
}

# --- runtime identity: no downloaded key file, Cloud Run uses this SA's
# attached identity directly (workload identity) ---
resource "google_service_account" "classifier_runtime" {
  account_id   = "novacart-classifier-runtime"
  display_name = "NovaCart classifier services runtime identity"
}

resource "google_project_iam_member" "runtime_bigquery" {
  project = var.gcp_project_id
  role    = "roles/bigquery.dataEditor"
  member  = "serviceAccount:${google_service_account.classifier_runtime.email}"
}

# dataEditor alone can read/write table rows but cannot RUN a query --
# report.py's weekly summary query needs bigquery.jobs.create, which only
# jobUser grants. Missing this caused the weekly-report Job to fail with a
# 403 on its first real execution.
resource "google_project_iam_member" "runtime_bigquery_jobuser" {
  project = var.gcp_project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.classifier_runtime.email}"
}

resource "google_project_iam_member" "runtime_vertex_ai" {
  project = var.gcp_project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.classifier_runtime.email}"
}

# --- BigQuery: stores both the router's and Gemini's prediction per ticket ---
resource "google_bigquery_dataset" "novacart" {
  dataset_id = var.bq_dataset
  location   = var.gcp_region
  depends_on = [google_project_service.apis]
}

resource "google_bigquery_table" "classified_tickets" {
  dataset_id          = google_bigquery_dataset.novacart.dataset_id
  table_id            = "classified_tickets"
  deletion_protection = false # this is a deploy-once demo project; teardown must be able to remove it

  schema = jsonencode([
    { name = "ticket_id", type = "INTEGER", mode = "REQUIRED" },
    { name = "stage", type = "STRING", mode = "REQUIRED" },
    { name = "router_category", type = "STRING", mode = "NULLABLE" },
    { name = "gemini_category", type = "STRING", mode = "NULLABLE" },
    { name = "gemini_confidence", type = "FLOAT", mode = "NULLABLE" },
    { name = "gemini_reasoning", type = "STRING", mode = "NULLABLE" },
    { name = "gemini_latency_ms", type = "INTEGER", mode = "NULLABLE" },
    { name = "taxonomy_version", type = "INTEGER", mode = "NULLABLE" },
    { name = "classified_at", type = "TIMESTAMP", mode = "REQUIRED" },
  ])
}

# --- Cloud Run services: triage-classifier and final-classifier ---
resource "google_cloud_run_v2_service" "classifier" {
  for_each = local.services

  name     = each.value
  location = var.gcp_region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.classifier_runtime.email

    containers {
      image = var.container_image

      env {
        name  = "STAGE"
        value = each.key
      }
      env {
        name  = "GCP_PROJECT_ID"
        value = var.gcp_project_id
      }
      env {
        name  = "BQ_DATASET"
        value = google_bigquery_dataset.novacart.dataset_id
      }
      env {
        name  = "USE_LLM_CLASSIFIER"
        value = tostring(var.use_llm_classifier)
      }

      resources {
        limits = {
          cpu = "1"
          # 1Gi was not enough headroom under real load: confirmed via Cloud
          # Run logs showing repeated OOM kills at ~1030-1120MiB usage
          # (baseline ~600MB idle + TF-IDF vectorizing + genai client +
          # gunicorn overhead pushes past 1Gi once actual traffic hits it,
          # even though it looked fine in the earlier lightweight tests).
          memory = "2Gi"
        }
      }

      # Empirically, a custom HTTP startup_probe on this project/platform
      # version left the revision marked Ready (and passing Cloud Run's own
      # internal probe) but never reachable from the public *.run.app edge
      # -- confirmed by A/B testing against control services with no custom
      # probe, which worked immediately. Reverted to the platform default
      # (TCP probe on the container port), which is what every working
      # control deploy used.
    }

    scaling {
      min_instance_count = 0
      max_instance_count = 2
    }
  }

  depends_on = [google_bigquery_table.classified_tickets]
}

# Allow unauthenticated calls so infra/simulate_tickets.py can hit these
# directly for the demo — fine for a short-lived, non-sensitive demo
# deployment; not a pattern to carry into a real production service.
resource "google_cloud_run_v2_service_iam_member" "public_invoke" {
  for_each = google_cloud_run_v2_service.classifier
  name     = each.value.name
  location = each.value.location
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# --- Weekly summary report: a Cloud Run Job, triggered by Cloud Scheduler ---
resource "google_cloud_run_v2_job" "weekly_report" {
  name     = "weekly-report"
  location = var.gcp_region

  template {
    template {
      service_account = google_service_account.classifier_runtime.email
      containers {
        image   = var.container_image
        command = ["python", "report.py"]
        env {
          name  = "GCP_PROJECT_ID"
          value = var.gcp_project_id
        }
        env {
          name  = "BQ_DATASET"
          value = google_bigquery_dataset.novacart.dataset_id
        }
      }
      max_retries = 1
    }
  }
}

resource "google_service_account" "scheduler_invoker" {
  account_id   = "novacart-scheduler-invoker"
  display_name = "Cloud Scheduler -> weekly-report job invoker"
}

resource "google_cloud_run_v2_job_iam_member" "scheduler_can_run" {
  name     = google_cloud_run_v2_job.weekly_report.name
  location = google_cloud_run_v2_job.weekly_report.location
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.scheduler_invoker.email}"
}

resource "google_cloud_scheduler_job" "weekly_report_trigger" {
  name      = "weekly-report-trigger"
  region    = var.gcp_region
  schedule  = "0 8 * * 1" # every Monday 08:00
  time_zone = "Europe/Madrid"

  http_target {
    http_method = "POST"
    uri         = "https://${var.gcp_region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.gcp_project_id}/jobs/${google_cloud_run_v2_job.weekly_report.name}:run"

    oauth_token {
      service_account_email = google_service_account.scheduler_invoker.email
    }
  }

  depends_on = [google_project_service.apis]
}
