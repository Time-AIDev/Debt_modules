# §8.1 — private buckets, uniform access, CMEK. ADR-007: GCS is the system of
# record for generated documents; Drive is a mirror, never the authority.

resource "google_kms_key_ring" "debt" {
  name     = "debt-${var.env}"
  location = var.region
}

resource "google_kms_crypto_key" "storage" {
  name            = "debt-storage"
  key_ring        = google_kms_key_ring.debt.id
  rotation_period = "7776000s" # 90 days
  lifecycle {
    prevent_destroy = true
  }
}

locals {
  buckets = {
    "docs"       = "Generated documents, system of record. Read only via signed URL."
    "uploads"    = "Quarantine landing zone; objects move out only after a clean verdict."
    "clean"      = "Post-scan sanitised uploads."
    "exports"    = "Operator-requested CSV/XLSX exports, short lifecycle."
  }
}

resource "google_storage_bucket" "b" {
  for_each                    = local.buckets
  name                        = "volt-debt-${var.env}-${each.key}"
  location                    = var.region
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = var.env != "prd"
  labels                      = local.labels

  versioning { enabled = true }

  encryption {
    default_kms_key_name = google_kms_crypto_key.storage.id
  }

  dynamic "lifecycle_rule" {
    for_each = each.key == "exports" ? [1] : []
    content {
      condition { age = 7 }
      action { type = "Delete" }
    }
  }
}
