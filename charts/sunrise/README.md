# sunrise

Deploys [Sunrise](https://github.com/vexxhost/sunrise), a horizontally scalable
OpenStack dashboard, as a non-root workload with a read-only root filesystem.

## Usage

```bash
helm upgrade --install sunrise \
  oci://ghcr.io/vexxhost/charts/sunrise \
  --version 0.1.0 \
  --namespace openstack \
  --create-namespace \
  --values sunrise-values.yaml
```

The image defaults to `ghcr.io/vexxhost/sunrise:main`. Set `image.digest` to
deploy an immutable image; when a digest is set it takes precedence over
`image.tag`.

## Runtime configuration

The chart accepts native Kubernetes environment sources. Keep non-sensitive
settings in `configMap.data`, and use `env` or `envFrom` for externally managed
Secrets and ConfigMaps. Explicit `env` entries take precedence over keys loaded
through `envFrom`.

```yaml
configMap:
  data:
    SUNRISE_DASHBOARD_URL: https://sunrise.example.com
    KEYSTONE_API: http://keystone-api.openstack.svc:5000
    KEYSTONE_PUBLIC_API: https://identity.example.com
    KEYSTONE_FEDERATION_IDENTITY_PROVIDERS: atmosphere
    SUNRISE_KEYCLOAK_ISSUER_ATMOSPHERE: https://keycloak.example.com/realms/atmosphere
    SUNRISE_KEYCLOAK_CLIENT_ID_ATMOSPHERE: sunrise-server
    SUNRISE_SESSION_BACKEND: redis
    SUNRISE_REDIS_URL: rediss://redis.example.com:6379

envFrom:
  - secretRef:
      name: sunrise-runtime
```

The referenced Secret should contain at least the stable session secret and
the confidential client secret for each configured identity provider:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: sunrise-runtime
type: Opaque
stringData:
  SUNRISE_SESSION_SECRET: replace-with-at-least-32-random-characters
  SUNRISE_KEYCLOAK_CLIENT_SECRET_ATMOSPHERE: replace-me
```

`secret.create` is available for development and simple installations, but its
values are retained in Helm release history. Production deployments should
prefer an externally managed Secret. The full application environment is
documented in Sunrise's
[`env.dist`](https://github.com/vexxhost/sunrise/blob/main/.env.dist).

Changes to the chart-managed ConfigMap or Secret update pod-template checksum
annotations and trigger a rollout. To roll pods when external resources change,
install Stakater Reloader and set `reloader.enabled=true`, or use an equivalent
platform mechanism.

## Network exposure

The Service is always created as `ClusterIP` by default. Both optional public
entry points are disabled by default so a platform such as Atmosphere can own
network exposure independently through Ansible:

```yaml
ingress:
  enabled: false

httpRoute:
  enabled: false
```

To let the chart create a standard Kubernetes Ingress:

```yaml
ingress:
  enabled: true
  className: atmosphere
  annotations:
    cert-manager.io/cluster-issuer: production
    nginx.ingress.kubernetes.io/affinity: cookie
    nginx.ingress.kubernetes.io/affinity-mode: persistent
    nginx.ingress.kubernetes.io/session-cookie-change-on-failure: "false"
    nginx.ingress.kubernetes.io/session-cookie-expires: "86400"
    nginx.ingress.kubernetes.io/session-cookie-max-age: "86400"
    nginx.ingress.kubernetes.io/session-cookie-name: sunrise-affinity
    nginx.ingress.kubernetes.io/session-cookie-path: /
    nginx.ingress.kubernetes.io/session-cookie-samesite: Lax
    nginx.ingress.kubernetes.io/session-cookie-secure: "true"
  hosts:
    - host: sunrise.example.com
      paths:
        - path: /
          pathType: Prefix
  tls:
    - secretName: sunrise-tls
      hosts:
        - sunrise.example.com
```

For an ingress-nginx-compatible controller, configure the persistent cookie-
affinity annotations shown above, matching Sunrise's
[kind deployment](https://github.com/vexxhost/sunrise/blob/main/deploy/k8s/kind/sunrise-ingress.yaml).
The dedicated cookie keeps a browser on the same ready Sunrise endpoint during
rolling updates, avoiding mixed application assets between overlapping builds.
It is separate from the encrypted Sunrise authentication session and does not
replace the shared Redis session store.

To let the chart create a Gateway API HTTPRoute, the Gateway API CRDs and a
compatible controller such as Envoy Gateway must already be installed:

```yaml
httpRoute:
  enabled: true
  parentRefs:
    - name: gateway
      namespace: envoy-gateway-system
  hostnames:
    - sunrise.example.com
```

Cookie-based endpoint persistence is preconfigured under
`httpRoute.sessionPersistence` and is rendered when the chart-managed
HTTPRoute is enabled. It requires support for the Gateway API extended feature.
When Atmosphere owns the Ingress or HTTPRoute, leave both chart resources
disabled and target the chart's Service. The platform-managed resource must
configure equivalent cookie persistence; the chart cannot add annotations or
route rules to a resource it does not own.

## Availability and security

The default three-replica deployment expects an external Redis-compatible session
store. `/healthz` is used for startup and liveness probes; `/readyz` verifies the
configured Redis dependency before a pod receives traffic. A PodDisruptionBudget
is enabled by default, and the deployment uses a short pre-stop drain so ingress
and Gateway data planes can converge during rolling updates.

Bounded `emptyDir` volumes provide the writable paths required by Sunrise. The
pod and container security contexts otherwise enforce non-root execution,
seccomp, dropped Linux capabilities, and a read-only root filesystem.

## Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `replicaCount` | Number of replicas when autoscaling is disabled | `3` |
| `image.repository` | Sunrise image repository | `ghcr.io/vexxhost/sunrise` |
| `image.tag` | Sunrise image tag | `main` |
| `image.digest` | Optional image digest, taking precedence over the tag | `""` |
| `configMap.create` | Create the non-sensitive runtime ConfigMap | `true` |
| `configMap.data` | Non-sensitive Sunrise environment variables | See `values.yaml` |
| `secret.create` | Create an Opaque runtime Secret | `false` |
| `env` | Additional Kubernetes `EnvVar` entries | `[]` |
| `envFrom` | Additional Kubernetes `EnvFromSource` entries | `[]` |
| `reloader.enabled` | Add the Stakater Reloader auto annotation | `false` |
| `service.type` | Kubernetes Service type | `ClusterIP` |
| `service.port` | Kubernetes Service port | `80` |
| `ingress.enabled` | Create a Kubernetes Ingress | `false` |
| `httpRoute.enabled` | Create a Gateway API HTTPRoute | `false` |
| `autoscaling.enabled` | Create a HorizontalPodAutoscaler | `false` |
| `podDisruptionBudget.enabled` | Create a PodDisruptionBudget | `true` |
| `resources` | Container resource requests and limits | See `values.yaml` |
| `nodeSelector` | Pod node selector | `{}` |
| `tolerations` | Pod tolerations | `[]` |
| `affinity` | Pod affinity rules | `{}` |
| `topologySpreadConstraints` | Pod topology spread constraints | `[]` |
