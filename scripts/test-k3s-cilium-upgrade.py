#!/usr/bin/env python3
"""Contract that K3s upgrades carry Cilium CNI into the new data directory."""
from __future__ import annotations

import pathlib
import os
import subprocess
import tempfile

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
PLANS = ROOT / "kubernetes/apps/system-upgrade/k3s/app/plan.yaml"
CANONICAL = ROOT / "scripts/kubeconform.sh"


def simulate_upgrade(script: str, *, moves_current: bool) -> None:
    with tempfile.TemporaryDirectory(prefix="k3s-cilium-upgrade-") as directory:
        root = pathlib.Path(directory)
        cni_parent = root / "opt/cni"
        cni = cni_parent / "bin"
        data = root / "var/lib/rancher/k3s/data"
        old = data / "old/bin"
        new = data / "new/bin"
        for path in (cni_parent, old, new):
            path.mkdir(parents=True)
        cni.symlink_to(old)
        source = cni / "cilium-cni"
        source.write_text("cilium")
        source.chmod(0o755)
        (old / "loopback").write_text("loopback")
        (old / "loopback").chmod(0o755)
        (new / "loopback").write_text("loopback")
        (new / "loopback").chmod(0o755)
        (data / "current").symlink_to(old.parent)
        upgrade = root / "upgrade.sh"
        upgrade.write_text(
            '#!/bin/sh\nset -eu\nrm "$HOST_ROOT/var/lib/rancher/k3s/data/current"\nln -s "$HOST_ROOT/var/lib/rancher/k3s/data/new" "$HOST_ROOT/var/lib/rancher/k3s/data/current"\n'
            if moves_current
            else "#!/bin/sh\nexit 0\n"
        )
        upgrade.chmod(0o755)
        completed = subprocess.run(
            ["/bin/sh", "-c", script],
            text=True,
            capture_output=True,
            env={
                **os.environ,
                "HOST_ROOT": str(root),
                "UPGRADE_SCRIPT": str(upgrade),
                "WAIT_ATTEMPTS": "2",
                "WAIT_SECONDS": "0",
            },
            timeout=10,
        )
        if completed.returncode:
            raise AssertionError(completed.stdout + completed.stderr)
        migrated = (new if moves_current else old) / "cilium-cni"
        if not migrated.exists() or not os.access(migrated, os.X_OK):
            raise AssertionError("wrapper did not install executable cilium-cni into the new K3s target")


def main() -> None:
    errors: list[str] = []
    plans = [doc for doc in yaml.safe_load_all(PLANS.read_text()) if doc]
    if {plan["metadata"]["name"] for plan in plans} != {"controllers", "workers"}:
        errors.append("expected controller and worker K3s upgrade plans")
    for plan in plans:
        name = plan["metadata"]["name"]
        spec = plan["spec"]
        upgrade = spec["upgrade"]
        script = "\n".join(upgrade.get("args", []))
        if spec.get("concurrency") != 1:
            errors.append(f"{name} upgrades are not serialized")
        if upgrade.get("command") != ["/bin/sh", "-c"]:
            errors.append(f"{name} does not wrap the official upgrade script")
        for contract in (
            "HOST_ROOT:-/host",
            "UPGRADE_SCRIPT:-/bin/upgrade.sh",
            '"$host_root/opt/cni/bin/cilium-cni"',
            '"$upgrade_script" upgrade',
            '"$host_root/var/lib/rancher/k3s/data/current"',
            "WAIT_ATTEMPTS:-120",
            "WAIT_SECONDS:-1",
            '[ "$current" != "$before" ] && [ -x "$current/bin/loopback" ]',
            "loopback",
            "chmod 0755",
        ):
            if contract not in script:
                errors.append(f"{name} upgrade wrapper is missing {contract}")
        preserve = script.find("cp \"$source\" \"$staged\"")
        upgrade_call = script.find('"$upgrade_script" upgrade')
        restore = script.rfind("cp \"$staged\"")
        if not 0 <= preserve < upgrade_call < restore:
            errors.append(f"{name} does not preserve, upgrade, then restore Cilium CNI in order")
        if not errors:
            simulate_upgrade(script, moves_current=True)
            simulate_upgrade(script, moves_current=False)
    if "python3 ./scripts/test-k3s-cilium-upgrade.py" not in CANONICAL.read_text():
        errors.append("canonical validation does not run the K3s/Cilium upgrade contract")
    if errors:
        raise SystemExit("\n".join(f"- {error}" for error in errors))
    print("K3s/Cilium upgrade contract passed")


if __name__ == "__main__":
    main()
