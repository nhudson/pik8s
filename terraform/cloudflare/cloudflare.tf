resource "random_id" "tunnel_secret" {
  byte_length = 35
}

resource "cloudflare_argo_tunnel" "pik8s-github-webhook" {
  name       = "pik8s-github-webhook"
  account_id = var.cloudflare_account_id
  secret     = random_id.tunnel_secret.b64_std
}

resource "cloudflare_record" "pik8s-github-webhook-cname" {
  name    = "flux-receiver"
  proxied = true
  ttl     = 1
  type    = "CNAME"
  value   = cloudflare_argo_tunnel.pik8s-github-webhook.cname
  zone_id = var.cloudflare_zone_id_nhudson_dev
}

resource "cloudflare_record" "nhudson_dev_nas" {
  name    = "nas"
  proxied = false
  ttl     = 1
  type    = "A"
  value   = "192.168.6.5"
  zone_id = var.cloudflare_zone_id_nhudson_dev
}

resource "cloudflare_record" "nhudson_dev_sonarr" {
  name    = "sonarr"
  proxied = false
  ttl     = 1
  type    = "A"
  value   = "192.168.6.220"
  zone_id = var.cloudflare_zone_id_nhudson_dev
}

resource "cloudflare_record" "nhudson_dev_nzbget" {
  name    = "sonarr"
  proxied = false
  ttl     = 1
  type    = "A"
  value   = "192.168.6.220"
  zone_id = var.cloudflare_zone_id_nhudson_dev
}
