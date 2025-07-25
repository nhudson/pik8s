terraform {
  required_providers {
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 5.7.0"
    }
    random = {
      version = "~> 3.7.0"
    }
  }
}
