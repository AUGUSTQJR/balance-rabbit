#!/usr/bin/env bash
# 余额兔 · 一键发布
# ---------------------------------------------------------------------------
# 做三件事（可分段执行，失败会明确告诉你是哪一步）：
#   1. 把 dist/ 里的 zip 传到 GitHub Release（AUGUSTQJR/balance-rabbit）
#   2. 更新 README.md 的「下载」表格（版本号 + 新直链）
#   3. 调 rabbitj 后台接口，把网站软件商城里的「余额兔」改成新版本 + 新直链
#
# 用法：
#   ./release.sh                     # 按 dist/ 里现有 zip 的版本号发布全部
#   ./release.sh macos               # 只发 macOS
#   ./release.sh macos windows       # 发多个平台
#   ./release.sh --dry-run macos     # 只打印将要做什么，不实际发送
#   ./release.sh --site-only         # 只更新网站后台（GitHub 已经传过了）
#   ./release.sh --github-only       # 只传 GitHub + 改 README
#
# 需要的两个令牌（只存本机，不进仓库）：
#   GH_TOKEN            GitHub Personal Access Token，repo 权限
#   RABBITJ_ADMIN_TOKEN rabbitj.top 后台登录后的 Bearer token
# 读取顺序：环境变量 → ~/.dsh/.credentials.yaml 的 refs 段
set -euo pipefail
cd "$(dirname "$0")"

REPO="AUGUSTQJR/balance-rabbit"
API_BASE="https://www.rabbitj.top/apiAI"
SOFTWARE_ID=4          # 软件商城里「余额兔」的记录 id
CREDS="$HOME/.dsh/.credentials.yaml"
ENVFILE="$(cd "$(dirname "$0")" && pwd)/.env.release"
DIST_KEEP=3            # dist/ 里最多保留几个旧版本，多出来的提示手动清

DRY_RUN=0
DO_GITHUB=1
DO_SITE=1
PLATFORMS=()

for arg in "$@"; do
  case "$arg" in
    --dry-run)      DRY_RUN=1 ;;
    --github-only)  DO_SITE=0 ;;
    --site-only)    DO_GITHUB=0 ;;
    macos|windows|linux) PLATFORMS+=("$arg") ;;
    -h|--help)      sed -n '2,25p' "$0"; exit 0 ;;
    *) echo "未知参数：${arg}（可用：macos windows linux --dry-run --site-only --github-only）"; exit 2 ;;
  esac
done

# ---------- 小工具 ----------
say()  { printf '%s\n' "$*"; }
step() { printf '\n▶ %s\n' "$*"; }
die()  { printf '\n✗ %s\n' "$*" >&2; exit 1; }
run()  { if [ "$DRY_RUN" = 1 ]; then printf '  [dry-run] %s\n' "$*"; else eval "$@"; fi; }

cred() {  # cred <KEY>：环境变量优先，其次 refs 段
  local key="$1"
  if [ -n "${!key:-}" ]; then printf '%s' "${!key}"; return; fi
  # 本机 .env.release（已 gitignore），其次 ~/.dsh/.credentials.yaml
  if [ -f "$ENVFILE" ]; then
    local v; v=$(awk -F= -v k="$key" '$1=="export "k{print $2}' "$ENVFILE" | tr -d '"')
    [ -n "$v" ] && { printf '%s' "$v"; return; }
  fi
  [ -f "$CREDS" ] || return 0
  awk -v k="$key" '$1==k":"{print $2; exit}' "$CREDS"
}

# ---------- 平台元数据 ----------
# macOS 自带 bash 3.2 没有关联数组，用函数查表代替
zippat() { case "$1" in
  macos)   echo 'macos/dist/余额兔-v*-macOS.zip' ;;
  windows) echo 'windows/dist/余额兔-v*-Windows-免安装.zip' ;;
  linux)   echo 'linux/dist/余额兔-v*-Linux.zip' ;;
esac; }
assetname() { case "$1" in   # GitHub 附件名必须是英文
  macos)   echo "BalanceRabbit-v$2-macOS.zip" ;;
  windows) echo "BalanceRabbit-v$2-Windows.zip" ;;
  linux)   echo "BalanceRabbit-v$2-Linux.zip" ;;
