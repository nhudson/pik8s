locals {
  account_id  = var.cloudflare_r2_account_id
  r2_location = var.cloudflare_r2_location
}

resource "cloudflare_r2_bucket" "thanos" {
  account_id = local.account_id
  name       = "thanos"
  location   = local.r2_location
}

resource "cloudflare_r2_bucket" "loki" {
  account_id = local.account_id
  name       = "loki"
  location   = local.r2_location
}

resource "cloudflare_r2_bucket" "psqlbackups" {
  account_id = local.account_id
  name       = "postgres-backups"
  location   = local.r2_location
}
