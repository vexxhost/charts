# VEXXHOST Helm Charts

Helm charts published as OCI artifacts to `ghcr.io/vexxhost/charts`.

## Charts

| Chart | Description |
|-------|-------------|
| [loopback-block](charts/loopback-block/) | Creates loopback block devices for Rook-Ceph OSDs |

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
