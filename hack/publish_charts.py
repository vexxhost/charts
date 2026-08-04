# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "pyyaml",
# ]
# ///
"""Publish authored and patched-vendor Helm charts as immutable OCI artifacts.

Existing tags are pulled and compared by packaged chart contents. Identical
content is left untouched and signed if needed; different content is rejected.
New artifacts are resolved by digest after push and signed by digest with
GitHub Actions OIDC.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import stat
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SUBCOMMAND_TIMEOUT = 300
CERTIFICATE_IDENTITY = (
    r"^https://github\.com/vexxhost/charts/\.github/workflows/"
    r"publish\.yaml@refs/heads/main$"
)
OIDC_ISSUER = "https://token.actions.githubusercontent.com"


def die(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def run(
    command: list[str], *, check: bool = True, cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            cwd=cwd or REPO_ROOT,
            text=True,
            capture_output=True,
            check=check,
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


def safe_extract(archive: Path, destination: Path) -> Path:
    root = destination.resolve()
    with tarfile.open(archive, "r:gz") as stream:
        for member in stream.getmembers():
            target = (destination / member.name).resolve()
            if not target.is_relative_to(root):
                die(f"archive member escapes extraction directory: {member.name}")
            if member.isdev() or member.isfifo() or member.issym() or member.islnk():
                die(f"unsupported special file in chart archive: {member.name}")
        stream.extractall(destination)
    chart_roots = [path for path in destination.iterdir() if path.is_dir()]
    if len(chart_roots) != 1 or not (chart_roots[0] / "Chart.yaml").is_file():
        die(f"archive does not contain exactly one chart: {archive}")
    return chart_roots[0]


def tree_manifest(root: Path) -> dict[str, tuple[str, int, str]]:
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


def destination_digest(reference: str) -> str | None:
    result = run(["oras", "resolve", "--full-reference", reference], check=False)
    if result.returncode == 0:
        resolved = result.stdout.strip()
        if "@sha256:" not in resolved:
            die(f"oras returned an invalid reference for {reference}: {resolved}")
        return resolved.split("@", 1)[1]
    error = f"{result.stdout}\n{result.stderr}".lower()
    if any(
        marker in error
        for marker in (
            "not found",
            "manifest unknown",
            "name unknown",
            "name_unknown",
            "404",
        )
    ):
        return None
    die(f"failed to resolve {reference}: {result.stderr.strip()}")


def sign(repository: str, digest: str) -> None:
    reference = f"{repository}@{digest}"
    verification = run(
        [
            "cosign",
            "verify",
            reference,
            "--certificate-identity-regexp",
            CERTIFICATE_IDENTITY,
            "--certificate-oidc-issuer",
            OIDC_ISSUER,
        ],
        check=False,
    )
    if verification.returncode == 0:
        print("  cosign signature already present")
        return
    run(["cosign", "sign", "--yes", reference])
    print("  cosign signature added")


def write_outputs(
    repository: str, name: str, version: str, digest: str | None, action: str
) -> None:
    reference = repository
    if digest:
        reference = f"{reference}@{digest}"
    if output_path := os.environ.get("GITHUB_OUTPUT"):
        with Path(output_path).open("a") as stream:
            stream.write(
                f"digest={digest or ''}\nreference={reference}\naction={action}\n"
            )
    if summary_path := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(summary_path).open("a") as stream:
            stream.write("| Chart | Version | Digest | Result |\n")
            stream.write("| --- | --- | --- | --- |\n")
            stream.write(
                f"| `{name}` | `{version}` | `{digest or 'not published'}` | {action} |\n"
            )


def publish(chart_value: str, registry: str, *, check_only: bool) -> None:
    chart = (REPO_ROOT / chart_value).resolve()
    charts_root = (REPO_ROOT / "charts").resolve()
    if chart.parent != charts_root or not (chart / "Chart.yaml").is_file():
        die(f"chart must be an immediate child of charts/: {chart_value}")
    metadata = yaml.safe_load((chart / "Chart.yaml").read_text())
    name = metadata.get("name")
    version = str(metadata.get("version", ""))
    if not name or not version or chart.name != name:
        die(f"invalid chart name or version in {chart / 'Chart.yaml'}")

    repository = f"{registry.rstrip('/')}/{name}"
    tagged_reference = f"{repository}:{version}"
    print(f"--- {name} {version} ---")

    with tempfile.TemporaryDirectory(prefix=f"publish-{name}-") as temporary:
        workspace = Path(temporary)
        package_dir = workspace / "local"
        package_dir.mkdir()
        run(["helm", "package", str(chart), "--destination", str(package_dir)])
        packages = list(package_dir.glob("*.tgz"))
        if len(packages) != 1:
            die(f"helm package produced {len(packages)} archives for {name}")
        local_package = packages[0]
        local_root = safe_extract(local_package, workspace / "local-extracted")

        digest = destination_digest(tagged_reference)
        if digest:
            print(f"  destination exists: {repository}@{digest}")
            remote_dir = workspace / "remote"
            remote_dir.mkdir()
            run(
                [
                    "helm",
                    "pull",
                    f"oci://{repository}",
                    "--version",
                    version,
                    "--destination",
                    str(remote_dir),
                ]
            )
            remote_packages = list(remote_dir.glob("*.tgz"))
            if len(remote_packages) != 1:
                die(
                    f"helm pull produced {len(remote_packages)} archives for {tagged_reference}"
                )
            remote_root = safe_extract(
                remote_packages[0], workspace / "remote-extracted"
            )
            if tree_manifest(local_root) != tree_manifest(remote_root):
                die(
                    f"{tagged_reference} already exists with different chart content; "
                    "increment Chart.yaml version"
                )
            action = "unchanged"
            print("  existing chart content is identical; push skipped")
        elif check_only:
            action = "available"
            print(f"  destination tag is available: {tagged_reference}")
        else:
            run(["helm", "push", str(local_package), f"oci://{registry.rstrip('/')}"])
            digest = destination_digest(tagged_reference)
            if digest is None:
                die(f"destination did not resolve after push: {tagged_reference}")
            action = "published"
            print(f"  resolved digest: {digest}")

            verification_dir = workspace / "published"
            verification_dir.mkdir()
            run(
                [
                    "helm",
                    "pull",
                    f"oci://{repository}",
                    "--version",
                    version,
                    "--destination",
                    str(verification_dir),
                ]
            )
            published_package = next(verification_dir.glob("*.tgz"), None)
            if published_package is None:
                die(f"published chart could not be pulled: {tagged_reference}")
            published_root = safe_extract(
                published_package, workspace / "published-extracted"
            )
            if tree_manifest(local_root) != tree_manifest(published_root):
                die(
                    f"published chart content differs from local package: {tagged_reference}"
                )

        if digest and not check_only:
            sign(repository, digest)
        write_outputs(repository, name, version, digest, action)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chart", required=True, help="chart directory under charts/")
    parser.add_argument(
        "--registry",
        default="ghcr.io/vexxhost/charts",
        help="destination OCI registry path",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="check destination immutability without writes",
    )
    arguments = parser.parse_args()
    publish(arguments.chart, arguments.registry, check_only=arguments.check_only)


if __name__ == "__main__":
    main()
