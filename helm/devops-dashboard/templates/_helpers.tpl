{{- define "devops-dashboard.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "devops-dashboard.fullname" -}}
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

{{- define "devops-dashboard.backend.fullname" -}}
{{- printf "%s-backend" (include "devops-dashboard.fullname" .) }}
{{- end }}

{{- define "devops-dashboard.frontend.fullname" -}}
{{- printf "%s-frontend" (include "devops-dashboard.fullname" .) }}
{{- end }}

{{- define "devops-dashboard.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{ include "devops-dashboard.selectorLabels" . }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "devops-dashboard.selectorLabels" -}}
app.kubernetes.io/name: {{ include "devops-dashboard.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
