#!/usr/bin/env bash
# 查询 rabbitj.top（anyGPT 商业站）账户余额
# 认证方式：API Key（sk-...），来源优先级：
#   1) 环境变量 RABBIT_API_KEY
#   2) ~/.dsh/.credentials.yaml 中的 refs.RABBIT_API_KEY
# 原理：GET /v1/usage?limit=1&status=billed 返回最近一条已计费请求，
#       其中的 balance_cny 即该笔扣费后的实时余额（单位：元）。
set -euo pipefail

BASE="${RABBIT_BASE:-https://www.rabbitj.top}"

key="${RABBIT_API_KEY:-}"
if [ -z "$key" ] && [ -f "$HOME/.dsh/.credentials.yaml" ]; then
  key=$(python3 - "$HOME/.dsh/.credentials.yaml" <<'PY'
import re, sys
text = open(sys.argv[1]).read()
m = re.search(r'^\s*RABBIT_API_KEY:\s*(\S+)\s*$', text, re.M)
print(m.group(1) if m else '', end='')
PY
)
fi
if [ -z "$key" ]; then
  echo "错误：未找到 API Key（RABBIT_API_KEY 或 ~/.dsh/.credentials.yaml）" >&2
  exit 2
fi

json=$(curl -sS --max-time 30 "$BASE/v1/usage?limit=1&status=billed" \
  -H "Authorization: Bearer $key")

python3 - "$json" <<'PY'
import json, sys
d = json.loads(sys.argv[1])
items = d.get("items") or []
if not items:
    print("未查询到已计费记录，无法推算余额。"); sys.exit(1)
i = items[0]
bal = i.get("balance_cny")
print(f"余额：¥{bal:.4f}" if bal is not None else "余额字段缺失")
print(f"（该余额更新于 {i.get('created_at')}，最近一笔：{i.get('model')}，扣费 ¥{i.get('charged_cny')}）")
PY
