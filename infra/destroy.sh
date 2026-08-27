#!/usr/bin/env bash
# Tears down everything infra/deploy.sh created. Run this once you've
# captured the screenshots/GIF for the README — this project isn't meant
# to run 24/7.
set -euo pipefail

cd "$(dirname "$0")"

echo "This will destroy all Terraform-managed resources (Cloud Run services,"
echo "BigQuery dataset + table, Cloud Scheduler job, service accounts)."
read -p "Type 'destroy' to confirm: " confirmation
if [ "$confirmation" != "destroy" ]; then
  echo "Aborted."
  exit 1
fi

terraform destroy
