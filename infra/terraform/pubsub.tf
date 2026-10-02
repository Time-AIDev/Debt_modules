# §7.1 — transactional outbox relay publishes here (ADR-004).
# NOTE for consumers: after v2.x, band_set_code travels beside every aging_bucket.
# A bucket code alone no longer identifies a band. Three event types dual-publish
# v1 and v2 for at least one release and 30 days; for a PERMIT hold, v1 is not
# emitted at all, because a v1 consumer would read it as a hold that freezes the
# clock and would run the DPD clock during an MEA/PEA delay.

locals {
  topics = [
    "evt.money.dpd_updated",
    "evt.money.payment_received",
    "evt.collections.hold_opened",
    "evt.collections.hold_closed",
    "evt.collections.contact_logged",
    "evt.contract.activated",
  ]
}

resource "google_pubsub_topic" "t" {
  for_each = toset(local.topics)
  name     = each.value
  labels   = local.labels

  message_retention_duration = "604800s" # 7 days
}

resource "google_pubsub_topic" "dead_letter" {
  name   = "evt.dead-letter"
  labels = local.labels
}

resource "google_pubsub_subscription" "push" {
  for_each = toset(local.topics)
  name     = "${each.value}.app-push"
  topic    = google_pubsub_topic.t[each.value].id

  push_config {
    push_endpoint = "${google_cloud_run_v2_service.debt_api.uri}/internal/pubsub/${each.value}"
    oidc_token {
      service_account_email = google_service_account.sa["pubsub-push-sa"].email
    }
  }

  ack_deadline_seconds = 60

  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.dead_letter.id
    max_delivery_attempts = 10
  }

  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "600s"
  }
}
