# §7.3 — every job runs in Asia/Bangkok. A job STARTER only enqueues chunked
# Cloud Tasks and returns in seconds; no request may run longer than 5 minutes.

locals {
  jobs = {
    "odoo-reconciliation" = { schedule = "0 2 * * *", desc = "02:00 nightly reconciliation poll — the safety net behind the Odoo activation webhook (ADR-012)" }
    "today-list-build"    = { schedule = "30 2 * * *", desc = "02:30 build each officer's Today List for the day" }
    "fee-state-check"     = { schedule = "50 3 * * *", desc = "03:50 nightly fee-state check (REQ-MNY-036). The detection signal RB-MNY-02 depends on — without it the seven fee states fail silently" }
    "dpd-roll"            = { schedule = "10 2 * * *", desc = "02:10 roll DPD and aging buckets" }
    "outbox-relay-sweep"  = { schedule = "* * * * *", desc = "Outbox relay safety net every minute; in staging it is the ONLY relay" }
    "hold-expiry"         = { schedule = "0 * * * *", desc = "Hourly hold expiry. A failure does NOT mean expired holds keep freezing DPD — that is true only for service-issue holds. An unreleased PERMIT hold freezes nothing; it suppresses collection on an account that keeps accruing" }
  }
}

resource "google_cloud_scheduler_job" "j" {
  for_each         = local.jobs
  name             = each.key
  region           = var.region
  schedule         = each.value.schedule
  time_zone        = "Asia/Bangkok"
  description      = each.value.desc
  attempt_deadline = "320s"

  retry_config {
    retry_count          = 3
    min_backoff_duration = "10s"
    max_backoff_duration = "300s"
  }

  http_target {
    http_method = "POST"
    uri         = "${google_cloud_run_v2_service.debt_api.uri}/internal/jobs/${each.key}/start"
    oidc_token {
      service_account_email = google_service_account.sa["debt-scheduler-sa"].email
      audience              = google_cloud_run_v2_service.debt_api.uri
    }
  }
}

resource "google_cloud_tasks_queue" "q" {
  for_each = toset(["odoo-sync", "peak-post", "doc-render", "notify"])
  name     = each.value
  location = var.region

  rate_limits {
    max_dispatches_per_second = 10
    max_concurrent_dispatches = 20
  }

  retry_config {
    max_attempts       = 10
    min_backoff        = "5s"
    max_backoff        = "600s"
    max_doublings      = 5
    max_retry_duration = "86400s"
  }
}
