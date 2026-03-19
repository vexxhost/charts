{{- define "loopback-block.fullname" -}}
{{ .Release.Name }}
{{- end -}}

{{- define "loopback-block.labels" -}}
app.kubernetes.io/name: loopback-block
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.Version }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "loopback-block.selectorLabels" -}}
app.kubernetes.io/name: loopback-block
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}