esac; }
releasetag() { case "$1" in
  macos)   echo "v$2-macOS" ;;
  windows) echo "v$2-windows" ;;
  linux)   echo "v$2-linux" ;;
esac; }

# 把 dist 里最新的 zip 找出来，结果写进全局 FOUND_ZIP_1 / FOUND_VER_1
FOUND_ZIP_1=""; FOUND_VER_1=""
find_zip() {
  local plat="$1" f ver
  FOUND_ZIP_1=""; FOUND_VER_1=""
  f=$(ls -1t $(zippat "$plat") 2>/dev/null | head -1 || true)
  if [ -z "$f" ]; then
    say "  ⚠ ${plat}：dist/ 里没有 zip，跳过（先跑对应的 build.sh / package.sh）"
    return 1
  fi
  ver=$(basename "$f" | sed -E 's/.*-v([0-9]+\.[0-9]+\.[0-9]+)-.*/\1/')
  [ -n "$ver" ] || { say "  ⚠ ${plat}：解析不出版本号：$f"; return 1; }
  say "  ${plat}：${f}（v${ver}）"
  FOUND_ZIP_1="$f"; FOUND_VER_1="$ver"
  return 0
}

# ---------- 1. GitHub：覆盖 dist 文件（不建 Release）----------
# 方案 B：文件名保留版本号；每个 dist 目录只留最新一个 zip；
# 旧的删掉、新的提交推送。仓库地址永久有效，后台 links 不用改。
publish_github() {
  local plat="$1" zip="$2" ver="$3"
  local dir; dir=$(dirname "$zip")

  step "GitHub：$dir 覆盖为 v$ver"
  # 删掉同目录里的旧版本 zip（保留当前这个）
  local old
  for old in $(ls -1 "$dir"/*.zip 2>/dev/null); do
    [ "$old" = "$zip" ] && continue
    say "  删除旧包 $(basename "$old")"
    run "git rm -q --cached '$old' 2>/dev/null || true; rm -f '$old'"
  done

  run "git add -A '$dir'"
  if [ "$DRY_RUN" = 1 ]; then
    say "  [dry-run] git commit -m 'release: $plat v$ver'  &&  git push"
    return
  fi
  if git diff --cached --quiet; then
    say "  目录内容无变化，跳过提交"
  else
    git commit -q -m "release: $plat v${ver}（覆盖 dist 分发包）" || die "提交失败"
    say "  ✓ 已提交"
  fi

  # 推送（用部署密钥，优先于 https）
  GIT_SSH_COMMAND="ssh -i \"$PWD/.deploykeys/augustqjr_ed25519\" -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new" \
    git push origin HEAD 2>&1 | tail -2
  say "  ✓ 已推送：https://github.com/$REPO/tree/main/$dir"
}

# 仓库里指向 dist 的固定直链（后台 links 一直用这个，不变）
dist_url() {  # dist_url <plat>
  case "$1" in
    macos)   echo "https://github.com/$REPO/tree/main/macos/dist" ;;
    windows) echo "https://github.com/$REPO/tree/main/windows/dist" ;;
    linux)   echo "https://github.com/$REPO/tree/main/linux/dist" ;;
  esac
}

# ---------- 2. README 下载表格 ----------
# 覆盖 dist 模式下，README 下载链接指向 dist 目录页（不是 releases/download）
update_readme() {
  local plat="$1" ver="$2"
  local url; url=$(dist_url "$plat")
  local zip; zip=$(ls -1t $(zippat "$plat") 2>/dev/null | head -1)
  local size; size=$(du -h "$zip" 2>/dev/null | cut -f1 | tr -d ' ')

  [ -f README.md ] || { say "  ⚠ 没找到 README.md，跳过"; return; }
  if [ "$DRY_RUN" = 1 ]; then
    say "  [dry-run] README 里 ${plat} 那行 → v$ver / $url"
    return
  fi
  cp README.md "README.md.bak.$(date +%Y%m%d%H%M%S)"
  python3 - "$plat" "$ver" "$url" "$size" <<'PYEOF'
import sys, glob, os
plat, ver, url, size = sys.argv[1:5]
key = {'macos':'-macOS','windows':'-Windows','linux':'-Linux'}[plat]
pat = {'macos':'macos/dist/*-macOS.zip','windows':'windows/dist/*-Windows*.zip',
       'linux':'linux/dist/*-Linux.zip'}[plat]
files = glob.glob(pat)
fname = os.path.basename(max(files, key=os.path.getmtime)) if files else ''
s = open('README.md', encoding='utf-8').read()
out, hit = [], False
for line in s.splitlines(True):
    if '|' in line and key in line and ('dist' in line or 'releases/download' in line):
        cells = line.rstrip('\n').split('|')
        if fname: cells[2] = f' [`{fname}`]({url}) '
        cells[3] = f' v{ver} '
        cells[4] = f' {size} '
        line = '|'.join(cells) + '\n'
        hit = True
    out.append(line)
if hit:
    open('README.md','w',encoding='utf-8').write(''.join(out))
    print('  ✓ README 下载表格已更新 → ' + url)
else:
    print(f'  ⚠ README 里没找到 {plat} 对应行，请手动改')
PYEOF
}

# ---------- 3. 网站后台 ----------
# 关键：update 接口是"整条记录覆盖"，必须先把原记录读出来原样回填，
# 只改 version / links / summary。否则 cover_url 等字段会被清空。
site_api() {  # site_api <path> <json-body>
  local path="$1" body="$2" token; token=$(cred RABBITJ_ADMIN_TOKEN)
  curl -sS --max-time 30 -X POST "https://www.rabbitj.top/apiAI/$path" \
    -H "token: $token" -H "Authorization: Bearer $token" \
    -H 'Content-Type: application/json' -d "$body"
}

update_site() {
  local token; token=$(cred RABBITJ_ADMIN_TOKEN)
  if [ -z "$token" ] && [ "$DRY_RUN" = 1 ]; then
    say "  [dry-run] 未设置 RABBITJ_ADMIN_TOKEN，只打印将发送的内容"
  fi
  [ -n "$token" ] || [ "$DRY_RUN" = 1 ] || die "缺 RABBITJ_ADMIN_TOKEN（放 .env.release 或 ~/.dsh/.credentials.yaml）"

  # 收集各平台最新版本 + 直链，取最高版本作网站版本号
  local -a links=()
  local maxver="" plat z v tag asset url label
  for plat in "${FOUND_PLAT[@]}"; do
    z=""; v=""
    for i in "${!FOUND_PLAT[@]}"; do
      [ "${FOUND_PLAT[$i]}" = "$plat" ] && { z="${FOUND_ZIP[$i]}"; v="${FOUND_VER[$i]}"; }
    done
    [ -n "$z" ] || continue
    tag=$(releasetag "$plat" "$v"); asset=$(assetname "$plat" "$v")
    url=$(dist_url "$plat")
    case "$plat" in macos) label="macOS";; windows) label="Windows";; linux) label="Linux";; esac
    links+=("{\"label\":\"$label\",\"url\":\"$url\",\"code\":\"\"}")
    if [ -z "$maxver" ] || [ "$(printf '%s\n%s\n' "$maxver" "$v" | sort -V | tail -1)" = "$v" ]; then
      maxver="$v"
    fi
  done
  [ ${#links[@]} -gt 0 ] || die "没有任何 dist zip，无法确定网站要写的版本"

  step "网站后台：读取「余额兔」(id=$SOFTWARE_ID) 原记录"
  local cur
  if [ "$DRY_RUN" = 1 ] && [ -z "$token" ]; then
    say "  [dry-run] 无 token，跳过读取"
    return
  fi
  cur=$(site_api "user/admin/software" '{"page":1,"page_num":50,"category_id":null,"keyword":""}')
  local body_file="/tmp/rabbitj_body_$$.json"
  printf '%s' "$cur" > "/tmp/rabbitj_list_$$.json"

  python3 - "$SOFTWARE_ID" "$maxver" "$(IFS=,; printf '%s' "${links[*]}")" "/tmp/rabbitj_list_$$.json" "$DRY_RUN" <<'PYEOF'
import json, sys
sid, ver, links_raw, listfile, dry = int(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5]
data = json.load(open(listfile, encoding="utf-8"))
rows = data.get("list") or data.get("data") or []
rec = next((r for r in rows if r.get("id") == sid), None)
if not rec:
    print(f"  ✗ 列表里找不到 id={sid}"); sys.exit(3)
print(f"  读到：{rec.get('name')} | 版本 {rec.get('version')} | 封面 {len(rec.get('cover_url') or '')} 字符")
links = json.loads("[" + links_raw + "]")
# 整条记录回填，只替换这三项
body = dict(rec)
body["version"] = ver
body["links"] = links
# 简介里去掉已下线的 iOS 说法
sm = body.get("summary") or ""
sm2 = sm.replace("，另有 iOS 脚本组件版", "").replace("，另有iOS脚本组件版", "")
if sm2 != sm:
    body["summary"] = sm2
    print("  简介：已移除 iOS 表述")
for junk in ("category_name",):
    body.pop(junk, None)
payload = json.dumps(body, ensure_ascii=False)
open("/tmp/rabbitj_body_payload.json", "w", encoding="utf-8").write(payload)
print(f"  待提交：version={ver} links={len(links)} 封面保留={bool(body.get('cover_url'))}")
if dry == "1":
    print("  [dry-run] 不实际提交")
    sys.exit(0)
PYEOF
  local rc=$?
  [ $rc -eq 0 ] || die "读取/组装原记录失败（rc=$rc）"
  [ "$DRY_RUN" = 1 ] && return 0

  local resp
  resp=$(curl -sS --max-time 30 -X POST "https://www.rabbitj.top/apiAI/user/admin/software/update" \
    -H "token: ${RABBITJ_ADMIN_TOKEN:-$(cred RABBITJ_ADMIN_TOKEN)}" \
    -H "Authorization: Bearer $(cred RABBITJ_ADMIN_TOKEN)" \
    -H 'Content-Type: application/json' \
    --data-binary "@/tmp/rabbitj_body_payload.json" || true)
  say "  返回：$resp"
  case "$resp" in
    *'"code":"0"'*|*'"code":0'*) say "  ✓ 网站已更新为 v$maxver" ;;
    *) say "  ⚠ 网站更新可能失败（看上面返回）。若提示 3004，说明 token 过期。" ;;
  esac
  rm -f "/tmp/rabbitj_list_$$.json" /tmp/rabbitj_body_payload.json
}

# ---------- 主流程 ----------
say "余额兔发布  $(date '+%Y-%m-%d %H:%M:%S')"
[ "$DRY_RUN" = 1 ] && say "（dry-run：只打印，不实际发送）"

[ ${#PLATFORMS[@]} -gt 0 ] || PLATFORMS=(macos windows linux)

step "清点 dist/ 里的分发包"
declare -a FOUND_PLAT=() FOUND_ZIP=() FOUND_VER=()
for p in "${PLATFORMS[@]}"; do
  if find_zip "$p"; then
    FOUND_PLAT+=("$p"); FOUND_ZIP+=("$FOUND_ZIP_1"); FOUND_VER+=("$FOUND_VER_1")
  fi
done
[ ${#FOUND_PLAT[@]} -gt 0 ] || die "没有任何可发布的 zip"

if [ "$DO_GITHUB" = 1 ]; then
  for i in "${!FOUND_PLAT[@]}"; do
    publish_github "${FOUND_PLAT[$i]}" "${FOUND_ZIP[$i]}" "${FOUND_VER[$i]}"
    update_readme  "${FOUND_PLAT[$i]}" "${FOUND_VER[$i]}"
  done
fi

if [ "$DO_SITE" = 1 ]; then
  update_site
fi

step "完成"
for i in "${!FOUND_PLAT[@]}"; do
  p="${FOUND_PLAT[$i]}"; v="${FOUND_VER[$i]}"
  say "  ${p} v${v}: $(dist_url "$p")"
done
[ "$DRY_RUN" = 0 ] && say "\n✓ 完成。仓库：https://github.com/$REPO"
