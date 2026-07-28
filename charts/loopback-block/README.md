# loopback-block

Deploys a DaemonSet that creates loopback block devices using sparse files
attached via `losetup`. This is useful for providing block devices to
Rook-Ceph OSDs on nodes that do not have physical block devices available.

## Usage

```bash
helm install loopback-block oci://ghcr.io/vexxhost/charts/loopback-block --version 0.1.1
```

The DaemonSet registers a missing `/dev/loopN` device through
`/dev/loop-control` before creating its device node and attaching the sparse
backing file. Device paths must use that exact naming format so the chart can
derive the Linux loop-device minor number safely. The container image must
provide the util-linux implementation of `losetup`.

Recent `ceph-volume` versions require a running udev daemon and populated
`/run/udev/data` on each storage node. This chart creates loop devices but
does not install or manage udev; clusters using those Ceph versions must
provide it separately.

## Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `image.repository` | Container image repository | `docker.io/library/debian` |
| `image.tag` | Container image tag | `trixie-slim` |
| `image.pullPolicy` | Container image pull policy | `IfNotPresent` |
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
