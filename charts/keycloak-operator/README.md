# keycloak-operator

Installs the Keycloak Operator and the `Keycloak` and `KeycloakRealmImport`
custom resource definitions.

The operator watches custom resources in the Helm release namespace. The chart
does not create `Keycloak` custom resources.

## Usage

```bash
helm upgrade --install keycloak-operator \
  oci://ghcr.io/vexxhost/charts/keycloak-operator \
  --version 0.1.0 \
  --namespace auth-system \
  --create-namespace
```

## CRD lifecycle

The CRDs are rendered as regular Helm resources rather than placed in Helm's
special `crds/` directory. This allows `helm upgrade` to update their schemas.
Both CRDs have the `helm.sh/resource-policy: keep` annotation, so uninstalling
the release does not delete custom resources managed by the operator.

To manage the CRDs outside this chart, set:

```yaml
crds:
  create: false
```

Do not change `crds.create` from `true` to `false` after the chart has taken
ownership without first planning the ownership transition.

If the CRDs were installed before this chart, a one-time installation with a
Helm version that supports resource adoption can take ownership:

```bash
helm upgrade --install keycloak-operator \
  oci://ghcr.io/vexxhost/charts/keycloak-operator \
  --version 0.1.0 \
  --namespace auth-system \
  --create-namespace \
  --take-ownership
```

CRDs are cluster-scoped. Installing the chart under another release name or
namespace requires an explicit CRD ownership decision.

## Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `replicaCount` | Number of operator replicas | `1` |
| `image.repository` | Keycloak Operator image repository | `quay.io/keycloak/keycloak-operator` |
| `image.tag` | Operator image tag; defaults to `appVersion` | `""` |
| `image.digest` | Optional operator image digest | `""` |
| `image.pullPolicy` | Operator image pull policy | `IfNotPresent` |
| `keycloakImage.repository` | Keycloak image used for managed instances | `quay.io/keycloak/keycloak` |
| `keycloakImage.tag` | Managed Keycloak image tag; defaults to `appVersion` | `""` |
| `keycloakImage.digest` | Optional managed Keycloak image digest | `""` |
| `imagePullSecrets` | Image pull secrets | `[]` |
| `crds.create` | Install and manage the Keycloak CRDs | `true` |
| `crds.annotations` | Additional annotations added to both CRDs | `{}` |
| `serviceAccount.create` | Create the operator service account | `true` |
| `serviceAccount.name` | Service account name override | `""` |
| `rbac.create` | Create the upstream operator RBAC resources | `true` |
| `service.type` | Operator health service type | `ClusterIP` |
| `service.port` | Operator health service port | `80` |
| `resources` | Operator resource requests and limits | See `values.yaml` |
| `additionalEnv` | Additional operator environment variables | `[]` |
| `nodeSelector` | Pod node selector | `{}` |
| `tolerations` | Pod tolerations | `[]` |
| `affinity` | Pod affinity rules | `{}` |
| `topologySpreadConstraints` | Pod topology spread constraints | `[]` |

The default manifests and CRDs are sourced from
[`keycloak-k8s-resources` 26.6.4](https://github.com/keycloak/keycloak-k8s-resources/tree/26.6.4/kubernetes).
