# §5.1 — three services. Every sizing number here is from that table, not invented.

resource "google_cloud_run_v2_service" "debt_api" {
  name     = "debt-api"
  location = var.region
  # allUsers invoker is safe ONLY in combination with this ingress restriction.
  ingress  = "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"
  labels   = local.labels

  template {
    service_account                  = google_service_account.sa["debt-api-sa"].email
    execution_environment            = "EXECUTION_ENVIRONMENT_GEN2"
    # Python builds and serialises wide customer rows on one vCPU. Four concurrent
    # requests keep queueing bounded without letting forty CPU-heavy responses
    # contend inside one instance.
    max_instance_request_concurrency = 4
    timeout                          = "300s"

    scaling {
      min_instance_count = local.api_min_instances
      max_instance_count = local.api_max_instances
    }

    vpc_access {
      connector = google_vpc_access_connector.debt_vpcc.id
      egress    = "ALL_TRAFFIC"
    }

    containers {
      image = "${var.region}-docker.pkg.dev/${var.project_id}/debt/debt-api:${var.image_tag}"

      resources {
        limits = {
          cpu    = "1"
          memory = "1Gi"
        }
        cpu_idle          = local.api_cpu_idle
        startup_cpu_boost = true
      }

      env {
        name  = "ENV"
        value = var.env
      }
      dynamic "env" {
        for_each = var.env == "stg" ? {
          SLOW_REQUEST_MS = "1200"
          SLOW_SQL_MS     = "100"
        } : {}
        content {
          name  = env.key
          value = env.value
        }
      }
      env {
        name  = "DB_INSTANCE"
        value = google_sql_database_instance.pg.connection_name
      }
      env {
        name  = "DOCS_BUCKET"
        value = google_storage_bucket.b["docs"].name
      }
      # CF1 is unresolved: the penalty rate is configuration, never a literal in code,
      # and PENALTY invoicing stays off until Legal rules. See app/config.py.
      env {
        name  = "PENALTY_INVOICING_ENABLED"
        value = "false"
      }

      dynamic "env" {
        for_each = local.api_secrets
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.s[env.key].secret_id
              version = "latest"
            }
          }
        }
      }

      startup_probe {
        http_get { path = "/healthz" }
        period_seconds    = 5
        failure_threshold = 12 # 60 s budget
      }

      liveness_probe {
        http_get { path = "/healthz" }
        period_seconds    = 30
        failure_threshold = 3
      }
    }
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }
}

resource "google_cloud_run_v2_service" "debt_web" {
  name     = "debt-web"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"
  labels   = local.labels

  template {
    service_account                  = google_service_account.sa["debt-web-sa"].email
    execution_environment            = "EXECUTION_ENVIRONMENT_GEN2"
    max_instance_request_concurrency = 200
    timeout                          = "30s"

    scaling {
      min_instance_count = local.web_min_instances
      max_instance_count = local.web_max_instances
    }

    containers {
      image = "${var.region}-docker.pkg.dev/${var.project_id}/debt/debt-web:${var.image_tag}"
      resources {
        limits = {
          cpu    = "1"
          memory = "256Mi"
        }
        cpu_idle = true
      }
      startup_probe {
        http_get { path = "/healthz" }
        period_seconds    = 5
        failure_threshold = 6
      }
    }
  }
}

resource "google_cloud_run_v2_service" "clamav_scanner" {
  name     = "clamav-scanner"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_INTERNAL_ONLY"
  labels   = local.labels

  template {
    service_account       = google_service_account.sa["clamav-scanner-sa"].email
    execution_environment = "EXECUTION_ENVIRONMENT_GEN2"
    # Concurrency 1 on purpose: memory headroom is the binding constraint, and an
    # OOM kill loses in-flight verdicts. Throughput comes from instances.
    max_instance_request_concurrency = 1
    timeout                          = "300s"

    scaling {
      min_instance_count = var.env == "prd" ? 1 : 0
      max_instance_count = var.env == "prd" ? 5 : 2
    }

    vpc_access {
      connector = google_vpc_access_connector.debt_vpcc.id
      egress    = "ALL_TRAFFIC" # freshclam goes out through NAT
    }

    containers {
      image = "${var.region}-docker.pkg.dev/${var.project_id}/debt/clamav-scanner:${var.image_tag}"
      resources {
        limits = {
          cpu    = "1"
          memory = "3Gi"
        }
        cpu_idle          = true
        startup_cpu_boost = true
      }
      startup_probe {
        http_get { path = "/healthz" }
        period_seconds    = 10
        failure_threshold = 30 # 300 s for clamd to load signatures
      }
    }
  }
}
