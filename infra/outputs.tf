output "triage_classifier_url" {
  value = google_cloud_run_v2_service.classifier["triage"].uri
}

output "final_classifier_url" {
  value = google_cloud_run_v2_service.classifier["final"].uri
}

output "bigquery_table" {
  value = "${var.gcp_project_id}.${google_bigquery_dataset.novacart.dataset_id}.${google_bigquery_table.classified_tickets.table_id}"
}
