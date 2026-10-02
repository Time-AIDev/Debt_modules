# §9.2 — one service account per workload, least privilege. No SA keys anywhere.

locals {
  service_accounts = {
    "debt-api-sa"        = "debt-api Cloud Run service"
    "debt-web-sa"        = "debt-web nginx static service"
    "clamav-scanner-sa"  = "clamav-scanner, Eventarc-invoked only"
    "debt-tasks-sa"      = "Cloud Tasks OIDC caller for /internal/tasks/*"
    "debt-scheduler-sa"  = "Cloud Scheduler OIDC caller for /internal/jobs/*"
    "pubsub-push-sa"     = "Pub/Sub push OIDC caller for /internal/pubsub/*"
    "eventarc-sa"        = "Eventarc trigger for GCS finalize -> clamav-scanner"
  }
}

resource "google_service_account" "sa" {
  for_each     = local.service_accounts
  account_id   = each.key
  display_name = each.value
}

# debt-api reads its own secrets, signs URLs, publishes events, enqueues tasks.
locals {
  api_roles = [
    "roles/cloudsql.client",
    "roles/secretmanager.secretAccessor",
    "roles/pubsub.publisher",
    "roles/cloudtasks.enqueuer",
    "roles/cloudtrace.agent",
    # Signing time-limited URLs for the private docs bucket without an SA key
    # (ADR-007 / §8.2): the SA signs blobs as itself.
    "roles/iam.serviceAccountTokenCreator",
  ]
}

resource "google_project_iam_member" "api" {
  for_each = toset(local.api_roles)
  project  = var.project_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.sa["debt-api-sa"].email}"
}

# Only eventarc-sa may invoke the scanner (§5.1 IAM invoker row).
resource "google_cloud_run_v2_service_iam_member" "scanner_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.clamav_scanner.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.sa["eventarc-sa"].email}"
}

# debt-api and debt-web are allUsers at the Cloud Run layer *because ingress is
# restricted to the load balancer* and the app authenticates every request itself.
# Removing the ingress restriction without changing this would expose the API.
resource "google_cloud_run_v2_service_iam_member" "api_public" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.debt_api.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
