variable "cloudflare_account_id" {
  description = "account id of the cloudflare account you are managaging"
  type        = string
  sensitive   = true
}

variable "cloudflare_zone_id_nhudson_dev" {
  description = "the zone id for nhudson.dev dns zone"
  type        = string
  sensitive   = true
}
