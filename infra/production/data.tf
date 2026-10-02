resource "google_compute_network" "private" {

  name                    = "debt-production"
  auto_create_subnetworks = false
  depends_on              = [google_project_service.apis]

}

resource "google_compute_subnetwork" "runtime" {

  name                     = "debt-runtime"
  region                   = var.region
  network                  = google_compute_network.private.id
  ip_cidr_range            = "10.30.0.0/24"
  private_ip_google_access = true

}

resource "google_compute_global_address" "sql_range" {

  name          = "debt-sql-private"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 16
  network       = google_compute_network.private.id

}

resource "google_service_networking_connection" "sql" {

  network                 = google_compute_network.private.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.sql_range.name]

}

resource "google_compute_address" "egress" {

  name   = "debt-egress"
  region = var.region
}

resource "google_compute_router" "nat" {

  name    = "debt-router"
  region  = var.region
  network = google_compute_network.private.id

}

resource "google_compute_router_nat" "egress" {

  name                               = "debt-nat"
  router                             = google_compute_router.nat.name
  region                             = var.region
  nat_ip_allocate_option             = "MANUAL_ONLY"
  nat_ips                            = [google_compute_address.egress.self_link]
  source_subnetwork_ip_ranges_to_nat = "LIST_OF_SUBNETWORKS"
  subnetwork {

    name                    = google_compute_subnetwork.runtime.id
    source_ip_ranges_to_nat = ["ALL_IP_RANGES"]

  }

  log_config {

    enable = true
    filter = "ERRORS_ONLY"
  }


}

resource "google_sql_database_instance" "primary" {

  name                = "debt-pg-prd"
  region              = var.region
  database_version    = "POSTGRES_16"
  deletion_protection = true
  settings {

    tier                        = "db-custom-2-8192"
    edition                     = "ENTERPRISE"
    availability_type           = "REGIONAL"
    disk_type                   = "PD_SSD"
    disk_size                   = 20
    disk_autoresize             = true
    deletion_protection_enabled = true
    ip_configuration {

      ipv4_enabled    = false
      private_network = google_compute_network.private.id
      ssl_mode        = "ENCRYPTED_ONLY"

    }

    backup_configuration {

      enabled                        = true
      start_time                     = "18:00"
      point_in_time_recovery_enabled = true
      transaction_log_retention_days = 7
      backup_retention_settings {
        retained_backups = 30
      }


    }

    database_flags {

      name  = "cloudsql.iam_authentication"
      value = "on"
    }

    maintenance_window {

      day          = 7
      hour         = 18
      update_track = "stable"
    }

    user_labels = local.labels

  }

  depends_on = [google_service_networking_connection.sql]
  lifecycle {
    prevent_destroy = true
  }


}

resource "google_sql_database" "business" {

  name     = "debt"
  instance = google_sql_database_instance.primary.name

}

resource "google_sql_user" "runtime" {

  for_each = toset(["api", "worker"])
  name     = trimsuffix(google_service_account.workload[each.key].email, ".gserviceaccount.com")
  instance = google_sql_database_instance.primary.name
  type     = "CLOUD_IAM_SERVICE_ACCOUNT"

}

resource "google_storage_bucket" "private" {

  for_each                    = toset(["uploads", "clean", "documents", "exports"])
  name                        = "${var.project_id}-${each.key}"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false
  labels                      = local.labels
  versioning {
    enabled = true
  }

  dynamic "lifecycle_rule" {

    for_each = contains(["uploads", "exports"], each.key) ? [1] : []
    content {

      condition {
        age = 7
      }

      action {
        type = "Delete"
      }


    }


  }


}

resource "google_storage_bucket_iam_member" "runtime_objects" {

  for_each = { for item in setproduct(toset(["api", "worker"]), toset(["uploads", "clean", "documents", "exports"])) : "${item[0]}:${item[1]}" => item }
  bucket   = google_storage_bucket.private[each.value[1]].name
  role     = "roles/storage.objectUser"
  member   = "serviceAccount:${google_service_account.workload[each.value[0]].email}"

}

