#!/bin/bash
# Obsidian同期スクリプト
# GitHubリポジトリのobsidianフォルダをローカルのObsidian Vaultに同期

REPO_DIR="$HOME/ai-tweet-dashboard"
OBSIDIAN_DIR="$HOME/Documents/AI情報ダッシュボード"

# リポジトリを最新に更新
cd "$REPO_DIR" && git pull --quiet

# ObsidianフォルダにMarkdownをコピー
mkdir -p "$OBSIDIAN_DIR"
cp -u "$REPO_DIR"/obsidian/*.md "$OBSIDIAN_DIR/" 2>/dev/null

echo "Obsidian同期完了: $(date)"
