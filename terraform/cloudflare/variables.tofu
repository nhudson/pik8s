variable "cloudflare_r2_account_id" {
  description = "account id of the cloudflare account you are managaging"
  type        = string
  sensitive   = true
}

variable "cloudflare_r2_location" {
  description = "The location hint of the R2 bucket"
  type        = string
  default     = "ENAM"
}

variable "cloudflare_r2_api_token" {
  description = "The API token for the cloudflare r2 bucket access"
  type        = string
  sensitive   = true
}
