resource "google_compute_global_address" "frontend" {
  name = "debt-https"
}
resource "google_compute_managed_ssl_certificate" "https" {
  name = "debt-https"
  managed {
    domains = [var.hostname]
  }
}
resource "google_compute_security_policy" "edge" {
  name = "debt-edge"
  rule {
    action   = "throttle"
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
    }
  }
  rule {
    action   = "deny(403)"
    priority = 900
    preview  = true
    match {
      expr { expression = "evaluatePreconfiguredWaf('sqli-v33-stable')" }
    }
  }
  rule {
    action   = "allow"
    priority = 2147483647
    match {
      versioned_expr = "SRC_IPS_V1"
      config { src_ip_ranges = ["*"] }
    }
  }
}
resource "google_compute_region_network_endpoint_group" "application" {
  for_each              = var.enable_workloads ? toset(["api", "web"]) : toset([])
  name                  = "debt-${each.key}"
  region                = var.region
  network_endpoint_type = "SERVERLESS"
  cloud_run { service = google_cloud_run_v2_service.application[each.key].name }
}
resource "google_compute_backend_service" "application" {
  for_each              = var.enable_workloads ? toset(["api", "web"]) : toset([])
  name                  = "debt-${each.key}"
  protocol              = "HTTP"
  load_balancing_scheme = "EXTERNAL_MANAGED"
  security_policy       = google_compute_security_policy.edge.id
  enable_cdn            = false
  backend { group = google_compute_region_network_endpoint_group.application[each.key].id }
  log_config { enable = true }
}
resource "google_compute_url_map" "application" {
  count           = var.enable_workloads ? 1 : 0
  name            = "debt-https"
  default_service = google_compute_backend_service.application["web"].id
  host_rule {
    hosts        = [var.hostname]
    path_matcher = "debt"
  }
  path_matcher {
    name            = "debt"
    default_service = google_compute_backend_service.application["web"].id
    path_rule {
      paths   = ["/api/*", "/v1/*", "/livez", "/readyz"]
      service = google_compute_backend_service.application["api"].id
    }
  }
}
resource "google_compute_target_https_proxy" "application" {
  count            = var.enable_workloads ? 1 : 0
  name             = "debt-https"
  url_map          = google_compute_url_map.application[0].id
  ssl_certificates = [google_compute_managed_ssl_certificate.https.id]
}
resource "google_compute_global_forwarding_rule" "https" {
  count                 = var.enable_workloads ? 1 : 0
  name                  = "debt-https"
  ip_address            = google_compute_global_address.frontend.address
  target                = google_compute_target_https_proxy.application[0].id
  port_range            = "443"
  load_balancing_scheme = "EXTERNAL_MANAGED"
}
resource "google_compute_url_map" "redirect" {
  name = "debt-http-redirect"
  default_url_redirect {
    https_redirect         = true
    strip_query            = false
    redirect_response_code = "MOVED_PERMANENTLY_DEFAULT"
  }
}
resource "google_compute_target_http_proxy" "redirect" {
  name    = "debt-http-redirect"
  url_map = google_compute_url_map.redirect.id
}
resource "google_compute_global_forwarding_rule" "http" {
  name                  = "debt-http-redirect"
  ip_address            = google_compute_global_address.frontend.address
  target                = google_compute_target_http_proxy.redirect.id
  port_range            = "80"
  load_balancing_scheme = "EXTERNAL_MANAGED"
}
output "dns_a_record" { value = google_compute_global_address.frontend.address }
output "odoo_allowlist_ip" { value = google_compute_address.egress.address }
output "web_url" { value = "https://${var.hostname}/" }
output "api_base" { value = "https://${var.hostname}/api/v1" }
output "worker_url" { value = local.worker_url }
output "sql_private_ip" { value = google_sql_database_instance.primary.private_ip_address }
output "runtime_database_roles" { value = [for user in google_sql_user.runtime : user.name] }
