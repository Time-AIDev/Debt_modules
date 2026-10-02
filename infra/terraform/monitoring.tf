# Customer-list SLO telemetry. The application writes one PII-free structured row
# per workbook request (plus other slow requests); this metric keeps the workbook
# route and extracts latency.
resource "google_logging_metric" "workbook_latency" {
  name        = "workbook_latency_ms"
  description = "Backend latency of GET /v1/workbook, in milliseconds"
  filter = join(" AND ", [
    "resource.type=\"cloud_run_revision\"",
    "resource.labels.service_name=\"debt-api\"",
    "jsonPayload.metric=\"http_server_duration_ms\"",
    "jsonPayload.method=\"GET\"",
    "jsonPayload.route=\"/v1/workbook\"",
  ])
  value_extractor = "EXTRACT(jsonPayload.elapsed_ms)"

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "DISTRIBUTION"
    unit        = "ms"
  }

  bucket_options {
    exponential_buckets {
      num_finite_buckets = 18
      growth_factor      = 2
      scale              = 1
    }
  }
}

locals {
  workbook_latency_alerts = {
    warning = {
      threshold_ms = 1500
      duration     = "300s"
    }
    slo_breach = {
      threshold_ms = 2000
      duration     = "300s"
    }
  }
}

resource "google_monitoring_alert_policy" "workbook_latency" {
  for_each     = local.workbook_latency_alerts
  display_name = "Customer list p95 ${each.key} (${each.value.threshold_ms} ms)"
  combiner     = "OR"

  documentation {
    content   = "GET /v1/workbook p95 exceeded ${each.value.threshold_ms} ms for five minutes. Inspect the structured phases_ms fields before changing database capacity."
    mime_type = "text/markdown"
  }

  conditions {
    display_name = "Workbook p95 > ${each.value.threshold_ms} ms"
    condition_threshold {
      filter = join(" AND ", [
        "metric.type=\"logging.googleapis.com/user/${google_logging_metric.workbook_latency.name}\"",
        "resource.type=\"cloud_run_revision\"",
      ])
      comparison      = "COMPARISON_GT"
      threshold_value = each.value.threshold_ms
      duration        = each.value.duration

      aggregations {
        alignment_period     = "300s"
        per_series_aligner   = "ALIGN_PERCENTILE_95"
        cross_series_reducer = "REDUCE_MAX"
        group_by_fields      = ["resource.label.service_name"]
      }

      trigger {
        count = 1
      }
    }
  }

  alert_strategy {
    auto_close = "1800s"
  }

  user_labels = {
    service  = "debt-api"
    slo      = "customer-list"
    severity = each.key
  }
}

resource "google_monitoring_dashboard" "customer_list" {
  dashboard_json = jsonencode({
    displayName = "Volt Debt — Customer list SLO"
    gridLayout = {
      columns = 1
      widgets = [{
        title = "GET /v1/workbook p95 latency"
        xyChart = {
          dataSets = [{
            plotType  = "LINE"
            targetAxis = "Y1"
            timeSeriesQuery = {
              timeSeriesFilter = {
                filter = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.workbook_latency.name}\" AND resource.type=\"cloud_run_revision\""
                aggregation = {
                  alignmentPeriod     = "300s"
                  perSeriesAligner    = "ALIGN_PERCENTILE_95"
                  crossSeriesReducer  = "REDUCE_MAX"
                  groupByFields       = ["resource.label.service_name"]
                }
              }
            }
          }]
          thresholds = [
            { value = 1500, color = "YELLOW", direction = "ABOVE", label = "warning" },
            { value = 2000, color = "RED", direction = "ABOVE", label = "SLO breach" },
          ]
          yAxis = { label = "milliseconds", scale = "LINEAR" }
        }
      }]
    }
  })
}
