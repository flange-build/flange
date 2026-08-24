#!/bin/bash
set -xeuo pipefail

readonly SOC_ID="498"
readonly SOC_ID_PATH="/sys/devices/soc0/soc_id"
readonly RUNTIME_DIR="/run/fastrpc"

if [[ ! -e "${SOC_ID_PATH}" ]]; then
    echo "FastRPC soc_id 挂载点不存在：${SOC_ID_PATH}" >&2
    exit 1
fi

mkdir -p "${RUNTIME_DIR}"
printf '%s\n' "${SOC_ID}" > "${RUNTIME_DIR}/soc_id"
if ! mountpoint -q "${SOC_ID_PATH}"; then
    mount --bind "${RUNTIME_DIR}/soc_id" "${SOC_ID_PATH}"
fi
