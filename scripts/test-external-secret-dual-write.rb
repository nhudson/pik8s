#!/usr/bin/env ruby
# frozen_string_literal: true

require "find"
require "json"
require "yaml"

root = File.expand_path(ARGV.fetch(0, "kubernetes"))
phase_annotation = "secrets-migration.pik8s.dev/phase"
external_secrets = []

Find.find(root) do |path|
  next unless path.end_with?(".yaml")

  YAML.load_stream(File.read(path)).compact.each do |document|
    next unless document.is_a?(Hash)
    next unless document["kind"] == "ExternalSecret"
    next unless document.dig("metadata", "annotations", phase_annotation) == "dual-write"

    external_secrets << [path, document]
  end
end

approved_paths = [
  "apps/cert-manager/cert-manager/issuers/externalsecret.yaml",
  "apps/network/cloudflared/app/externalsecret.yaml",
  "apps/network/external-dns/app/externalsecret.yaml",
].sort
actual_paths = external_secrets.map { |path, _| path.delete_prefix("#{root}/") }.sort
abort "expected three app-level dual-write contracts" unless external_secrets.length == 3
abort "dual-write scope differs from the approved app-level set" unless actual_paths == approved_paths

external_secrets.each do |path, external_secret|
  apps_root = File.join(root, "apps") + File::SEPARATOR
  abort "only app-level resources are in dual-write scope" unless path.start_with?(apps_root)

  metadata = external_secret.fetch("metadata")
  spec = external_secret.fetch("spec")
  secret_store_ref = spec.fetch("secretStoreRef")
  target = spec.fetch("target")
  template = target.fetch("template")
  secret_name = metadata.fetch("name")
  directory = File.dirname(path)

  abort "target must preserve the existing Secret name" unless target["name"] == secret_name
  abort "dual-write must use the approved ClusterSecretStore" unless secret_store_ref == { "kind" => "ClusterSecretStore", "name" => "1password" }
  abort "dual-write must use Merge" unless target["creationPolicy"] == "Merge"
  abort "dual-write must retain data on deletion" unless target["deletionPolicy"] == "Retain"
  abort "template engine must be v2" unless template["engineVersion"] == "v2"
  abort "prune handoff is not part of dual-write" if template.dig("metadata", "annotations", "kustomize.toolkit.fluxcd.io/prune")
  abort "per-field data mappings are not allowed" if spec.key?("data")

  extracts = spec.fetch("dataFrom")
  abort "exactly one item extraction is required" unless extracts.length == 1
  abort "vault item must match the existing public Secret name" unless extracts.dig(0, "extract", "key") == secret_name

  rollback_candidates = Dir.glob(File.join(directory, "*.sops.yaml")).filter_map do |candidate|
    documents = YAML.load_stream(File.read(candidate)).compact
    secret = documents.find { |document| document.is_a?(Hash) && document["kind"] == "Secret" && document.dig("metadata", "name") == secret_name }
    [candidate, secret] if secret
  end
  abort "expected one encrypted rollback Secret" unless rollback_candidates.length == 1

  rollback_path, rollback = rollback_candidates.first
  abort "encrypted rollback metadata must remain" unless rollback.key?("sops")
  rollback_values = (rollback["data"] || {}).values + (rollback["stringData"] || {}).values
  abort "encrypted rollback values must remain SOPS ciphertext" unless rollback_values.all? { |value| value.is_a?(String) && value.match?(/\AENC\[[^\n]+\]\z/) }
  abort "namespace contract changed" unless rollback.dig("metadata", "namespace") == metadata["namespace"]

  expected_keys = ((rollback["data"] || {}).keys + (rollback["stringData"] || {}).keys).sort
  template_data = template.fetch("data")
  abort "template key set differs from encrypted rollback" unless template_data.keys.sort == expected_keys
  expected_keys.each do |key|
    expected_template = "{{ index . #{key.to_json} }}"
    abort "template does not use an exact key lookup" unless template_data[key] == expected_template
  end

  kustomization_path = File.join(directory, "kustomization.yaml")
  kustomization = YAML.safe_load(File.read(kustomization_path))
  resources = kustomization.fetch("resources")
  public_resource = "./#{File.basename(path)}"
  rollback_resource = "./#{File.basename(rollback_path)}"
  abort "dual-write resource is not active" unless resources.include?(public_resource)
  abort "encrypted rollback resource must remain active" unless resources.include?(rollback_resource)
end

puts "validated #{external_secrets.length} rollback-safe dual-write contracts"
