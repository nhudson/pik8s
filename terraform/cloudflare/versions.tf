terraform {
  required_providers {
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 3.27"
    }
    random = {
      version = "~> 3.4.3"
    }
  }
}
