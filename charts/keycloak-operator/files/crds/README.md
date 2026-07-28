# Vendored Keycloak CRDs

These generated CRDs are copied without modification from
`https://github.com/keycloak/keycloak-k8s-resources` tag `26.6.4`:

| File | Upstream Git blob |
| ------ | ------------------- |
| `keycloaks.k8s.keycloak.org-v1.yml` | `2c04048534f5a5959ddeefadb76a1d92c2cb819b` |
| `keycloakrealmimports.k8s.keycloak.org-v1.yml` | `d3fe326363840ed7c755e1d40a9e8067d9ab8378` |

`templates/crds.yaml` loads these files and adds Helm lifecycle annotations
while rendering them. Keeping the generated files unchanged makes future
upstream comparisons reproducible.
