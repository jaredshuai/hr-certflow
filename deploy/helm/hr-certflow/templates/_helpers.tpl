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

{{- /*
GlitchTip 事件聚合用的 release 版本号：显式传入 glitchtip.release 时优先；
留空或未设置时回退为当前 web 镜像 tag，使发版（只更新 images.web.tag）后
错误监控 release 自动对齐，无需手工同步 Argo 参数。dig 保证 glitchtip/images
任一层缺失时仍安全回退。
*/ -}}
{{- define "hr-certflow.glitchtipRelease" -}}
{{- $values := .Values | deepCopy | mustToJson | mustFromJson -}}
{{- $explicit := dig "glitchtip" "release" "" $values -}}
{{- $webTag := dig "images" "web" "tag" "" $values -}}
{{- default $webTag $explicit -}}
{{- end -}}
