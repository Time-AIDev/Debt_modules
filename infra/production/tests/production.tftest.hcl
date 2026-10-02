mock_provider "google" {
  mock_data "google_project" {
    defaults = { number = "123456789012", project_id = "volt-debt-prd" }
  }
  mock_resource "google_service_account" {
    defaults = { email = "runtime@volt-debt-prd.iam.gserviceaccount.com" }
  }
  mock_resource "google_sql_database_instance" {
    defaults = { private_ip_address = "10.40.0.2" }
  }
}
run "small_team_foundation" {
  command = plan
  variables { project_id = "volt-debt-prd" }
  assert {
    condition = google_sql_database_instance.primary.settings[0].tier == "db-custom-2-8192" && google_sql_database_instance.primary.settings[0].availability_type == "REGIONAL"
    error_message = "The selected 2 CPU / 8 GiB Regional HA profile must be preserved."
  }
  assert {
    condition = google_sql_database_instance.primary.settings[0].disk_size == 20 && google_sql_database_instance.primary.settings[0].disk_autoresize
    error_message = "Start at 20 GiB with auto-grow."
  }
  assert {
    condition = length(google_cloud_run_v2_service.application) == 0
    error_message = "Foundation must not start application workloads."
  }
}
run "candidate_profile" {
  command = plan
  variables {
    project_id = "volt-debt-prd"
    enable_workloads = true
    go_live = false
    api_image = "asia-southeast1-docker.pkg.dev/volt-debt-prd/debt/api@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    web_image = "asia-southeast1-docker.pkg.dev/volt-debt-prd/debt/web@sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    scanner_image = "asia-southeast1-docker.pkg.dev/volt-debt-prd/debt/scanner@sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
    secret_versions = { AUTH_SESSION_SECRET = "1", AUTH_ALLOWLIST = "1", GOOGLE_CLIENT_ID = "1", ODOO_URL = "1", ODOO_DB = "1", ODOO_LOGIN = "1", ODOO_API_KEY = "1", MIGRATION_DATABASE_URL = "1" }
  }
  assert {
    condition = google_cloud_run_v2_service.application["api"].template[0].scaling[0].min_instance_count == 1 && google_cloud_run_v2_service.application["api"].template[0].scaling[0].max_instance_count == 3
    error_message = "API must use the 1–3 small-team scaling profile."
  }
  assert {
    condition = google_cloud_run_v2_service.application["worker"].ingress == "INGRESS_TRAFFIC_INTERNAL_ONLY" && google_cloud_run_v2_service.application["api"].ingress == "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"
    error_message = "Worker must be private and API must be reachable only through the edge."
  }
}
