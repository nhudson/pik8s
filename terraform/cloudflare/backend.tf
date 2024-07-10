terraform {
  required_version = "1.9.2"
  backend "remote" {
    hostname     = "app.terraform.io"
    organization = "nhudson"

    workspaces {
      name = "pik8s2"
    }
  }
}
