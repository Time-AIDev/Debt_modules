# §6.1 — Cloud SQL for PostgreSQL 16, private IP only, CMEK.

resource "google_sql_database_instance" "pg" {
  name                = "debt-pg-${var.env}"
  database_version    = "POSTGRES_16"
  region              = var.region
  deletion_protection = var.env == "prd"

  settings {
    tier              = var.env == "prd" ? "db-custom-4-16384" : "db-custom-2-7680"
    edition           = "ENTERPRISE"
    availability_type = var.env == "prd" ? "REGIONAL" : "ZONAL"
    disk_type         = "PD_SSD"
    disk_size         = var.env == "prd" ? 100 : 20
    disk_autoresize   = true

    ip_configuration {
      ipv4_enabled                                  = false
      private_network                               = google_compute_network.vpc.id
      enable_private_path_for_google_cloud_services = true
      ssl_mode                                      = "ENCRYPTED_ONLY"
    }

    backup_configuration {
      enabled                        = true
      start_time                     = "18:00" # 01:00 Asia/Bangkok
      point_in_time_recovery_enabled = true
      transaction_log_retention_days = var.env == "prd" ? 7 : 1
      backup_retention_settings {
        retained_backups = var.env == "prd" ? 30 : 7
      }
    }

    database_flags {
      name  = "cloudsql.iam_authentication"
      value = "on"
    }

    user_labels = local.labels
  }
}

resource "google_sql_database" "debt" {
  name     = "debt"
  instance = google_sql_database_instance.pg.name
}
