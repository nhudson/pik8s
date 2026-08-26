#!/usr/bin/env ruby
# frozen_string_literal: true

require "find"
require "json"
require "yaml"

root = File.expand_path(ARGV.fetch(0, "kubernetes"))
repo = File.dirname(root)
phase_annotation = "secrets-migration.pik8s.dev/phase"
migration_phases = %w[dual-write ownership-handoff external-secret].freeze
contracts = {
  "apps/cert-manager/cert-manager/issuers/externalsecret.yaml" => { "name" => "cert-manager-secret", "keys" => ["api-token"] },
  "apps/flux-system/webhooks/app/github/externalsecret.yaml" => { "name" => "github-webhook-token-secret", "keys" => ["token"] },
  "apps/network/cloudflared/app/externalsecret.yaml" => { "name" => "cloudflared-secret", "keys" => ["TUNNEL_ID", "credentials.json"] },
  "apps/network/external-dns/app/externalsecret.yaml" => { "name" => "external-dns-secret", "keys" => ["api-token"] },
}.freeze
external_secrets = []

Find.find(root) do |path|
  next unless path.end_with?(".yaml")

  YAML.load_stream(File.read(path)).compact.each do |document|
    next unless document.is_a?(Hash) && document["kind"] == "ExternalSecret"

    phase = document.dig("metadata", "annotations", phase_annotation)
    next unless migration_phases.include?(phase)

    external_secrets << [path, document, phase]
  end
end

actual_paths = external_secrets.map { |path, _, _| path.delete_prefix("#{root}/") }.sort
abort "expected four finalized app ExternalSecret contracts" unless actual_paths == contracts.keys.sort
abort "all approved resources must be finalized" unless external_secrets.all? { |_, _, phase| phase == "external-secret" }

external_secrets.each do |path, external_secret, _|
  relative = path.delete_prefix("#{root}/")
  contract = contracts.fetch(relative)
  expected_name = contract.fetch("name")
  expected_keys = contract.fetch("keys").sort
  metadata = external_secret.fetch("metadata")
  spec = external_secret.fetch("spec")
  target = spec.fetch("target")
  template = target.fetch("template")
  secret_name = metadata.fetch("name")
  directory = File.dirname(path)

  abort "metadata name differs from the approved public Secret name" unless secret_name == expected_name
  abort "target must preserve the public Secret name" unless target["name"] == expected_name
  abort "refresh interval differs from the approved contract" unless spec["refreshInterval"] == "1h"
  abort "finalized resource must use the approved ClusterSecretStore" unless spec["secretStoreRef"] == { "kind" => "ClusterSecretStore", "name" => "1password" }
  abort "finalized resource must use Orphan" unless target["creationPolicy"] == "Orphan"
  abort "finalized resource must retain provider-deleted data" unless target["deletionPolicy"] == "Retain"
  abort "template engine must be v2" unless template["engineVersion"] == "v2"
  abort "finalized target must carry the Flux prune guard" unless template.dig("metadata", "annotations", "kustomize.toolkit.fluxcd.io/prune") == "disabled"
  abort "per-field data mappings are not allowed" if spec.key?("data")
  abort "exactly one item extraction is required" unless spec.fetch("dataFrom").length == 1
  abort "vault item must match the public Secret name" unless spec.dig("dataFrom", 0, "extract", "key") == expected_name

  template_data = template.fetch("data")
  abort "template key set differs from the approved contract" unless template_data.keys.sort == expected_keys
  expected_keys.each do |key|
    abort "template does not use an exact key lookup" unless template_data[key] == "{{ index . #{key.to_json} }}"
  end

  resources = YAML.safe_load(File.read(File.join(directory, "kustomization.yaml"))).fetch("resources")
  abort "finalized ExternalSecret is not active" unless resources.include?("./#{File.basename(path)}")
  abort "retired SOPS resource remains active" if resources.any? { |resource| resource.end_with?(".sops.yaml") }
  abort "retired SOPS file remains in app directory" unless Dir.glob(File.join(directory, "*.sops.yaml")).empty?
end

retired_paths = [
  "kubernetes/apps/monitoring/grafana/app/grafana-env.sops.yaml",
  "kubernetes/apps/monitoring/grafana/app/grafana-secret.sops.yaml",
  "kubernetes/apps/monitoring/kube-prometheus-stack/app/alertmanager.sops.yaml",
]
abort "dormant or obsolete SOPS artifacts remain" if retired_paths.any? { |path| File.exist?(File.join(repo, path)) }
grafana_files = Dir.glob(File.join(root, "apps/monitoring/grafana/**/*")).select { |path| File.file?(path) }
abort "retired Grafana application definition remains" unless grafana_files.empty?

contracts.each_key do |relative|
  live_path = File.join(root, relative)
  template_path = File.join(repo, "bootstrap/templates/kubernetes", "#{relative}.j2")
  base = File.dirname(template_path)
  abort "bootstrap ExternalSecret template missing" unless File.exist?(template_path)
  abort "bootstrap ExternalSecret contract differs from live" unless YAML.safe_load(File.read(template_path)) == YAML.safe_load(File.read(live_path))
  abort "bootstrap SOPS template remains" unless Dir.glob(File.join(base, "*.sops.yaml.j2")).empty?
  resources = YAML.safe_load(File.read(File.join(base, "kustomization.yaml.j2"))).fetch("resources")
  abort "bootstrap ExternalSecret template is inactive" unless resources.include?("./externalsecret.yaml")
  abort "bootstrap app still references SOPS" if resources.any? { |resource| resource.end_with?(".sops.yaml") }
end

puts "validated #{external_secrets.length} finalized app ExternalSecret contracts"
