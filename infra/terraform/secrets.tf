locals {
  api_secrets = {
    "DB_PASSWORD"         = "Cloud SQL application user"
    "WEBHOOK_HMAC_SECRET" = "Odoo Automated Action webhook HMAC (ADR-012)"
    "ODOO_API_KEY"        = "Odoo XML-RPC/JSON-RPC API key"
    "PEAK_CONNECT_ID"     = "PEAK connectId"
    "PEAK_CONNECT_KEY"    = "PEAK connectKey"
    "PEAK_USER_TOKEN"     = "PEAK userToken"
    "IDP_API_KEY"         = "Identity Platform web API key"
  }
}

resource "google_secret_manager_secret" "s" {
  for_each  = local.api_secrets
  secret_id = lower(replace(each.key, "_", "-"))
  labels    = local.labels
  replication {
    user_managed {
      replicas { location = var.region }
    }
  }
}

# Values are never in Terraform. Populate with:
#   gcloud secrets versions add odoo-api-key --data-file=- <<< "$VALUE"
