terraform {
  required_version = ">= 1.8.0"
  backend "s3" {
    # Cloudflare R2 configuration
    # The endpoint is set via AWS_S3_ENDPOINT environment variable to hide account ID
    bucket                      = "tofu-backend"
    key                         = "cloudflare/terraform.tfstate"
    region                      = "auto"
    use_lockfile                = true
    skip_credentials_validation = true
    skip_region_validation      = true
    skip_requesting_account_id  = true
    skip_metadata_api_check     = true
    use_path_style              = true
    skip_s3_checksum            = true
  }
}
