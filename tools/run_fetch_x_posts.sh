#!/bin/bash
# fetch_x_posts.py を実行してキャッシュを git push する LaunchAgent ラッパー
# 火・土 6:50 JST に起動（com.crossedge.fetch-x-posts.plist）

export PATH="/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
REPO="/Users/yonetomo/ai-secretary"

cd "$REPO" || exit 1

echo "=== run_fetch_x_posts.sh 開始 $(date '+%Y-%m-%d %H:%M JST') ==="

/opt/homebrew/bin/python3 tools/fetch_x_posts.py

git add data/x_posts_cache.json
if ! git diff --staged --quiet; then
    git commit -m "[自動] x_posts_cache.json 更新 ($(date '+%Y-%m-%d %H:%M JST'))"
    git push origin main && echo "  push 完了" || echo "  push 失敗（次回に持ち越し）"
else
    echo "  変更なし。push スキップ。"
fi

echo "=== 完了 ==="
