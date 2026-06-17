# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "pyyaml",
#     "jsonschema",
#     "requests",
# ]
# ///
"""Mirror external Helm charts into ghcr.io/vexxhost/charts.

Reads YAML manifest files from mirrors/ describing upstream chart sources,
versions, and provenance keys.  Validates them against a JSON Schema,
verifies upstream Helm provenance, copies the exact OCI artifact with ORAS,
and optionally signs the destination with cosign.

Usage:
  uv run hack/mirror_charts.py --validate-only
  uv run hack/mirror_charts.py --dry-run --chart cert-manager
  uv run hack/mirror_charts.py --chart cert-manager --version v1.15.5
"""

from __future__ import annotations

import argparse
import atexit
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import jsonschema
import requests
import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent
MIRRORS_DIR = REPO_ROOT / "mirrors"
SCHEMA_PATH = REPO_ROOT / "schemas" / "chart-mirror.schema.json"

SUBCOMMAND_TIMEOUT = 300  # seconds per network subprocess
HTTP_TIMEOUT = 30         # seconds per HTTP request


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def run(cmd: list[str], *, cwd: Path | None = None, check: bool = True, timeout: int | None = None, **kwargs) -> subprocess.CompletedProcess:
    """Wrap subprocess.run with defaults for this script."""
    try:
        return subprocess.run(
            cmd, cwd=cwd or REPO_ROOT, text=True,
            capture_output=True, check=check,
            timeout=timeout or SUBCOMMAND_TIMEOUT, **kwargs,
        )
    except FileNotFoundError:
        die(f"required binary not found: {cmd[0]}")
    except subprocess.CalledProcessError as exc:
        for stream in (exc.stdout, exc.stderr):
            if stream:
                print(stream.strip(), file=sys.stderr)
        die(f"command failed: {' '.join(cmd)}")
    except subprocess.TimeoutExpired as exc:
        die(f"command timed out after {exc.timeout}s: {' '.join(cmd)}")


