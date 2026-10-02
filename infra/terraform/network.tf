# §4 — one VPC, private services access for Cloud SQL, a Serverless VPC connector
# so Cloud Run has a stable egress identity, and Cloud NAT with a STATIC IP.
# The static IP is the whole point: it is allow-listed on the Odoo droplet and at PEAK.

resource "google_compute_network" "vpc" {
  name                    = "debt-vpc-${var.env}"
  auto_create_subnetworks = false
}

resource "google_compute_subnetwork" "main" {
  name          = "debt-subnet-${var.env}"
  ip_cidr_range = "10.20.0.0/20"
  region        = var.region
  network       = google_compute_network.vpc.id

  private_ip_google_access = true

  log_config {
    aggregation_interval = "INTERVAL_10_MIN"
    flow_sampling        = 0.5
    metadata             = "INCLUDE_ALL_METADATA"
  }
}

resource "google_vpc_access_connector" "debt_vpcc" {
  name          = "debt-vpcc-${var.env}"
  region        = var.region
  network       = google_compute_network.vpc.name
  ip_cidr_range = "10.20.16.0/28"
  min_instances = 2
  max_instances = var.env == "prd" ? 6 : 3
}

# Private services access for Cloud SQL private IP.
resource "google_compute_global_address" "psa" {
  name          = "debt-psa-${var.env}"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 16
  network       = google_compute_network.vpc.id
}

resource "google_service_networking_connection" "psa" {
  network                 = google_compute_network.vpc.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.psa.name]
}

resource "google_compute_router" "nat" {
  name    = "debt-router-${var.env}"
  region  = var.region
  network = google_compute_network.vpc.id
}

# Static egress IP — this is the address Odoo and PEAK allow-list.
resource "google_compute_address" "nat" {
  name   = "debt-nat-ip-${var.env}"
  region = var.region
}

resource "google_compute_router_nat" "nat" {
  name                               = "debt-nat-${var.env}"
  router                             = google_compute_router.nat.name
  region                             = var.region
  nat_ip_allocate_option             = "MANUAL_ONLY"
  nat_ips                            = [google_compute_address.nat.self_link]
  source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"

  log_config {
    enable = true
    filter = "ERRORS_ONLY"
  }
}

# §4.5 — Cloud Armor. Rate limits are per-IP; the app does its own per-user limiting.
resource "google_compute_security_policy" "debt_armor" {
  name = "debt-armor-${var.env}"

  rule {
    action   = "rate_based_ban"
    priority = 1000
    match {
      versioned_expr = "SRC_IPS_V1"
      config { src_ip_ranges = ["*"] }
    }
    rate_limit_options {
      conform_action = "allow"
      exceed_action  = "deny(429)"
      enforce_on_key = "IP"
      rate_limit_threshold {
        count        = 600
        interval_sec = 60
      }
      ban_duration_sec = 300
    }
    description = "Per-IP rate ban"
  }

  rule {
    action   = "deny(403)"
    priority = 900
    match {
      expr { expression = "evaluatePreconfiguredExpr('sqli-v33-stable')" }
    }
    description = "OWASP SQLi"
  }

  rule {
    action   = "deny(403)"
    priority = 901
    match {
      expr { expression = "evaluatePreconfiguredExpr('xss-v33-stable')" }
    }
    description = "OWASP XSS"
  }

  rule {
    action   = "allow"
    priority = 2147483647
    match {
      versioned_expr = "SRC_IPS_V1"
      config { src_ip_ranges = ["*"] }
    }
    description = "default allow"
  }
}
