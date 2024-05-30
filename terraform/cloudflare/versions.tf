terraform {
  required_providers {
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 4.34.0"
    }
    random = {
      version = "~> 3.6.0"
    }
  }
}
