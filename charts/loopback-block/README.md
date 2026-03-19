# loopback-block

Deploys a DaemonSet that creates loopback block devices using sparse files
attached via `losetup`. This is useful for providing block devices to
Rook-Ceph OSDs on nodes that do not have physical block devices available.

## Usage

```bash
helm install loopback-block oci://ghcr.io/vexxhost/charts/loopback-block --version 0.1.0
```

## Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `image.repository` | Container image repository | `busybox` |
| `image.tag` | Container image tag | `latest` |
| `devices` | List of loop devices to create | See below |
| `devices[].path` | Device path for the loop device | `/dev/loop0` |
| `devices[].file` | Backing sparse file path | `/var/lib/loopback-block/loop0.img` |
| `devices[].sizeMB` | Size of the sparse file in MB | `10240` |
| `nodeSelector` | Node selector for pod scheduling | `{}` |
| `affinity` | Pod affinity rules | Excludes control-plane nodes |
| `tolerations` | Pod tolerations | Tolerate all taints |
| `resources` | Container resource requests/limits | 10m CPU, 16-32Mi memory |

## Multiple Devices

To create multiple loopback devices, add entries to the `devices` list:

```yaml
devices:
  - path: /dev/loop0
    file: /var/lib/loopback-block/loop0.img
    sizeMB: 10240
  - path: /dev/loop1
    file: /var/lib/loopback-block/loop1.img
    sizeMB: 10240
```
