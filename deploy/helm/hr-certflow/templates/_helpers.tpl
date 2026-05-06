{{- define "hr-certflow.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "hr-certflow.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "hr-certflow.labels" -}}
app.kubernetes.io/name: {{ include "hr-certflow.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
shared-k3s.io/project: hr-certflow
{{- end -}}

{{- define "hr-certflow.selectorLabels" -}}
app.kubernetes.io/name: {{ include "hr-certflow.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "hr-certflow.intOrPercent" -}}
{{- $value := toString . -}}
{{- if regexMatch "^[0-9]+$" $value -}}
{{- $value -}}
{{- else -}}
{{- $value | quote -}}
{{- end -}}
{{- end -}}
