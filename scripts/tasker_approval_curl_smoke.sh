#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${ATENA_TASKER_TEST_URL:-http://127.0.0.1:8787}"
SECRET="${ATENA_TASKER_HMAC_SECRET:?defina ATENA_TASKER_HMAC_SECRET apenas na sessão de teste}"
DEVICE_ID="${ATENA_TASKER_DEVICE_ID:-android-test}"
CHAT_ID="${ATENA_TEST_CHAT_ID:-chat-test}"
TASK_ID="task-curl-$(date +%s)"

sign_and_post() {
  local path="$1" body="$2" nonce
  local timestamp signature
  timestamp="$(date +%s)"
  nonce="$(cat /proc/sys/kernel/random/uuid | tr -d '-')"
  signature="$(printf '%s' "${timestamp}.${nonce}.${body}" | openssl dgst -sha256 -hmac "$SECRET" -hex | awk '{print $2}')"
  curl --fail-with-body --silent --show-error \
    -X POST "${BASE_URL}${path}" \
    -H 'Content-Type: application/json' \
    -H "X-Atena-Timestamp: ${timestamp}" \
    -H "X-Atena-Nonce: ${nonce}" \
    -H "X-Atena-Signature: ${signature}" \
    --data-binary "$body"
  printf '\n'
}

printf '%s\n' '1) Aprovar a ação sensível'
sign_and_post /v1/tasker/approve "{\"approval_id\":\"${TASK_ID}\",\"requester_chat_id\":\"${CHAT_ID}\",\"device_id\":\"${DEVICE_ID}\",\"action\":\"android_send_message\",\"target\":\"android\",\"parameters\":{\"recipient\":\"contato-de-teste\",\"text\":\"mensagem de smoke test\"},\"expires_in\":120}"

printf '%s\n' '2) Despachar com approval_id'
sign_and_post /v1/tasker/dispatch "{\"command_id\":\"${TASK_ID}\",\"approval_id\":\"${TASK_ID}\",\"device_id\":\"${DEVICE_ID}\",\"action\":\"android_send_message\",\"target\":\"android\",\"parameters\":{\"recipient\":\"contato-de-teste\",\"text\":\"mensagem de smoke test\"}}"

printf '%s\n' '3) Tasker retirar a tarefa'
next_body="$(printf '{\"device_id\":\"%s\"}' "$DEVICE_ID")"
sign_and_post /v1/tasker/next "$next_body"

printf '%s\n' '4) Tasker confirmar resultado sem enviar mensagem real'
sign_and_post /v1/tasker/result "{\"command_id\":\"${TASK_ID}\",\"device_id\":\"${DEVICE_ID}\",\"ok\":true,\"result\":{\"simulated\":true}}"

printf '%s\n' 'Smoke test concluído. O destinatário era apenas um identificador de teste.'
