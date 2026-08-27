variable "gcp_project_id" {
  description = "GCP project ID (e.g. contacts-classification)"
  type        = string
}

variable "gcp_region" {
  description = "Region for Cloud Run, BigQuery, and Cloud Scheduler"
  type        = string
  default     = "europe-west1"
}

variable "vertex_ai_location" {
  description = "Vertex AI / Gemini endpoint location"
  type        = string
  default     = "global"
}

variable "bq_dataset" {
  description = "BigQuery dataset name for classified tickets"
  type        = string
  default     = "novacart_support"
}

variable "use_llm_classifier" {
  description = "Whether the Cloud Run services also call Gemini via Vertex AI. Leave false to deploy router-only and avoid Vertex AI spend."
  type        = bool
  default     = false
}

variable "container_image" {
  description = "Full Artifact Registry image URI, built and pushed by infra/deploy.sh before terraform apply (e.g. europe-west1-docker.pkg.dev/<project>/novacart/classifier:latest)"
  type        = string
}
