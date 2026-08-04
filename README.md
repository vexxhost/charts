# VEXXHOST Helm Charts

Helm charts published as OCI artifacts to `ghcr.io/vexxhost/charts`.

## Charts

| Chart | Description |
|-------|-------------|
| [cloudnative-pg](charts/cloudnative-pg/) | Patched CloudNativePG operator 1.28.4 based on upstream chart 0.27.1 |
| [keycloak-operator](charts/keycloak-operator/) | Installs the Keycloak Operator and its upgradeable CRDs |
| [loopback-block](charts/loopback-block/) | Creates loopback block devices for Rook-Ceph OSDs |

## Vendored Charts

Patched upstream charts are generated from manifests under `vendors/`. Each
manifest pins the upstream chart archive, Helm provenance, signing key, source
references, and ordered patch series. Generated charts are committed under
`charts/` and published through the same signed, immutable OCI workflow as
authored charts.

Regenerate all vendored charts:

```bash
nix develop --command uv run hack/vendor_charts.py
```

Verify that committed charts reproduce from their pinned inputs:

```bash
nix develop --command uv run hack/vendor_charts.py --check
```

## Mirrored Charts

External Helm charts are mirrored into `ghcr.io/vexxhost/charts` using ORAS.
Each mirror is declared in a YAML manifest under `mirrors/`, validated against
a [JSON Schema](schemas/chart-mirror.schema.json).

| Chart | Source |
|-------|--------|
| [cert-manager](mirrors/cert-manager.yaml) | `quay.io/jetstack/charts/cert-manager` |

### How mirroring works

1. **Resolve** the upstream version tag to a content-addressable digest (`oras resolve`).
2. **Verify** the upstream Helm provenance file (`.prov`) using the keyring
   specified in the manifest (`helm pull --prov --verify`).
3. **Copy** the exact OCI artifact to the destination repository with
   `oras cp source@sha256:<digest> destination:<version>`.  ORAS preserves
   all layers including the Helm provenance layer.
4. **Verify** the destination digest matches the source.
5. **Sign** the artifact with cosign using this repository's GitHub Actions
   OIDC identity.

### Consuming mirrored charts

Pull a chart with Helm:

```bash
helm pull oci://ghcr.io/vexxhost/charts/cert-manager --version v1.11.5
```

Verify Helm provenance with the upstream keyring:

```bash
helm pull oci://ghcr.io/vexxhost/charts/cert-manager \
  --version v1.11.5 --prov --verify \
  --keyring <cert-manager-keyring.gpg>
```

Verify the VEXXHOST cosign signature:

```bash
cosign verify ghcr.io/vexxhost/charts/cert-manager@sha256:<digest> \
  --certificate-identity-regexp '^https://github\.com/vexxhost/charts/\.github/workflows/mirror\.yaml@refs/heads/main$' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
```

## Development

Lint the charts:

```bash
ct lint --config ct.yaml
```

Run integration tests with kind:

```bash
kind create cluster --name chart-testing
ct install --config ct.yaml
kind delete cluster --name chart-testing
```

Authored and patched-vendor chart versions are immutable after publication.
Any content change requires a `Chart.yaml` version increment. The publishing
workflow reports the resolved OCI digest and signs that digest with cosign.

### Mirror manifests

The flake provides all required tools.  Use `nix develop` to enter a shell with
`uv`, `helm`, `oras`, and `cosign`:

```bash
nix develop
```

Validate mirror manifests locally:

```bash
nix develop --command uv run hack/mirror_charts.py --validate-only
```

Dry-run the mirror process (resolves sources, verifies provenance, skips writes):

```bash
nix develop --command uv run hack/mirror_charts.py --dry-run --chart cert-manager
```

### Adding a new mirror

1. Create a YAML file in `mirrors/` following the schema in
   `schemas/chart-mirror.schema.json`.  Include the modeline:
   ```yaml
   # yaml-language-server: $schema=../schemas/chart-mirror.schema.json
   ```
2. Test with `--validate-only` and `--dry-run`.
3. Open a PR — CI will validate the manifest and verify upstream provenance.
4. On merge to `main`, the mirror workflow copies and signs the chart.
