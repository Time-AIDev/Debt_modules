locals {

  runtime_environment = {
    ENV                    = "prd", AUTH_MODE = "on", AUTH_SESSION_POLICY = "tab", AUTH_ALLOW_TEST_ACCOUNTS = "false",
    PEAK_OUTBOUND_ENABLED  = "false", PENALTY_INVOICING_ENABLED = "false",
    GCP_PROJECT            = var.project_id, GCP_REGION = var.region, TASK_QUEUE = "imports",
    WORKER_AUDIENCE        = local.worker_url,
    TASK_CALLER_EMAIL      = google_service_account.workload["tasks"].email,
    SCHEDULER_CALLER_EMAIL = google_service_account.workload["scheduler"].email,
    UPLOADS_BUCKET         = google_storage_bucket.private["uploads"].name,
    CLEAN_BUCKET           = google_storage_bucket.private["clean"].name,
    DOCS_BUCKET            = google_storage_bucket.private["documents"].name,
    SCANNER_URL            = local.scanner_url,
    DB_POOL_SIZE           = "5", DB_MAX_OVERFLOW = "2", SLOW_SQL_MS = "100", SLOW_REQUEST_MS = "1200",
    PROD_GO_LIVE_ENABLED   = tostring(var.go_live), PROD_CANDIDATE_TEST_SUBJECTS = join(",", var.candidate_test_subjects)
  }
  services = {
    api     = { image = var.api_image, min = 1, max = 3, concurrency = 4, cpu = "1", memory = "2Gi", command = ["uvicorn"], args = ["app.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"], private = false }
    web     = { image = var.web_image, min = 0, max = 2, concurrency = 80, cpu = "1", memory = "256Mi", command = [], args = [], private = false }
    worker  = { image = var.api_image, min = 0, max = 1, concurrency = 1, cpu = "1", memory = "2Gi", command = ["uvicorn"], args = ["app.worker:app", "--host", "0.0.0.0", "--port", "8080"], private = true }
    scanner = { image = var.scanner_image, min = 0, max = 1, concurrency = 1, cpu = "1", memory = "3Gi", command = [], args = [], private = true }
  }

}

resource "google_cloud_run_v2_service" "application" {

  for_each            = var.enable_workloads ? local.services : {}
  name                = "debt-${each.key}"
  location            = var.region
  ingress             = each.value.private ? "INGRESS_TRAFFIC_INTERNAL_ONLY" : "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"
  deletion_protection = true
  labels              = local.labels
  dynamic "traffic" {
    for_each = contains(keys(var.active_revisions), each.key) && var.canary_percent < 100 ? [1] : []
    content {
      type     = "TRAFFIC_TARGET_ALLOCATION_TYPE_REVISION"
      revision = var.active_revisions[each.key]
      percent  = 100 - var.canary_percent
    }
  }
  dynamic "traffic" {
    for_each = !contains(keys(var.active_revisions), each.key) || var.canary_percent > 0 ? [1] : []
    content {
      type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
      percent = contains(keys(var.active_revisions), each.key) ? var.canary_percent : 100
      tag     = "candidate"
    }
  }
  template {

    service_account                  = google_service_account.workload[each.key].email
    max_instance_request_concurrency = each.value.concurrency
    timeout                          = "300s"
    scaling {

      min_instance_count = each.value.min
      max_instance_count = each.value.max
    }

    dynamic "vpc_access" {

      for_each = each.key == "web" ? [] : [1]
      content {

        egress = "ALL_TRAFFIC"
        network_interfaces {

          network    = google_compute_network.private.name
          subnetwork = google_compute_subnetwork.runtime.name
        }


      }


    }

    containers {

      image   = each.value.image
      command = each.value.command
      args    = each.value.args
      resources {

        limits            = { cpu = each.value.cpu, memory = each.value.memory }
        cpu_idle          = true
        startup_cpu_boost = true

      }

      dynamic "env" {

        for_each = contains(["api", "worker"], each.key) ? local.runtime_environment : { ENV = "prd" }
        content {

          name  = env.key
          value = env.value
        }


      }

      dynamic "env" {

        for_each = contains(["api", "worker"], each.key) ? { DATABASE_URL = "postgresql+psycopg://${google_sql_user.runtime[each.key].name}@${google_sql_database_instance.primary.private_ip_address}:5432/debt?sslmode=require" } : {}
        content {

          name  = env.key
          value = env.value
        }


      }

      dynamic "env" {

        for_each = each.key == "scanner" ? { SCANNER_AUDIENCE = local.scanner_url, SCANNER_CALLERS = join(",", [google_service_account.workload["api"].email, google_service_account.workload["worker"].email]) } : {}
        content {

          name  = env.key
          value = env.value
        }


      }

      dynamic "env" {

        for_each = contains(["api", "worker"], each.key) ? local.runtime_secret_names : toset([])
        content {

          name = env.value
          value_source {

            secret_key_ref {

              secret  = google_secret_manager_secret.configuration[env.value].secret_id
              version = lookup(var.secret_versions, env.value, "1")
            }

          }


        }


      }

      startup_probe {

        http_get {
          path = "/livez"
        }

        period_seconds    = 10
        failure_threshold = 30

      }


    }


  }

  lifecycle {

    precondition {

      condition     = can(regex("@sha256:[a-f0-9]{64}$", each.value.image))
      error_message = "Deploy tested immutable image digests."

    }

    precondition {

      condition     = !contains(["api", "worker"], each.key) || alltrue([for name in local.runtime_secret_names : contains(keys(var.secret_versions), name)])
      error_message = "Pin every runtime secret version before enabling workloads."

    }


  }

  depends_on = [google_project_service.apis, google_secret_manager_secret_iam_member.runtime, google_compute_router_nat.egress]

}

