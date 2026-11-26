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
GlitchTip 事件聚合用的 release 版本号解析规则：
- 显式传入 glitchtip.release（任何非空白标量，含 "0"）优先，绝不被 default 吞掉；
- 留空或未设置时回退为当前 web 镜像 tag（images.web.tag），使发版（只更新镜像 tag）
  后错误监控 release 自动对齐，无需手工同步 Argo 参数；
- 回退值是 chart 默认占位 latest 或空串时返回空串（latest/空不是有意义的版本，
  注入会让事件全部聚到一个伪版本），由渲染侧省略 release 字段。
dig 保证 glitchtip/images 任一层缺失时仍安全回退；mustFromJson 先把 chartutil.Values
转成纯 map，dig 才能工作。
*/ -}}
{{- define "hr-certflow.glitchtipRelease" -}}
{{- $values := .Values | deepCopy | mustToJson | mustFromJson -}}
{{- $explicit := dig "glitchtip" "release" "" $values -}}
{{- $webTag := dig "images" "web" "tag" "" $values | toString -}}
{{- $explicitStr := toString $explicit -}}
{{- if ne (trim $explicitStr) "" -}}
{{- $explicitStr -}}
{{- else if and (ne $webTag "") (ne $webTag "latest") -}}
{{- $webTag -}}
{{- end -}}
{{- end -}}
