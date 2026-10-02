resource "google_monitoring_notification_channel" "operations" {
  for_each     = var.notification_emails
  display_name = "Debt production on-call"
  type         = "email"
  labels       = { email_address = each.key }
}
locals {
  channels = [for channel in google_monitoring_notification_channel.operations : channel.name]
  thresholds = {
    sql_cpu      = { filter = "resource.type = \"cloudsql_database\" AND metric.type = \"cloudsql.googleapis.com/database/cpu/utilization\"", limit = 0.8, aligner = "ALIGN_MEAN" }
    sql_memory   = { filter = "resource.type = \"cloudsql_database\" AND metric.type = \"cloudsql.googleapis.com/database/memory/utilization\"", limit = 0.85, aligner = "ALIGN_MEAN" }
    sql_disk     = { filter = "resource.type = \"cloudsql_database\" AND metric.type = \"cloudsql.googleapis.com/database/disk/utilization\"", limit = 0.8, aligner = "ALIGN_MEAN" }
    task_backlog = { filter = "resource.type = \"cloud_tasks_queue\" AND metric.type = \"cloudtasks.googleapis.com/queue/depth\"", limit = 10, aligner = "ALIGN_MAX" }
  }
}
resource "google_monitoring_alert_policy" "capacity" {
  for_each              = local.thresholds
  display_name          = "Debt production ${each.key}"
  combiner              = "OR"
  enabled               = length(local.channels) > 0
  notification_channels = local.channels
  conditions {
    display_name = each.key
    condition_threshold {
      filter          = each.value.filter
      comparison      = "COMPARISON_GT"
      threshold_value = each.value.limit
      duration        = "300s"
      aggregations {
        alignment_period   = "60s"
        per_series_aligner = each.value.aligner
      }
      trigger { count = 1 }
    }
  }
}
resource "google_monitoring_uptime_check_config" "api" {
  count        = var.enable_workloads ? 1 : 0
  display_name = "Debt production readiness"
  timeout      = "10s"
  period       = "60s"
  http_check {
    path         = "/readyz"
    port         = 443
    use_ssl      = true
    validate_ssl = true
  }
  monitored_resource {
    type   = "uptime_url"
    labels = { project_id = var.project_id, host = var.hostname }
  }
}
resource "google_monitoring_alert_policy" "availability" {
  count                 = var.enable_workloads ? 1 : 0
  display_name          = "Debt production readiness failed"
  combiner              = "OR"
  notification_channels = local.channels
  enabled               = length(local.channels) > 0
  conditions {
    display_name = "Readiness failed"
    condition_threshold {
      filter          = "metric.type=\"monitoring.googleapis.com/uptime_check/check_passed\" AND resource.type=\"uptime_url\" AND metric.label.check_id=\"${google_monitoring_uptime_check_config.api[0].uptime_check_id}\""
      comparison      = "COMPARISON_LT"
      threshold_value = 1
      duration        = "120s"
      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_FRACTION_TRUE"
      }
      trigger { count = 2 }
    }
  }
}
resource "google_billing_budget" "production" {
  count           = var.billing_account != "" ? 1 : 0
  billing_account = var.billing_account
  display_name    = "Volt Debt production"
  budget_filter {
    projects               = ["projects/${data.google_project.current.number}"]
    credit_types_treatment = "EXCLUDE_ALL_CREDITS"
  }
  amount {
    specified_amount {
      currency_code = var.budget_currency
      units         = tostring(var.monthly_budget)
    }
  }
  threshold_rules { threshold_percent = 0.5 }
  threshold_rules { threshold_percent = 0.8 }
  threshold_rules { threshold_percent = 1.0 }
  all_updates_rule { monitoring_notification_channels = local.channels }
}

resource "google_logging_metric" "workbook_latency" {
  name   = "debt_workbook_latency_ms"
  filter = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"debt-api\" AND jsonPayload.event=\"production_request\" AND jsonPayload.route=\"/v1/workbook\""
  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "DISTRIBUTION"
    unit        = "ms"
  }
  value_extractor = "EXTRACT(jsonPayload.latency_ms)"
  bucket_options {
    explicit_buckets { bounds = [100, 250, 500, 1000, 1500, 2000, 3000, 5000, 10000, 20000] }
  }
  depends_on = [google_project_service.apis]
}
resource "google_monitoring_alert_policy" "workbook_latency" {
  display_name          = "Debt workbook p95 above 2 seconds"
  combiner              = "OR"
  enabled               = length(local.channels) > 0
  notification_channels = local.channels
  conditions {
    display_name = "Workbook p95"
    condition_threshold {
      filter          = "resource.type=\"cloud_run_revision\" AND metric.type=\"logging.googleapis.com/user/${google_logging_metric.workbook_latency.name}\""
      comparison      = "COMPARISON_GT"
      threshold_value = 2000
      duration        = "300s"
      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_PERCENTILE_95"
      }
      trigger { count = 1 }
    }
  }
}
resource "google_monitoring_alert_policy" "api_errors" {
  display_name          = "Debt API 5xx above 1 percent"
  combiner              = "OR"
  enabled               = length(local.channels) > 0
  notification_channels = local.channels
  conditions {
    display_name = "Unexpected server errors"
    condition_threshold {
      filter             = "resource.type=\"cloud_run_revision\" AND resource.label.service_name=\"debt-api\" AND metric.type=\"run.googleapis.com/request_count\" AND metric.label.response_code_class=\"5xx\""
      denominator_filter = "resource.type=\"cloud_run_revision\" AND resource.label.service_name=\"debt-api\" AND metric.type=\"run.googleapis.com/request_count\""
      comparison         = "COMPARISON_GT"
      threshold_value    = 0.01
      duration           = "300s"
      aggregations {
        alignment_period     = "60s"
        per_series_aligner   = "ALIGN_RATE"
        cross_series_reducer = "REDUCE_SUM"
      }
      denominator_aggregations {
        alignment_period     = "60s"
        per_series_aligner   = "ALIGN_RATE"
        cross_series_reducer = "REDUCE_SUM"
      }
      trigger { count = 1 }
    }
  }
}
