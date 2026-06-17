# VEXXHOST Helm Charts

Helm charts published as OCI artifacts to `ghcr.io/vexxhost/charts`.

## Charts

| Chart | Description |
|-------|-------------|
| [loopback-block](charts/loopback-block/) | Creates loopback block devices for Rook-Ceph OSDs |

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
  --certificate-identity-regexp '^https://github.com/vexxhost/charts/.github/workflows/mirror.yaml@refs/heads/main$' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
```

## Development

Lint the charts:

```bash
ct lint --config ct.yaml
```

Run integration tests with kind:

```bash
kind create cluster
ct install --config ct.yaml
kind delete cluster
```

### Mirror manifests

Validate mirror manifests locally:

```bash
nix-shell -p uv kubernetes-helm oras cosign --run "uv run hack/mirror_charts.py --validate-only"
```

Dry-run the mirror process (resolves sources, verifies provenance, skips writes):

```bash
nix-shell -p uv kubernetes-helm oras cosign --run "uv run hack/mirror_charts.py --dry-run --chart cert-manager"
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
