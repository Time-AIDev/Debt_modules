variable "project_id" {
  type        = string
  description = "volt-debt-stg or volt-debt-prd. ADR-010 item 1: two projects, one codebase."
}

variable "env" {
  type        = string
  description = "stg or prd. Drives every sizing difference in GCP_Architecture.md §5.1."
  validation {
    condition     = contains(["stg", "prd"], var.env)
    error_message = "env must be stg or prd."
  }
}

variable "region" {
  type        = string
  default     = "asia-southeast1"
  # ADR-010 item 3 / A-04: PDPA cross-border is handled by contract and DPA.
  # Re-evaluate a Bangkok region when GA for every service used here.
  description = "Region for both projects."
}

variable "image_tag" {
  type        = string
  description = "git sha of the images in Artifact Registry."
}

# Required on every resource — GCP_Architecture.md §3.3.
locals {
  labels = {
    app         = "volt-debt"
    env         = var.env
    managed_by  = "terraform"
    cost_center = "debt-collection"
  }

  # §5.1 — the only differences between environments are sizing and CPU allocation.
  api_min_instances = var.env == "prd" ? 2 : 1
  api_max_instances = var.env == "prd" ? 20 : 5
  web_min_instances = var.env == "prd" ? 1 : 0
  web_max_instances = var.env == "prd" ? 5 : 2
  # prd keeps CPU always allocated for the in-process outbox relay; stg relies on
  # the outbox-relay-sweep Scheduler job instead (§5.3 rule 3).
  api_cpu_idle = var.env == "prd" ? false : true
}
