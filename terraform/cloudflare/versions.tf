terraform {
  required_providers {
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 5.1.0"
    }
    random = {
      version = "~> 3.6.0"
    }
  }
}
