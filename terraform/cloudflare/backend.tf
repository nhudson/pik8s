terraform {
  required_version = "1.7.5"
  backend "remote" {
    hostname     = "app.terraform.io"
    organization = "nhudson"

    workspaces {
      name = "pik8s2"
    }
  }
}
