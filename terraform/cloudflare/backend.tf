terraform {
  required_version = "~> 1.3.0"
  backend "remote" {
    hostname     = "app.terraform.io"
    organization = "nhudson"

    workspaces {
      name = "pik8s-cloudflare"
    }
  }
}
