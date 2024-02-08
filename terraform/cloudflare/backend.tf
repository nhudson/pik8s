terraform {
  required_version = "1.7.3"
  backend "remote" {
    hostname     = "app.terraform.io"
    organization = "nhudson"

    workspaces {
      name = "pik8s2"
    }
  }
}
