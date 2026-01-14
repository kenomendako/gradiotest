---
description: browser_subagent用にCDPモードでChromeを起動する（WSL2環境）
---

# Browser Subagent用 Chrome起動

WSL2環境で browser_subagent を使用するために、CDPモードでブラウザを起動します。

## 前提条件
* Chromiumベースブラウザがインストール済みであること（`google-chrome-stable` または `chromium-browser`）  
  未インストールの場合は、 `google-chrome-stable` のインストールを推奨

## 手順

// turbo
1. 既存のブラウザプロセスを終了し、CDPモードで再起動:
```bash
CHROME_BIN=$(which google-chrome-stable 2>/dev/null || which chromium-browser 2>/dev/null) && \
pkill -9 -f chrome 2>/dev/null; pkill -9 -f chromium 2>/dev/null; sleep 1; \
$CHROME_BIN --remote-debugging-port=9222 --remote-debugging-address=127.0.0.1 --no-first-run --no-default-browser-check --user-data-dir="$HOME/.gemini/antigravity-browser-profile" > /dev/null 2>&1 &
```

// turbo
2. 起動確認 (ポート 9222 が応答するか):
```bash
sleep 3 && curl -s [http://127.0.0.1:9222/json/version](http://127.0.0.1:9222/json/version) | head -n 3
```

## 注意
* 開発環境（WSL）の再起動後に毎回実行が必要です。
* ブラウザにアクセスするには、`google-chrome-stable` または `chromium-browser` を使用して下さい。