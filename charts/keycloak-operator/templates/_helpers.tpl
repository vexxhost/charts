{{/*
Expand the name of the chart.
*/}}
{{- define "keycloak-operator.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "keycloak-operator.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create the chart name and version used by the chart label.
*/}}
{{- define "keycloak-operator.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels.
*/}}
{{- define "keycloak-operator.labels" -}}
helm.sh/chart: {{ include "keycloak-operator.chart" . }}
{{ include "keycloak-operator.selectorLabels" . }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels.
*/}}
{{- define "keycloak-operator.selectorLabels" -}}
app.kubernetes.io/name: {{ include "keycloak-operator.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Pod labels with immutable selector labels taking precedence over user labels.
*/}}
{{- define "keycloak-operator.podLabels" -}}
{{- $podLabels := deepCopy (.Values.podLabels | default dict) -}}
{{- $selectorLabels := include "keycloak-operator.selectorLabels" . | fromYaml -}}
{{- mergeOverwrite $podLabels $selectorLabels | toYaml -}}
{{- end }}

{{/*
Create the name of the service account to use.
*/}}
{{- define "keycloak-operator.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "keycloak-operator.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- required "serviceAccount.name must be set when serviceAccount.create is false" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Build an image reference with optional tag or digest.
*/}}
{{- define "keycloak-operator.image" -}}
{{- if .Values.image.digest -}}
{{ printf "%s@%s" .Values.image.repository .Values.image.digest }}
{{- else -}}
{{ printf "%s:%s" .Values.image.repository (.Values.image.tag | default .Chart.AppVersion) }}
{{- end -}}
{{- end }}

{{/*
Build the related Keycloak image reference with optional tag or digest.
*/}}
{{- define "keycloak-operator.keycloakImage" -}}
{{- if .Values.keycloakImage.digest -}}
{{ printf "%s@%s" .Values.keycloakImage.repository .Values.keycloakImage.digest }}
{{- else -}}
{{ printf "%s:%s" .Values.keycloakImage.repository (.Values.keycloakImage.tag | default .Chart.AppVersion) }}
{{- end -}}
{{- end }}