def die(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def oras_resolve(repository: str, version: str) -> str:
    """Resolve a version tag to a full digest reference.

    Returns ``<repo>@sha256:<hex>`` using ``oras resolve --full-reference``.
    """
    ref = f"{repository}:{version}"
    result = run(["oras", "resolve", "--full-reference", ref], timeout=SUBCOMMAND_TIMEOUT)
    digest_ref = result.stdout.strip()
    if not digest_ref:
        die(f"oras resolve returned nothing for {ref}")
    return digest_ref


def fetch_keyring(keyring: str) -> Path:
    """Return a local path to the keyring file.

    If *keyring* is a URL it is downloaded via ``requests`` to a temporary
    file that is cleaned up when the process exits.  Otherwise it is
    expected to be a relative path from the repository root.
    """
    if keyring.startswith("http://") or keyring.startswith("https://"):
        resp = requests.get(keyring, timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
        tmp = tempfile.NamedTemporaryFile(suffix=".gpg", delete=False)
        try:
            tmp.write(resp.content)
        except Exception:
            tmp.close()
            os.unlink(tmp.name)
            raise
        tmp.close()
        # Clean up when the process exits.
        atexit.register(lambda p=Path(tmp.name): p.unlink(missing_ok=True))
        return Path(tmp.name)
    else:
        path = (REPO_ROOT / keyring).resolve()
        if not path.is_relative_to(REPO_ROOT.resolve()):
            die(f"keyring path escapes repository root: {keyring}")
        if not path.exists():
            die(f"keyring file not found: {path}")
        return path


def helm_verify(repository: str, version: str, keyring: str) -> str | None:
    """Pull the chart from *repository* and verify its Helm provenance.

    Uses ``helm pull --prov --verify`` and the supplied keyring.
    The downloaded chart archive is discarded (stored in a temp directory).

    Returns the resolved digest (``sha256:...``) as reported by Helm,
    or ``None`` if the output could not be parsed.  The caller MUST
    compare this against the digest from ``oras_resolve`` to close the
    TOCTOU window between resolution and verification.
    """
    keyring_path = fetch_keyring(keyring)
    oci_ref = f"oci://{repository}"
    with tempfile.TemporaryDirectory() as tmpdir:
        result = run(
            [
                "helm", "pull", oci_ref,
                "--version", version,
                "--prov",
                "--verify",
                "--keyring", str(keyring_path),
                "--destination", tmpdir,
            ],
            timeout=SUBCOMMAND_TIMEOUT,
        )
    # Helm prints "Digest: sha256:..." to stderr on successful pull.
    for line in result.stderr.splitlines():
        if line.startswith("Digest:"):
            return line.split(":", 1)[1].strip()
    return None


def oras_copy(source_ref: str, dest_ref: str) -> None:
    """Copy an OCI artifact from source to destination with ``oras copy``."""
    run(["oras", "copy", source_ref, dest_ref], timeout=SUBCOMMAND_TIMEOUT)


def cosign_sign(repository: str, digest: str) -> None:
    """Sign the OCI artifact at *digest* with cosign (keyless / OIDC).

    Checks for an existing signature first to avoid duplicate signatures
    on re-runs.
    """
    ref = f"{repository}@{digest}"
    verify = subprocess.run(
        ["cosign", "verify", ref,
         "--certificate-identity-regexp", "^https://github.com/vexxhost/charts/.github/workflows/mirror.yaml@refs/heads/main$",
         "--certificate-oidc-issuer", "https://token.actions.githubusercontent.com"],
        cwd=REPO_ROOT, text=True, capture_output=True, timeout=SUBCOMMAND_TIMEOUT,
    )
    if verify.returncode == 0:
        print("    cosign signature already present, skipping")
        return
    run(["cosign", "sign", "--yes", ref], timeout=SUBCOMMAND_TIMEOUT)


# ---------------------------------------------------------------------------
# core
# ---------------------------------------------------------------------------


def load_manifests() -> list[tuple[str, dict]]:
    """Load every YAML file under ``mirrors/``.

    Returns ``[(filename, manifest), ...]`` sorted by filename.
    """
    if not MIRRORS_DIR.is_dir():
        die(f"mirrors directory not found: {MIRRORS_DIR}")
    manifests = []
    for yaml_file in sorted(MIRRORS_DIR.glob("*.yaml")):
        try:
            with open(yaml_file) as fh:
                doc = yaml.safe_load(fh)
        except (OSError, yaml.YAMLError) as exc:
            die(f"failed to read {yaml_file}: {exc}")
        if doc is None:
            die(f"empty or null YAML document in {yaml_file}")
        if not isinstance(doc, dict):
            die(f"expected a mapping in {yaml_file}, got {type(doc).__name__}")
        manifests.append((yaml_file.name, doc))
    if not manifests:
        die("no mirror manifests found in mirrors/")
    return manifests


def load_schema() -> dict:
    """Load the JSON Schema for mirror manifests."""
    if not SCHEMA_PATH.exists():
        die(f"schema file not found: {SCHEMA_PATH}")
    try:
        with open(SCHEMA_PATH) as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        die(f"failed to read schema: {exc}")


def validate_manifests(manifests: list[tuple[str, dict]], schema: dict) -> bool:
    """Validate every manifest against the schema.  Returns True on success."""
    ok = True
    for name, manifest in manifests:
        try:
            jsonschema.validate(manifest, schema)
        except jsonschema.ValidationError as exc:
            ok = False
            print(f"{name}: validation error: {exc}", file=sys.stderr)
    return ok


def filter_manifests(
    manifests: list[tuple[str, dict]],
    chart: str | None,
    version: str | None,
) -> list[tuple[str, dict]]:
    """Return ``[(chart_name, manifest), ...]``, optionally filtered."""
    result = []
    for name, manifest in manifests:
        dest_repo = manifest["destination"]["repository"]
        chart_name = dest_repo.rsplit("/", 1)[-1]
        if chart and chart_name != chart:
            continue
        if version:
            versions = manifest.get("versions", [])
            if version not in versions:
                continue
        result.append((chart_name, manifest))
    return result


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


_VERSION_PATTERN = re.compile(r"^v\d+\.\d+\.\d+$")


def main() -> None:
    parser = argparse.ArgumentParser(description="Mirror external Helm charts")
    parser.add_argument("--validate-only", action="store_true", help="Validate manifests and exit")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without making changes")
    parser.add_argument("--chart", default=os.environ.get("MIRROR_CHART") or None, help="Process only the named chart")
    parser.add_argument("--version", default=os.environ.get("MIRROR_VERSION") or None, help="Process only the given version tag")
    args = parser.parse_args()

    if args.version and not _VERSION_PATTERN.match(args.version):
        die(f"--version must match v<major>.<minor>.<patch> (e.g. v1.2.3), got: {args.version}")

    manifests = load_manifests()
    schema = load_schema()

    if not validate_manifests(manifests, schema):
        die("manifest validation failed")

    if args.validate_only:
        print("All manifests are valid.")
        return

    selected = filter_manifests(manifests, args.chart, args.version)
    if not selected:
        die("no matching manifests after filtering")

    errors: list[str] = []

    for chart_name, manifest in selected:
        source_repo = manifest["source"]["repository"]
        dest_repo = manifest["destination"]["repository"]
        provenance = manifest.get("provenance", {})

        versions = manifest.get("versions", [])
        if args.version:
            versions = [args.version]

        for ver in versions:
            print(f"--- {chart_name} {ver} ---")

            # 1. Resolve source digest
            print(f"  resolving source: {source_repo}:{ver}")
            try:
                source_ref = oras_resolve(source_repo, ver)
                source_digest = source_ref.split("@")[-1]
            except SystemExit:
                errors.append(f"{chart_name} {ver}: source resolution failed")
                continue
            print(f"    -> {source_ref}")

            # 2. Verify upstream provenance (read-only, runs in both modes)
            if provenance and provenance.get("required", True):
                keyring = provenance.get("keyring")
                if not keyring:
                    errors.append(f"{chart_name} {ver}: provenance.required is true but no keyring configured")
                    continue
                print(f"  verifying provenance (keyring={keyring})")
                try:
                    verified_digest = helm_verify(source_repo, ver, keyring)
                except SystemExit:
                    errors.append(f"{chart_name} {ver}: provenance verification failed")
                    continue
                if verified_digest and verified_digest != source_digest:
                    errors.append(
                        f"{chart_name} {ver}: verified digest {verified_digest} does not match "
                        f"resolved digest {source_digest}; tag may have been repointed"
                    )
                    continue
                if not verified_digest:
                    print("    warning: could not parse verified digest from Helm output")
                print("    provenance OK")
            elif provenance:
                print("  provenance: verification not required (required: false), skipping")
            else:
                print("  provenance: no keyring configured, skipping verification")

            # 3. Check destination before copying (avoid overwriting existing tag)
            dest_tag_ref = f"{dest_repo}:{ver}"
            if not args.dry_run:
                dest_exists = subprocess.run(
                    ["oras", "resolve", dest_tag_ref],
                    cwd=REPO_ROOT, text=True, capture_output=True, timeout=SUBCOMMAND_TIMEOUT,
                )
                if dest_exists.returncode == 0:
                    existing_digest = dest_exists.stdout.strip().split("@")[-1]
                    if existing_digest == source_digest:
                        print(f"  destination {dest_tag_ref} already has correct digest, skipping copy")
                        # Still sign if needed (cosign_sign has its own pre-check)
                        print(f"  signing {dest_repo}@{source_digest}")
                        try:
                            cosign_sign(dest_repo, source_digest)
                        except SystemExit:
                            errors.append(f"{chart_name} {ver}: cosign sign failed")
                        print("  done.")
                        continue
                    else:
                        errors.append(
                            f"{chart_name} {ver}: destination exists with different digest "
                            f"({existing_digest}), refusing to overwrite"
                        )
                        continue

            # 4. Copy with ORAS
            print(f"  copying {source_ref} -> {dest_tag_ref}")
            if not args.dry_run:
                try:
                    oras_copy(source_ref, dest_tag_ref)
                except SystemExit:
                    errors.append(f"{chart_name} {ver}: oras copy failed")
                    continue
            else:
                print(f"    [DRY-RUN] oras copy {source_ref} {dest_tag_ref}")

            # 5. Post-copy: verify destination digest matches
            print("  verifying destination digest")
            if not args.dry_run:
                try:
                    dest_ref = oras_resolve(dest_repo, ver)
                except SystemExit:
                    errors.append(f"{chart_name} {ver}: destination resolution failed")
                    continue
                dest_digest = dest_ref.split("@")[-1]
                if dest_digest != source_digest:
                    errors.append(f"{chart_name} {ver}: digest mismatch source={source_digest} dest={dest_digest}")
                    continue
                print(f"    digest OK: {dest_digest}")
            else:
                print(f"    [DRY-RUN] oras resolve {dest_tag_ref}")

            # 6. Sign with cosign
            if not args.dry_run:
                print(f"  signing {dest_repo}@{source_digest}")
                try:
                    cosign_sign(dest_repo, source_digest)
                except SystemExit:
                    errors.append(f"{chart_name} {ver}: cosign sign failed")
                    continue
            else:
                print(f"    [DRY-RUN] cosign sign --yes {dest_repo}@{source_digest}")

            print("  done.")

    if errors:
        print(f"\n{len(errors)} error(s) occurred:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(1)

    print("All mirrors processed.")


if __name__ == "__main__":
    main()
