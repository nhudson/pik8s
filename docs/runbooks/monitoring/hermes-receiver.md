# Hermes alert receiver contract

The alert receiver is an external prerequisite operated by Hermes rather than a Kubernetes resource in this repository. Monitoring rollout must not be considered complete until this contract is verified against the live receiver.

- The tailnet-only endpoint requires HMAC V2 over `<timestamp>.<raw-body>` and rejects missing or invalid signatures in constant time. Do not enable Funnel or public SSH for alert delivery.
- The timestamp has a five-minute freshness window; stale signed requests are rejected rather than downgraded to legacy authentication.
- The relay sends the body digest as `X-Request-ID`, the generic delivery header supported by Hermes. Delivery identifiers have a bounded one-hour replay cache. A retry with the same identifier is ignored, while a distinct identifier remains eligible even when its body is identical. Alertmanager's four-hour repeat interval exceeds this cache window.
- A route script reduces alerts to an allow-list of operational fields and labels them as untrusted evidence.
- The route receives no terminal or file toolset. Its only cluster snapshot comes from fixed queries using a dedicated read-only cluster credential.
- Negative authorization checks must reject Secret reads, workload writes, exec, port-forwarding, and impersonation.
- The existing receiver route permits explanation and safe next checks but no automated remediation. A separately approved and verified remediation profile can use narrow, reversible GitOps changes only after cutover.

## Acceptance test

1. Check the receiver health endpoint without recording its private hostname.
2. Send a synthetic warning with a current HMAC V2 signature and unique delivery identifier; require an accepted response.
3. Repeat the same delivery identifier; require an idempotent ignored response and no second agent run.
4. Send the same body with a distinct identifier; require another accepted response.
5. Send a correctly signed stale timestamp and an invalid signature; require authentication rejection for both.
6. Verify the sanitized event creates a Hermes investigation and that its snapshot contains only counts, readiness booleans, and warning reasons.
7. Run positive and negative `kubectl auth can-i` checks with the fixed read-only cluster credential.

Alertmanager retries upstream failures. The relay does not log alert bodies, authorization headers, signatures, receiver URLs, or response bodies.

## Receiver-profile handoff

Keep the current read-only receiver and direct human notifications active until the replacement gateway has been restarted from a separate administration session and its local webhook is healthy. Stage a separately signed warning/critical route and prove its filter drops noise and strips untrusted instructions. Verify its dedicated cluster credential remains least-privileged; do not copy the default profile's credential or session state.

The private relay egress Service and named-pod NetworkPolicy must be Ready before changing the receiver. Keep the tailnet-only Serve listener on the existing receiver until a replacement webhook has passed signed, sanitized warning **and** critical tests. Coordinate the vault-backed destination and HMAC change with the Serve handoff; do not send a new key to an old route or an old key to a new route without a planned overlap/retry window. Preserve the independent human Alertmanager receiver throughout. Inspect the actual replacement-agent prompt and response, not only HTTP 202; then verify Flux, relay logs, delivery-failure counters, and non-noise alerts. If any stage fails, restore the previous private receiver and signing configuration through the documented vault/Serve rollback. Do not add a duplicate periodic poller for event-driven alerts.