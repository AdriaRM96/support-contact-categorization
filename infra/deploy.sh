#!/usr/bin/env bash
# One-time deploy: build the classifier image, push it, apply Terraform,
# then remind you how to run the demo and where to tear it down afterward.
#
# This project is meant to run for a short demo window, not 24/7 — the
# GCP project's billing is a Free Trial account. Review what this script
# does before running it; it provisions billable resources.
#
# Usage:
#   cd infra
#   cp terraform.tfvars.example terraform.tfvars   # fill in real values
#   ./deploy.sh
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -f terraform.tfvars ]; then
  echo "infra/terraform.tfvars not found. Copy terraform.tfvars.example and fill in real values first." >&2
  exit 1
fi

PROJECT_ID=$(grep -E '^gcp_project_id' terraform.tfvars | sed -E 's/.*"(.*)"/\1/')
REGION=$(grep -E '^gcp_region' terraform.tfvars | sed -E 's/.*"(.*)"/\1/')
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/novacart/classifier:latest"

echo "== 1/4: enabling required APIs and creating Artifact Registry repo (via terraform apply -target) =="
terraform init
terraform apply -target=google_project_service.apis -target=google_artifact_registry_repository.images -auto-approve

echo "== 2/4: building and pushing the classifier image =="
gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet
# --platform linux/amd64: Cloud Run requires amd64 images. Without this,
# building on Apple Silicon produces an arm64 image Cloud Run rejects.
docker build --platform linux/amd64 -f service/Dockerfile -t "${IMAGE}" ..
docker push "${IMAGE}"

echo "== 3/4: applying the rest of the infra =="
terraform apply -auto-approve

echo "== 4/4: done =="
terraform output
echo ""
echo "Next steps:"
echo "  1. Dry-run the simulator locally first: python simulate_tickets.py --dry-run --limit 5"
echo "  2. Point it at the deployed services:"
echo "       python simulate_tickets.py --triage-url \$(terraform output -raw triage_classifier_url) \\"
echo "                                   --final-url \$(terraform output -raw final_classifier_url)"
echo "  3. Capture screenshots/a GIF of the dashboard and the weekly report for the README."
echo "  4. When done, tear everything down: ./destroy.sh"
