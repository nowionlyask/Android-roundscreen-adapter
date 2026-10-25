#!/usr/bin/env bash
# Watch Control 一键启动（Linux / macOS）
#
# 用法：
#   ./run.sh                    启动中转服务
#   ./run.sh picker             启动点选工具
#   ./run.sh setup              生成配对密钥

set -e
cd "$(dirname "$0")"

# ---------- 公用 ----------
export WC_HOME="${WC_HOME:-$HOME/.config/watch-control}"
mkdir -p "$WC_HOME"

gen_key() {
  if [ -f "$WC_HOME/pairing.key" ]; then
    echo "[+] 配对密钥已存在: $WC_HOME/pairing.key"
  else
    python3 -c "import secrets; print(secrets.token_hex(32))" > "$WC_HOME/pairing.key"
    chmod 600 "$WC_HOME/pairing.key"
    echo "[+] 已生成配对密钥: $WC_HOME/pairing.key"
  fi
  echo "    内容: $(cat "$WC_HOME/pairing.key")"
}

case "${1:-server}" in
  setup)
    gen_key
    echo
    echo "接下来手动配置手表地址："
    echo "  export WATCH_ADDR=\"192.168.1.50:5555\""
    echo "或者什么都不做 —— 手表访问服务器后会自动学习地址。"
    ;;

  server)
    export PAIRING_KEY="${PAIRING_KEY:-$(cat "$WC_HOME/pairing.key" 2>/dev/null || true)}"
    echo "[*] 启动中转服务 (WC_HOME=$WC_HOME)"
    python3 server/app.py --host "${HOST:-127.0.0.1}" --port "${PORT:-8787}" "${@:2}"
    ;;

  picker)
    export BILIAUTO_KEY="${BILIAUTO_KEY:-$(cat "$WC_HOME/pairing.key" 2>/dev/null || true)}"
    export BILIAUTO_SERVER="${BILIAUTO_SERVER:-http://127.0.0.1:8787}"
    echo "[*] 启动点选工具"
    python3 tap-tool/serve.py
    ;;

  *)
    echo "用法: $0 [server|picker|setup]"
    exit 1
    ;;
esac