resource "google_cloud_run_v2_service_iam_member" "public_edge" {

  for_each = var.enable_workloads ? toset(["api", "web"]) : toset([])
  location = var.region
  name     = google_cloud_run_v2_service.application[each.key].name
  role     = "roles/run.invoker"
  member   = "allUsers"

}

resource "google_cloud_run_v2_service_iam_member" "worker" {

  for_each = var.enable_workloads ? toset(["tasks", "scheduler"]) : toset([])
  location = var.region
  name     = google_cloud_run_v2_service.application["worker"].name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.workload[each.key].email}"

}

resource "google_cloud_run_v2_service_iam_member" "scanner" {

  for_each = var.enable_workloads ? toset(["api", "worker"]) : toset([])
  location = var.region
  name     = google_cloud_run_v2_service.application["scanner"].name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.workload[each.key].email}"

}

resource "google_cloud_run_v2_job" "migration" {

  count               = var.enable_workloads || var.enable_migration ? 1 : 0
  name                = "debt-migrate"
  location            = var.region
  deletion_protection = true
  lifecycle {
    precondition {
      condition     = can(regex("@sha256:[a-f0-9]{64}$", var.api_image)) && contains(keys(var.secret_versions), "MIGRATION_DATABASE_URL")
      error_message = "Pin the migration image digest and admin secret version before enabling migration."
    }
  }
  template {

    template {

      service_account = google_service_account.workload["migrate"].email
      max_retries     = 0
      timeout         = "600s"
      vpc_access {

        egress = "ALL_TRAFFIC"
        network_interfaces {

          network    = google_compute_network.private.name
          subnetwork = google_compute_subnetwork.runtime.name
        }


      }

      containers {

        image   = var.api_image
        command = ["python", "-m", "app.migrate"]
        env {

          name = "DATABASE_URL"
          value_source {

            secret_key_ref {

              secret  = "MIGRATION_DATABASE_URL"
              version = lookup(var.secret_versions, "MIGRATION_DATABASE_URL", "1")
            }

          }

        }

        env {

          name  = "DB_RUNTIME_ROLES"
          value = join(",", [for user in google_sql_user.runtime : user.name])
        }


      }


    }


  }


}

resource "google_cloud_tasks_queue" "imports" {

  name     = "imports"
  location = var.region
  rate_limits {

    max_dispatches_per_second = 1
    max_concurrent_dispatches = 1
  }

  retry_config {

    max_attempts       = 10
    min_backoff        = "10s"
    max_backoff        = "600s"
    max_retry_duration = "86400s"
  }

  depends_on = [google_project_service.apis]

}

resource "google_cloud_scheduler_job" "relay" {

  count     = var.enable_workloads ? 1 : 0
  name      = "debt-outbox-relay"
  region    = var.region
  schedule  = "* * * * *"
  time_zone = "Asia/Bangkok"
  paused    = false
  http_target {

    http_method = "POST"
    uri         = "${local.worker_url}/internal/jobs/relay"
    oidc_token {

      service_account_email = google_service_account.workload["scheduler"].email
      audience              = local.worker_url
    }


  }


}
