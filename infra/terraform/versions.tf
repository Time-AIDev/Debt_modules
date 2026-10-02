# Volt Debt — prototype infrastructure.
# Faithful to the GCP Architecture doc (Drive — docs/02-gcp/ in the specs repo, not this one)
# §5.1, §6.1, §7, §8, §9 and ADR-010.
# NOTHING HERE HAS BEEN APPLIED. No gcloud credentials exist in this environment;
# these files are `terraform fmt`-clean and structurally complete, not proven against the API.

terraform {
  required_version = ">= 1.6.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }
  # ADR-010 item 1: default is a state bucket in each project, not a shared ops project.
  backend "gcs" {
    # bucket = "volt-debt-<env>-tfstate"   # set with -backend-config at init
    prefix = "debt/infra"
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}
