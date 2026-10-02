terraform {

  required_version = ">= 1.6.0"
  required_providers {

    google = { source = "hashicorp/google", version = "~> 6.0" }

  }

  backend "gcs" {
    prefix = "production"
  }


}

provider "google" {
  project = var.project_id
}

data "google_project" "current" {
  project_id = var.project_id
}


variable "project_id" {

  type = string
  validation {

    condition     = var.project_id != "dept-collection-508109" && can(regex("^volt-debt-prd", var.project_id))
    error_message = "Use a dedicated volt-debt-prd project; staging is forbidden."

  }


}

variable "region" {
  default = "asia-southeast1"
}

variable "hostname" {
  default = "debt.volt.co.th"
}

variable "enable_workloads" {

  type    = bool
  default = false
}

variable "go_live" {

  type    = bool
  default = false
}

variable "api_image" {

  type    = string
  default = ""
}

variable "web_image" {

  type    = string
  default = ""
}

variable "scanner_image" {

  type    = string
  default = ""
}

variable "secret_versions" {

  type    = map(string)
  default = {}
  validation {

    condition     = alltrue([for version in values(var.secret_versions) : can(regex("^[1-9][0-9]*$", version))])
    error_message = "Pin numeric Secret Manager versions, never latest."

  }


}

variable "notification_emails" {

  type    = set(string)
  default = []
}

variable "billing_account" {

  type    = string
  default = ""
}

variable "budget_currency" {

  type    = string
  default = "THB"
}

variable "monthly_budget" {

  type    = number
  default = 15000
}

variable "candidate_test_subjects" {
  type    = set(string)
  default = []
}
variable "active_revisions" {
  type        = map(string)
  default     = {}
  description = "Pin previous API/web revisions while deploying the next candidate."
}
variable "canary_percent" {
  type    = number
  default = 0
  validation {
    condition     = contains([0, 10, 50, 100], var.canary_percent)
    error_message = "Use the reviewed 0, 10, 50, 100 rollout steps."
  }
}
resource "terraform_data" "go_live_guard" {
  input = var.go_live
  lifecycle {
    precondition {
      condition     = !var.go_live || (var.enable_workloads && var.billing_account != "" && length(var.notification_emails) > 0)
      error_message = "Go live requires deployed workloads, billing budget and incident recipients. Verify measured release gates with release.py before apply."
    }
  }
}


locals {

  labels               = { app = "volt-debt", env = "prd", managed_by = "terraform" }
  worker_url           = "https://debt-worker-${data.google_project.current.number}.${var.region}.run.app"
  scanner_url          = "https://debt-scanner-${data.google_project.current.number}.${var.region}.run.app"
  account_names        = toset(["api", "web", "worker", "migrate", "scanner", "tasks", "scheduler", "build"])
  secret_names         = toset(["AUTH_SESSION_SECRET", "AUTH_ALLOWLIST", "GOOGLE_CLIENT_ID", "ODOO_URL", "ODOO_DB", "ODOO_LOGIN", "ODOO_API_KEY", "MIGRATION_DATABASE_URL"])
  runtime_secret_names = setsubtract(local.secret_names, toset(["MIGRATION_DATABASE_URL"]))

}


resource "google_project_service" "apis" {

  for_each           = toset(["run.googleapis.com", "sqladmin.googleapis.com", "compute.googleapis.com", "servicenetworking.googleapis.com", "secretmanager.googleapis.com", "artifactregistry.googleapis.com", "cloudbuild.googleapis.com", "cloudtasks.googleapis.com", "cloudscheduler.googleapis.com", "monitoring.googleapis.com", "logging.googleapis.com", "iamcredentials.googleapis.com"])
  service            = each.key
  disable_on_destroy = false

}

resource "google_artifact_registry_repository" "images" {

  location      = var.region
  repository_id = "debt"
  format        = "DOCKER"
  labels        = local.labels
  depends_on    = [google_project_service.apis]

}

resource "google_service_account" "workload" {

  for_each     = local.account_names
  account_id   = "debt-${each.key}"
  display_name = "Production debt ${each.key}"
  depends_on   = [google_project_service.apis]

}

resource "google_secret_manager_secret" "configuration" {

  for_each  = local.secret_names
  secret_id = each.key
  labels    = local.labels
  replication {

    auto {

    }


  }

  depends_on = [google_project_service.apis]

}

resource "google_secret_manager_secret_iam_member" "runtime" {

  for_each  = { for item in setproduct(toset(["api", "worker"]), local.runtime_secret_names) : "${item[0]}:${item[1]}" => item }
  secret_id = google_secret_manager_secret.configuration[each.value[1]].id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.workload[each.value[0]].email}"

}

resource "google_secret_manager_secret_iam_member" "migration" {

  secret_id = google_secret_manager_secret.configuration["MIGRATION_DATABASE_URL"].id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.workload["migrate"].email}"

}

resource "google_project_iam_member" "database_login" {

  for_each = toset(["api", "worker"])
  project  = var.project_id
  role     = "roles/cloudsql.instanceUser"
  member   = "serviceAccount:${google_service_account.workload[each.key].email}"

}

resource "google_project_iam_member" "task_enqueue" {

  project = var.project_id
  role    = "roles/cloudtasks.enqueuer"
  member  = "serviceAccount:${google_service_account.workload["worker"].email}"

}

resource "google_service_account_iam_member" "task_identity" {

  service_account_id = google_service_account.workload["tasks"].name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.workload["worker"].email}"

}


variable "enable_migration" {
  type    = bool
  default = false
}

resource "google_storage_bucket" "build_source" {
  name                        = "${var.project_id}-build-source"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false
  lifecycle_rule {
    condition { age = 7 }
    action { type = "Delete" }
  }
}
resource "google_storage_bucket_iam_member" "build_source" {
  bucket = google_storage_bucket.build_source.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.workload["build"].email}"
}
resource "google_storage_bucket_iam_member" "build_report" {
  bucket = google_storage_bucket.private["exports"].name
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${google_service_account.workload["build"].email}"
}
resource "google_artifact_registry_repository_iam_member" "build" {
  location   = var.region
  repository = google_artifact_registry_repository.images.name
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${google_service_account.workload["build"].email}"
}
resource "google_project_iam_member" "build_logs" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.workload["build"].email}"
}
