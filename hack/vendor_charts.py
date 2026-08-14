# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "pyyaml",
#     "jsonschema",
#     "requests",
# ]
# ///
"""Reproducibly generate patched charts from verified upstream releases.

Each manifest under ``vendors/`` pins the upstream chart archive, Helm
provenance file, signing key, reference artifacts, and ordered patch series.
The generated chart is committed under ``charts/`` so consumers never need the
vendoring toolchain.

Usage:
  uv run hack/vendor_charts.py --validate-only
  uv run hack/vendor_charts.py --check
  uv run hack/vendor_charts.py --chart cloudnative-pg
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

import jsonschema
import requests
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
VENDORS_DIR = REPO_ROOT / "vendors"
SCHEMA_PATH = REPO_ROOT / "schemas" / "chart-vendor.schema.json"
HTTP_TIMEOUT = 60
SUBCOMMAND_TIMEOUT = 300


def die(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def run(
    command: list[str], *, cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            cwd=cwd or REPO_ROOT,
            text=True,
            capture_output=True,
            check=True,
            timeout=SUBCOMMAND_TIMEOUT,
        )
    except FileNotFoundError:
        die(f"required binary not found: {command[0]}")
    except subprocess.CalledProcessError as exc:
        for output in (exc.stdout, exc.stderr):
            if output:
                print(output.strip(), file=sys.stderr)
        die(f"command failed: {' '.join(command)}")
    except subprocess.TimeoutExpired:
        die(f"command timed out: {' '.join(command)}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download(specification: dict[str, str], destination: Path) -> None:
    try:
        response = requests.get(specification["url"], timeout=HTTP_TIMEOUT)
        response.raise_for_status()
    except requests.RequestException as exc:
        die(f"download failed for {specification['url']}: {exc}")
    destination.write_bytes(response.content)
    actual = sha256(destination)
    expected = specification["sha256"]
    if actual != expected:
        die(
            f"checksum mismatch for {specification['url']}: expected {expected}, got {actual}"
        )


def safe_extract(archive: Path, destination: Path) -> None:
    root = destination.resolve()
    with tarfile.open(archive, "r:gz") as stream:
        for member in stream.getmembers():
            target = (destination / member.name).resolve()
            if not target.is_relative_to(root):
                die(f"archive member escapes extraction directory: {member.name}")
            if member.isdev() or member.isfifo() or member.issym() or member.islnk():
                die(f"unsupported special file in chart archive: {member.name}")
        stream.extractall(destination)


def load_manifests() -> list[tuple[Path, dict]]:
    if not VENDORS_DIR.is_dir():
        die(f"vendor manifest directory not found: {VENDORS_DIR}")
    schema = json.loads(SCHEMA_PATH.read_text())
    manifests: list[tuple[Path, dict]] = []
    errors: list[str] = []
    for path in sorted(VENDORS_DIR.glob("*.yaml")):
        try:
            manifest = yaml.safe_load(path.read_text())
            jsonschema.validate(
                manifest, schema, format_checker=jsonschema.FormatChecker()
            )
            manifests.append((path, manifest))
        except (yaml.YAMLError, jsonschema.ValidationError) as exc:
            errors.append(f"{path.relative_to(REPO_ROOT)}: {exc.message}")
    if errors:
        die("invalid vendor manifests:\n  - " + "\n  - ".join(errors))
    return manifests


def resolve_repository_path(value: str, *, expected_parent: Path | None = None) -> Path:
    path = (REPO_ROOT / value).resolve()
    if not path.is_relative_to(REPO_ROOT.resolve()):
        die(f"path escapes repository root: {value}")
    if expected_parent is not None and path.parent != expected_parent.resolve():
        die(f"destination must be an immediate child of {expected_parent}: {value}")
    return path


def verify_signing_key(key_path: Path, expected_fingerprint: str) -> Path:
    fingerprints = run(
        ["gpg", "--batch", "--show-keys", "--with-colons", str(key_path)]
    ).stdout.splitlines()
    primary = next(
        (line.split(":")[9] for line in fingerprints if line.startswith("fpr:")), None
    )
    if primary != expected_fingerprint:
        die(
            f"signing key fingerprint mismatch: expected {expected_fingerprint}, got {primary}"
        )
    keyring = key_path.with_suffix(".keyring.gpg")
    run(
        [
            "gpg",
            "--batch",
            "--yes",
            "--dearmor",
            "--output",
            str(keyring),
            str(key_path),
        ]
    )
    return keyring


def tree_manifest(root: Path) -> dict[str, tuple[str, int, str]]:
    if not root.exists():
        return {}
    entries: dict[str, tuple[str, int, str]] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        mode = stat.S_IMODE(path.lstat().st_mode)
        if path.is_symlink():
            entries[relative] = ("symlink", mode, os.readlink(path))
        elif path.is_file():
            entries[relative] = ("file", mode, sha256(path))
        elif path.is_dir():
            entries[relative] = ("directory", mode, "")
    return entries


def crds_by_name(documents: str) -> dict[str, dict]:
    crds: dict[str, dict] = {}
    for document in yaml.safe_load_all(documents):
        if (
            not isinstance(document, dict)
            or document.get("kind") != "CustomResourceDefinition"
        ):
            continue
        name = document.get("metadata", {}).get("name")
        if not name:
            die("CRD without metadata.name")
        if name in crds:
            die(f"duplicate CRD: {name}")
        crds[name] = document
    return crds


def verify_crds(chart_root: Path, reference_path: Path) -> None:
    rendered = run(
        [
            "helm",
            "template",
            "vendor-check",
            str(chart_root),
            "--show-only",
            "templates/crds/crds.yaml",
        ]
    ).stdout
    chart_crds = crds_by_name(rendered)
    reference_crds = crds_by_name(reference_path.read_text())
    for crd in chart_crds.values():
        annotations = crd.get("metadata", {}).get("annotations", {})
        annotations.pop("helm.sh/resource-policy", None)
    if chart_crds != reference_crds:
        chart_names = set(chart_crds)
        reference_names = set(reference_crds)
        details = []
        if chart_names != reference_names:
            details.append(
                f"chart={sorted(chart_names)}, reference={sorted(reference_names)}"
            )
        else:
            details.append(
                "changed="
                + str(
                    sorted(
                        name
                        for name in chart_names
                        if chart_crds[name] != reference_crds[name]
                    )
                )
            )
        die("rendered CRDs differ from pinned release manifest: " + "; ".join(details))
    print(f"  verified {len(chart_crds)} CRDs against {reference_path.name}")


def report_difference(expected: dict, actual: dict) -> None:
    expected_paths = set(expected)
    actual_paths = set(actual)
    for path in sorted(expected_paths - actual_paths):
        print(f"  missing: {path}")
    for path in sorted(actual_paths - expected_paths):
        print(f"  extra: {path}")
    for path in sorted(expected_paths & actual_paths):
        if expected[path] != actual[path]:
            print(f"  changed: {path}")


def generate_chart(manifest: dict, *, check: bool) -> bool:
    name = manifest["name"]
    destination = resolve_repository_path(
        manifest["destination"], expected_parent=REPO_ROOT / "charts"
    )
    print(f"--- {name} {manifest['upstreamVersion']} ---")

    with tempfile.TemporaryDirectory(prefix=f"vendor-{name}-") as temporary:
        workspace = Path(temporary)
        chart_path = workspace / f"{name}-{manifest['upstreamVersion']}.tgz"
        provenance_path = chart_path.with_suffix(chart_path.suffix + ".prov")
        key_path = workspace / "upstream-signing-key.asc"

        print("  downloading and verifying pinned sources")
        download(manifest["source"]["chart"], chart_path)
        download(manifest["source"]["provenance"], provenance_path)
        download(manifest["source"]["key"], key_path)
        reference_paths: dict[str, Path] = {}
        for reference in manifest.get("references", []):
            reference_path = workspace / reference["name"]
            download(reference, reference_path)
            reference_paths[reference["name"]] = reference_path

        keyring = verify_signing_key(key_path, manifest["source"]["key"]["fingerprint"])
        verification = run(
            ["helm", "verify", str(chart_path), "--keyring", str(keyring)]
        )
        print("  " + verification.stdout.strip().replace("\n", "\n  "))

        extracted = workspace / "extracted"
        extracted.mkdir()
        safe_extract(chart_path, extracted)
        chart_root = extracted / name
        if not (chart_root / "Chart.yaml").is_file():
            die(f"archive does not contain expected chart root: {name}")

        for patch_value in manifest["patches"]:
            patch_path = resolve_repository_path(patch_value)
            if not patch_path.is_file():
                die(f"patch not found: {patch_value}")
            print(f"  applying {patch_path.relative_to(REPO_ROOT)}")
            run(
                ["git", "apply", "--check", "--whitespace=error-all", str(patch_path)],
                cwd=extracted,
            )
            run(["git", "apply", "--whitespace=nowarn", str(patch_path)], cwd=extracted)

        if crd_reference := manifest.get("crdReference"):
            reference_path = reference_paths.get(crd_reference)
            if reference_path is None:
                die(f"CRD reference is not declared under references: {crd_reference}")
            verify_crds(chart_root, reference_path)

        generated = tree_manifest(chart_root)
        committed = tree_manifest(destination)
        if generated == committed:
            print("  generated chart is current")
            return False
        if check:
            print(f"  generated chart differs from {manifest['destination']}:")
            report_difference(generated, committed)
            return True

        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(chart_root, destination, symlinks=True)
        print(f"  updated {manifest['destination']}")
        return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chart", help="process one chart by name")
    parser.add_argument(
        "--check", action="store_true", help="fail if generated charts differ"
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="validate manifests without downloads",
    )
    arguments = parser.parse_args()

    manifests = load_manifests()
    if arguments.chart:
        manifests = [item for item in manifests if item[1]["name"] == arguments.chart]
        if not manifests:
            die(f"unknown vendored chart: {arguments.chart}")

    print(f"Validated {len(manifests)} vendor manifest(s).")
    if arguments.validate_only:
        return

    differences = False
    for _, manifest in manifests:
        differences = generate_chart(manifest, check=arguments.check) or differences
    if arguments.check and differences:
        die("vendored charts are not reproducible; run hack/vendor_charts.py")


if __name__ == "__main__":
    main()
