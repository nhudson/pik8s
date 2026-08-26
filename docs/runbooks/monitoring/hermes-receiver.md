# Hermes alert receiver contract

The alert receiver is an external prerequisite operated by Hermes rather than a Kubernetes resource in this repository. Monitoring rollout must not be considered complete until this contract is verified against the live receiver.

- The public endpoint requires HMAC V2 over `<timestamp>.<raw-body>` and rejects missing or invalid signatures in constant time.
- The timestamp has a five-minute freshness window; stale signed requests are rejected rather than downgraded to legacy authentication.
- The relay sends the body digest as `X-Request-ID`, the generic delivery header supported by Hermes. Delivery identifiers have a bounded one-hour replay cache. A retry with the same identifier is ignored, while a distinct identifier remains eligible even when its body is identical. Alertmanager's four-hour repeat interval exceeds this cache window.
- A route script reduces alerts to an allow-list of operational fields and labels them as untrusted evidence.
- The route receives no terminal or file toolset. Its only cluster snapshot comes from fixed queries using a dedicated read-only kubeconfig.
- Negative authorization checks must reject Secret reads, workload writes, exec, port-forwarding, and impersonation.
- The route prompt permits explanation and safe next checks but no automated remediation.

## Acceptance test

1. Check the receiver health endpoint without recording its private hostname.
2. Send a synthetic warning with a current HMAC V2 signature and unique delivery identifier; require an accepted response.
3. Repeat the same delivery identifier; require an idempotent ignored response and no second agent run.
4. Send the same body with a distinct identifier; require another accepted response.
5. Send a correctly signed stale timestamp and an invalid signature; require authentication rejection for both.
6. Verify the sanitized event creates a Hermes investigation and that its snapshot contains only counts, readiness booleans, and warning reasons.
7. Run positive and negative `kubectl auth can-i` checks for the fixed kubeconfig.

Alertmanager retries upstream failures. The relay does not log alert bodies, authorization headers, signatures, receiver URLs, or response bodies.