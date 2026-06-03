"""
AI Tweet Dashboard - メイン収集・分類スクリプト
- 2アカウントのいいね欄からAI関連ツイートを収集
- トレンドのAIツイートも検索
- Gemini APIで分類・スコアリング
- HTML (GitHub Pages) + Markdown (Obsidian) + Discord通知を出力
"""

import os
import json
import requests
from datetime import datetime, timedelta, timezone
from pathlib import Path
import google.generativeai as genai

# ─── 設定 ───────────────────────────────────────────
X_BEARER_TOKENS = [
    os.environ["X_BEARER_TOKEN_1"],
    os.environ["X_BEARER_TOKEN_2"],
]
X_USERNAMES = ["tigauuuuu", "j6Xb5VYjCF59749"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
DISCORD_WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"]

# AIキーワード（フィルタリング用）
AI_KEYWORDS = [
    "ai", "chatgpt", "claude", "gemini", "gpt", "llm", "生成ai", "機械学習",
    "深層学習", "openai", "anthropic", "midjourney", "stable diffusion",
    "プロンプト", "prompt", "copilot", "hugging face", "transformer",
    "fine-tuning", "rag", "agent", "エージェント", "multimodal", "diffusion",
    "llama", "mistral", "perplexity", "cursor", "github copilot", "sora",
    "dall-e", "whisper", "embedding", "vector", "langchain", "autogpt",
    "人工知能", "自然言語処理", "nlp", "computer vision", "画像生成",
]

JST = timezone(timedelta(hours=9))

# ─── X API ──────────────────────────────────────────
def get_headers(token):
    return {"Authorization": f"Bearer {token}"}

def get_user_id(username, token):
    url = f"https://api.twitter.com/2/users/by/username/{username}"
    r = requests.get(url, headers=get_headers(token))
    r.raise_for_status()
    return r.json()["data"]["id"]

def get_liked_tweets(user_id, token):
    """いいねしたツイートを取得（最大100件）"""
    url = f"https://api.twitter.com/2/users/{user_id}/liked_tweets"
    params = {
        "max_results": 100,
        "tweet.fields": "created_at,public_metrics,author_id,text",
        "expansions": "author_id",
        "user.fields": "username,name",
    }
    r = requests.get(url, headers=get_headers(token), params=params)
    if r.status_code == 429:
        print(f"Rate limit hit for user {user_id}")
        return []
    r.raise_for_status()
    data = r.json()
    tweets = data.get("data", [])
    users = {u["id"]: u for u in data.get("includes", {}).get("users", [])}
    for t in tweets:
        user = users.get(t.get("author_id"), {})
        t["author_username"] = user.get("username", "unknown")
        t["author_name"] = user.get("name", "unknown")
    return tweets

def search_ai_tweets():
    """トレンドのAIツイートを検索"""
    token = X_BEARER_TOKENS[0]
    query = "(AI OR ChatGPT OR Claude OR LLM OR 生成AI OR OpenAI) lang:ja -is:retweet"
    url = "https://api.twitter.com/2/tweets/search/recent"
    params = {
        "query": query,
        "max_results": 50,
        "tweet.fields": "created_at,public_metrics,author_id,text",
        "expansions": "author_id",
        "user.fields": "username,name",
    }
    r = requests.get(url, headers=get_headers(token), params=params)
    if r.status_code != 200:
        print(f"Search failed: {r.status_code}")
        return []
    data = r.json()
    tweets = data.get("data", [])
    users = {u["id"]: u for u in data.get("includes", {}).get("users", [])}
    for t in tweets:
        user = users.get(t.get("author_id"), {})
        t["author_username"] = user.get("username", "unknown")
        t["author_name"] = user.get("name", "unknown")
        t["source"] = "search"
    return tweets

# ─── フィルタリング ──────────────────────────────────
def is_ai_related(text):
    text_lower = text.lower()
    return any(kw in text_lower for kw in AI_KEYWORDS)

def is_yesterday(created_at_str):
    """前日(JST)または過去7日以内のツイートかどうか（初回は7日分取得）"""
    try:
        dt = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
        dt_jst = dt.astimezone(JST)
        week_ago = datetime.now(JST).date() - timedelta(days=7)
        return dt_jst.date() >= week_ago
    except Exception:
        return True  # パース失敗時は含める

def deduplicate(tweets):
    seen = set()
    result = []
    for t in tweets:
        if t["id"] not in seen:
            seen.add(t["id"])
            result.append(t)
    return result

# ─── Gemini 分類 ─────────────────────────────────────
def classify_tweets(tweets):
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel("gemini-1.5-flash")

    tweet_list = "\n".join([
        f"{i+1}. {t['text'][:200]}" for i, t in enumerate(tweets)
    ])

    prompt = f"""以下のAI関連ツイートを分析して、JSON形式で返してください。

ツイート一覧:
{tweet_list}

各ツイートに対して以下を判定してください：
- category: "新機能/アップデート" | "使い方/Tips" | "研究/論文" | "議論/考察" | "ツール紹介" | "その他"
- importance: 1〜5の整数（5が最重要）
- reason: なぜ重要か1行で（日本語）
- emoji: カテゴリに合う絵文字1つ

返答形式（JSON配列のみ、他のテキストなし）:
[
  {{"index": 1, "category": "...", "importance": 4, "reason": "...", "emoji": "..."}},
  ...
]"""

    try:
        response = model.generate_content(prompt)
        text = response.text.strip()
        # JSONブロックを抽出
        if "```" in text:
            text = text.split("```")[1].replace("json", "").strip()
        classifications = json.loads(text)
        result = {}
        for c in classifications:
            idx = c["index"] - 1
            if 0 <= idx < len(tweets):
                result[tweets[idx]["id"]] = c
        return result
    except Exception as e:
        print(f"Gemini classification error: {e}")
        # フォールバック: ルールベース
        return {t["id"]: rule_based_classify(t) for t in tweets}

def rule_based_classify(tweet):
    text = tweet["text"].lower()
    if any(kw in text for kw in ["リリース", "update", "新機能", "v3", "launch", "発表"]):
        return {"category": "新機能/アップデート", "importance": 4, "reason": "新機能・アップデート情報", "emoji": "📦"}
    elif any(kw in text for kw in ["使い方", "プロンプト", "コツ", "tips", "方法", "how to"]):
        return {"category": "使い方/Tips", "importance": 3, "reason": "実践的な使い方", "emoji": "🛠️"}
    elif any(kw in text for kw in ["論文", "arxiv", "research", "paper"]):
        return {"category": "研究/論文", "importance": 4, "reason": "研究・論文情報", "emoji": "🔬"}
    else:
        return {"category": "その他", "importance": 2, "reason": "AI関連情報", "emoji": "💬"}

# ─── HTML生成 ─────────────────────────────────────────
def generate_html(tweets, classifications, date_str):
    cats = ["新機能/アップデート", "使い方/Tips", "研究/論文", "議論/考察", "ツール紹介", "その他"]
    grouped = {c: [] for c in cats}
    grouped["その他"] = []

    for t in sorted(tweets, key=lambda x: classifications.get(x["id"], {}).get("importance", 0), reverse=True):
        clf = classifications.get(t["id"], {})
        cat = clf.get("category", "その他")
        if cat not in grouped:
            cat = "その他"
        grouped[cat].append((t, clf))

    cards_html = ""
    for cat in cats:
        items = grouped.get(cat, [])
        if not items:
            continue
        cards_html += f'<div class="category"><h2>{items[0][1].get("emoji","📌")} {cat} <span class="count">{len(items)}</span></h2>'
        for t, clf in items:
            importance = clf.get("importance", 1)
            stars = "⭐" * importance
            reason = clf.get("reason", "")
            author = t.get("author_name", t.get("author_username", ""))
            username = t.get("author_username", "")
            text = t["text"].replace("<", "&lt;").replace(">", "&gt;")
            metrics = t.get("public_metrics", {})
            likes = metrics.get("like_count", 0)
            rts = metrics.get("retweet_count", 0)
            tweet_url = f"https://twitter.com/{username}/status/{t['id']}"
            source_badge = '<span class="badge search">🔍 検索</span>' if t.get("source") == "search" else '<span class="badge liked">❤️ いいね</span>'
            cards_html += f"""
<div class="card importance-{importance}">
  <div class="card-header">
    <span class="stars">{stars}</span>
    {source_badge}
    <span class="metrics">❤️ {likes:,} 🔁 {rts:,}</span>
  </div>
  <div class="author"><a href="https://twitter.com/{username}" target="_blank">@{username}</a> · {author}</div>
  <div class="text">{text}</div>
  <div class="reason">💡 {reason}</div>
  <a href="{tweet_url}" target="_blank" class="tweet-link">ツイートを見る →</a>
</div>"""
        cards_html += "</div>"

    top5 = sorted(tweets, key=lambda x: classifications.get(x["id"], {}).get("importance", 0), reverse=True)[:5]
    top5_html = "".join([
        f'<li>{classifications.get(t["id"],{}).get("emoji","📌")} {t["text"][:80]}...</li>'
        for t in top5
    ])

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI情報ダッシュボード - {date_str}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0f0f1a; color: #e0e0e0; padding: 16px; }}
  h1 {{ text-align: center; padding: 20px 0 8px; font-size: 1.4em; color: #a78bfa; }}
  .date {{ text-align: center; color: #888; font-size: 0.85em; margin-bottom: 20px; }}
  .summary {{ background: #1a1a2e; border-radius: 12px; padding: 16px; margin-bottom: 20px; border-left: 4px solid #a78bfa; }}
  .summary h2 {{ color: #a78bfa; margin-bottom: 8px; font-size: 1em; }}
  .summary li {{ margin: 6px 0; font-size: 0.88em; line-height: 1.5; }}
  .category {{ margin-bottom: 24px; }}
  .category h2 {{ font-size: 1em; color: #c4b5fd; margin-bottom: 10px; padding-bottom: 6px; border-bottom: 1px solid #333; }}
  .count {{ background: #6d28d9; color: white; padding: 2px 8px; border-radius: 10px; font-size: 0.75em; margin-left: 6px; }}
  .card {{ background: #1a1a2e; border-radius: 10px; padding: 14px; margin-bottom: 12px; border-left: 3px solid #444; }}
  .card.importance-5 {{ border-left-color: #f59e0b; }}
  .card.importance-4 {{ border-left-color: #a78bfa; }}
  .card.importance-3 {{ border-left-color: #34d399; }}
  .card-header {{ display: flex; align-items: center; gap: 8px; margin-bottom: 6px; flex-wrap: wrap; }}
  .stars {{ font-size: 0.75em; }}
  .badge {{ font-size: 0.7em; padding: 2px 6px; border-radius: 8px; }}
  .badge.liked {{ background: #7f1d1d; color: #fca5a5; }}
  .badge.search {{ background: #1e3a5f; color: #93c5fd; }}
  .metrics {{ font-size: 0.75em; color: #888; margin-left: auto; }}
  .author {{ font-size: 0.8em; color: #888; margin-bottom: 6px; }}
  .author a {{ color: #a78bfa; text-decoration: none; }}
  .text {{ font-size: 0.9em; line-height: 1.6; margin-bottom: 8px; white-space: pre-wrap; word-break: break-word; }}
  .reason {{ font-size: 0.8em; color: #a3e635; margin-bottom: 8px; }}
  .tweet-link {{ font-size: 0.8em; color: #60a5fa; text-decoration: none; }}
  @media (min-width: 768px) {{
    body {{ max-width: 800px; margin: 0 auto; padding: 24px; }}
    h1 {{ font-size: 1.8em; }}
  }}
</style>
</head>
<body>
<h1>🤖 AI情報ダッシュボード</h1>
<div class="date">📅 {date_str} | 収集件数: {len(tweets)}件</div>
<div class="summary">
  <h2>⭐ 本日のTOP5</h2>
  <ol>{top5_html}</ol>
</div>
{cards_html}
</body>
</html>"""

# ─── Markdown生成 (Obsidian用) ────────────────────────
def generate_markdown(tweets, classifications, date_str):
    lines = [f"# AI情報ダッシュボード - {date_str}", "", f"収集件数: {len(tweets)}件", ""]

    cats = ["新機能/アップデート", "使い方/Tips", "研究/論文", "議論/考察", "ツール紹介", "その他"]
    grouped = {c: [] for c in cats}
    for t in sorted(tweets, key=lambda x: classifications.get(x["id"], {}).get("importance", 0), reverse=True):
        clf = classifications.get(t["id"], {})
        cat = clf.get("category", "その他")
        if cat not in grouped:
            cat = "その他"
        grouped[cat].append((t, clf))

    for cat in cats:
        items = grouped.get(cat, [])
        if not items:
            continue
        emoji = items[0][1].get("emoji", "📌")
        lines.append(f"## {emoji} {cat}")
        for t, clf in items:
            importance = clf.get("importance", 1)
            stars = "⭐" * importance
            username = t.get("author_username", "")
            reason = clf.get("reason", "")
            tweet_url = f"https://twitter.com/{username}/status/{t['id']}"
            lines += [
                f"### {stars} @{username}",
                f"> {t['text']}",
                f"",
                f"💡 {reason}",
                f"🔗 [{tweet_url}]({tweet_url})",
                "",
            ]
    return "\n".join(lines)

# ─── Discord通知 ──────────────────────────────────────
def send_discord(tweets, classifications, date_str):
    top5 = sorted(tweets, key=lambda x: classifications.get(x["id"], {}).get("importance", 0), reverse=True)[:5]
    lines = [f"**🤖 AI情報ダッシュボード - {date_str}**", f"本日 {len(tweets)} 件のAI情報を収集しました！", "", "**⭐ TOP5**"]
    for i, t in enumerate(top5, 1):
        clf = classifications.get(t["id"], {})
        emoji = clf.get("emoji", "📌")
        lines.append(f"{i}. {emoji} {t['text'][:80]}...")

    dashboard_url = "https://ichiya0220kaneko-code.github.io/ai-tweet-dashboard/"
    lines.append(f"\n📊 [ダッシュボードを開く]({dashboard_url})")

    payload = {"content": "\n".join(lines)}
    r = requests.post(DISCORD_WEBHOOK_URL, json=payload)
    print(f"Discord: {r.status_code}")

# ─── メイン処理 ───────────────────────────────────────
def main():
    today = datetime.now(JST)
    date_str = today.strftime("%Y年%m月%d日")
    print(f"=== AI Tweet Dashboard {date_str} ===")

    all_tweets = []

    # 2アカウントのいいね取得
    for username, token in zip(X_USERNAMES, X_BEARER_TOKENS):
        print(f"Fetching likes for @{username}...")
        try:
            user_id = get_user_id(username, token)
            tweets = get_liked_tweets(user_id, token)
            # 前日のツイートのみ
            filtered = [t for t in tweets if is_yesterday(t.get("created_at", ""))]
            # AI関連のみ
            ai_tweets = [t for t in filtered if is_ai_related(t.get("text", ""))]
            print(f"  @{username}: {len(tweets)}件 → 前日分{len(filtered)}件 → AI関連{len(ai_tweets)}件")
            for t in ai_tweets:
                t["source"] = f"liked_by_{username}"
            all_tweets.extend(ai_tweets)
        except Exception as e:
            print(f"  Error for @{username}: {e}")

    # トレンドAIツイート検索
    print("Searching trending AI tweets...")
    try:
        search_tweets = search_ai_tweets()
        # エンゲージメントが高いもの（いいね50以上）に絞る
        popular = [t for t in search_tweets
                   if t.get("public_metrics", {}).get("like_count", 0) >= 50]
        print(f"  検索結果: {len(search_tweets)}件 → 人気{len(popular)}件")
        all_tweets.extend(popular)
    except Exception as e:
        print(f"  Search error: {e}")

    # 重複除去
    all_tweets = deduplicate(all_tweets)
    print(f"重複除去後: {len(all_tweets)}件")

    if not all_tweets:
        print("収集ツイートなし。終了します。")
        return

    # Gemini分類
    print("Classifying with Gemini...")
    classifications = classify_tweets(all_tweets)

    # HTML出力 (GitHub Pages)
    html = generate_html(all_tweets, classifications, date_str)
    Path("docs/index.html").write_text(html, encoding="utf-8")
    print("docs/index.html を生成しました")

    # Markdown出力 (Obsidian同期用)
    md = generate_markdown(all_tweets, classifications, date_str)
    md_filename = f"obsidian/AI情報_{today.strftime('%Y-%m-%d')}.md"
    Path("obsidian").mkdir(exist_ok=True)
    Path(md_filename).write_text(md, encoding="utf-8")
    print(f"{md_filename} を生成しました")

    # Discord通知
    print("Sending Discord notification...")
    send_discord(all_tweets, classifications, date_str)

    print("=== 完了 ===")

if __name__ == "__main__":
    main()
