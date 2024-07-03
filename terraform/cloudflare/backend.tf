terraform {
  required_version = "1.9.1"
  backend "remote" {
    hostname     = "app.terraform.io"
    organization = "nhudson"

    workspaces {
      name = "pik8s2"
    }
  }
}
