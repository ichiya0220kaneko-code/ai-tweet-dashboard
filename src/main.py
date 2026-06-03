"""
AI情報ダッシュボード - マルチソース収集スクリプト
- Hacker News API（完全無料）
- RSSフィード（TechCrunch AI, VentureBeat, The Verge AI等）
- arXiv API（最新AI論文）
- Reddit API（AIサブレディット）
- Gemini APIで分類・スコアリング
- HTML (GitHub Pages) + Markdown (Obsidian) + Discord通知
"""

import os
import json
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
import google.generativeai as genai

GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
DISCORD_WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"]
JST = timezone(timedelta(hours=9))

# ─── Hacker News ────────────────────────────────────
AI_KEYWORDS = [
    "ai", "chatgpt", "claude", "gemini", "gpt", "llm", "machine learning",
    "deep learning", "openai", "anthropic", "midjourney", "stable diffusion",
    "prompt", "copilot", "hugging face", "transformer", "fine-tuning", "rag",
    "agent", "multimodal", "diffusion", "llama", "mistral", "perplexity",
    "cursor", "sora", "dall-e", "whisper", "langchain", "artificial intelligence",
    "neural", "nlp", "computer vision", "image generation", "生成ai", "人工知能",
]

def is_ai_related(text):
    text_lower = (text or "").lower()
    return any(kw in text_lower for kw in AI_KEYWORDS)

def fetch_hackernews():
    """Hacker NewsのトップストーリーからAI関連を取得"""
    items = []
    try:
        # Top stories + Best stories
        for list_type in ["topstories", "beststories"]:
            r = requests.get(f"https://hacker-news.firebaseio.com/v0/{list_type}.json", timeout=10)
            story_ids = r.json()[:50]  # 上位50件
            for sid in story_ids[:30]:
                try:
                    sr = requests.get(f"https://hacker-news.firebaseio.com/v0/item/{sid}.json", timeout=5)
                    story = sr.json()
                    if not story or story.get("type") != "story":
                        continue
                    title = story.get("title", "")
                    if not is_ai_related(title):
                        continue
                    items.append({
                        "id": f"hn_{sid}",
                        "title": title,
                        "text": title,
                        "url": story.get("url", f"https://news.ycombinator.com/item?id={sid}"),
                        "score": story.get("score", 0),
                        "comments": story.get("descendants", 0),
                        "source": "Hacker News",
                        "source_emoji": "🟠",
                        "created_at": datetime.fromtimestamp(story.get("time", 0), tz=JST).isoformat(),
                    })
                except Exception:
                    continue
        print(f"Hacker News: {len(items)}件のAI記事")
    except Exception as e:
        print(f"Hacker News エラー: {e}")
    return items

def fetch_rss(url, source_name, source_emoji):
    """RSSフィードからAI関連記事を取得"""
    items = []
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; AI-Dashboard/1.0)"}
        r = requests.get(url, timeout=10, headers=headers)
        root = ET.fromstring(r.content)

        # RSS 2.0
        for item in root.findall(".//item")[:20]:
            title = item.findtext("title", "")
            link = item.findtext("link", "")
            desc = item.findtext("description", "")
            pub_date = item.findtext("pubDate", "")

            if not is_ai_related(title + " " + desc):
                continue

            items.append({
                "id": f"rss_{hash(link)}",
                "title": title,
                "text": f"{title}\n{desc[:200]}",
                "url": link,
                "score": 0,
                "source": source_name,
                "source_emoji": source_emoji,
                "created_at": datetime.now(JST).isoformat(),
            })
    except Exception as e:
        print(f"{source_name} RSSエラー: {e}")
    return items

def fetch_all_rss():
    """複数RSSフィードを収集"""
    feeds = [
        ("https://techcrunch.com/category/artificial-intelligence/feed/", "TechCrunch AI", "💻"),
        ("https://venturebeat.com/ai/feed/", "VentureBeat AI", "🚀"),
        ("https://www.theverge.com/ai-artificial-intelligence/rss/index.xml", "The Verge AI", "🔷"),
        ("https://feeds.feedburner.com/oreilly/radar", "O'Reilly Radar", "📚"),
    ]
    all_items = []
    for url, name, emoji in feeds:
        items = fetch_rss(url, name, emoji)
        print(f"{name}: {len(items)}件")
        all_items.extend(items)
    return all_items

def fetch_arxiv():
    """arXivから最新AI論文を取得"""
    items = []
    try:
        queries = ["cat:cs.AI", "cat:cs.LG", "cat:cs.CL"]
        for query in queries[:2]:
            url = f"https://export.arxiv.org/api/query?search_query={query}&sortBy=submittedDate&sortOrder=descending&max_results=10"
            r = requests.get(url, timeout=10)
            root = ET.fromstring(r.content)
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            for entry in root.findall("atom:entry", ns)[:5]:
                title = entry.findtext("atom:title", "", ns).strip().replace("\n", " ")
                summary = entry.findtext("atom:summary", "", ns).strip()[:300]
                link = entry.find("atom:id", ns)
                url_link = link.text if link is not None else ""
                items.append({
                    "id": f"arxiv_{hash(url_link)}",
                    "title": title,
                    "text": f"📄 {title}\n{summary}",
                    "url": url_link,
                    "score": 0,
                    "source": "arXiv",
                    "source_emoji": "🔬",
                    "created_at": datetime.now(JST).isoformat(),
                })
        print(f"arXiv: {len(items)}件")
    except Exception as e:
        print(f"arXiv エラー: {e}")
    return items

def fetch_reddit():
    """RedditのAI関連サブレディットから人気投稿を取得"""
    items = []
    subreddits = ["artificial", "MachineLearning", "LocalLLaMA", "ChatGPT"]
    headers = {"User-Agent": "AI-Dashboard/1.0"}
    for sub in subreddits:
        try:
            r = requests.get(
                f"https://www.reddit.com/r/{sub}/hot.json?limit=10",
                headers=headers, timeout=10
            )
            if r.status_code != 200:
                continue
            posts = r.json().get("data", {}).get("children", [])
            for post in posts[:5]:
                d = post.get("data", {})
                title = d.get("title", "")
                if d.get("score", 0) < 100:
                    continue
                items.append({
                    "id": f"reddit_{d.get('id')}",
                    "title": title,
                    "text": title,
                    "url": f"https://reddit.com{d.get('permalink', '')}",
                    "score": d.get("score", 0),
                    "source": f"Reddit r/{sub}",
                    "source_emoji": "🟥",
                    "created_at": datetime.now(JST).isoformat(),
                })
            print(f"Reddit r/{sub}: {len(posts)}件中{len([p for p in posts if p.get('data',{}).get('score',0)>=100])}件")
        except Exception as e:
            print(f"Reddit r/{sub} エラー: {e}")
    return items

def deduplicate(items):
    seen = set()
    result = []
    for item in items:
        if item["id"] not in seen:
            seen.add(item["id"])
            result.append(item)
    return result

# ─── Gemini 分類 ─────────────────────────────────────
def classify_items(items):
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel("gemini-1.5-flash")

    item_list = "\n".join([
        f"{i+1}. [{item['source']}] {item['title'][:150]}"
        for i, item in enumerate(items)
    ])

    prompt = f"""以下のAI関連ニュース・記事を分析して、JSON形式で返してください。

記事一覧:
{item_list}

各記事に対して以下を判定してください：
- category: "新機能/アップデート" | "使い方/Tips" | "研究/論文" | "議論/考察" | "ツール紹介" | "業界ニュース"
- importance: 1〜5の整数（5が最重要・実用性・新規性・影響度で判断）
- reason: なぜ重要か1行で（日本語）
- emoji: カテゴリに合う絵文字1つ

返答形式（JSON配列のみ）:
[
  {{"index": 1, "category": "...", "importance": 4, "reason": "...", "emoji": "..."}},
  ...
]"""

    try:
        response = model.generate_content(prompt)
        text = response.text.strip()
        if "```" in text:
            text = text.split("```")[1].replace("json", "").strip()
        classifications = json.loads(text)
        result = {}
        for c in classifications:
            idx = c["index"] - 1
            if 0 <= idx < len(items):
                result[items[idx]["id"]] = c
        return result
    except Exception as e:
        print(f"Gemini エラー: {e}")
        return {item["id"]: {"category": "業界ニュース", "importance": 3, "reason": "AI関連情報", "emoji": "📌"} for item in items}

# ─── HTML生成 ─────────────────────────────────────────
def generate_html(items, classifications, date_str):
    cats = ["新機能/アップデート", "使い方/Tips", "研究/論文", "ツール紹介", "業界ニュース", "議論/考察"]
    grouped = {c: [] for c in cats}

    for item in sorted(items, key=lambda x: classifications.get(x["id"], {}).get("importance", 0), reverse=True):
        clf = classifications.get(item["id"], {})
        cat = clf.get("category", "業界ニュース")
        if cat not in grouped:
            cat = "業界ニュース"
        grouped[cat].append((item, clf))

    cards_html = ""
    for cat in cats:
        cat_items = grouped.get(cat, [])
        if not cat_items:
            continue
        emoji = cat_items[0][1].get("emoji", "📌")
        cards_html += f'<div class="category"><h2>{emoji} {cat} <span class="count">{len(cat_items)}</span></h2>'
        for item, clf in cat_items:
            importance = clf.get("importance", 1)
            stars = "⭐" * importance
            reason = clf.get("reason", "")
            title = item["title"].replace("<", "&lt;").replace(">", "&gt;")
            source = item["source"]
            source_emoji = item.get("source_emoji", "📰")
            score = item.get("score", 0)
            score_html = f'<span class="score">👍 {score:,}</span>' if score > 0 else ""
            cards_html += f"""
<div class="card importance-{importance}">
  <div class="card-header">
    <span class="stars">{stars}</span>
    <span class="badge">{source_emoji} {source}</span>
    {score_html}
  </div>
  <div class="title">{title}</div>
  <div class="reason">💡 {reason}</div>
  <a href="{item['url']}" target="_blank" class="article-link">記事を読む →</a>
</div>"""
        cards_html += "</div>"

    top5 = sorted(items, key=lambda x: classifications.get(x["id"], {}).get("importance", 0), reverse=True)[:5]
    top5_html = "".join([
        f'<li>{classifications.get(t["id"],{}).get("emoji","📌")} {t["title"][:80]}</li>'
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
  .date {{ text-align: center; color: #888; font-size: 0.85em; margin-bottom: 8px; }}
  .sources {{ text-align: center; color: #666; font-size: 0.75em; margin-bottom: 20px; }}
  .summary {{ background: #1a1a2e; border-radius: 12px; padding: 16px; margin-bottom: 20px; border-left: 4px solid #a78bfa; }}
  .summary h2 {{ color: #a78bfa; margin-bottom: 8px; font-size: 1em; }}
  .summary li {{ margin: 6px 0; font-size: 0.88em; line-height: 1.5; list-style: none; }}
  .category {{ margin-bottom: 24px; }}
  .category h2 {{ font-size: 1em; color: #c4b5fd; margin-bottom: 10px; padding-bottom: 6px; border-bottom: 1px solid #333; }}
  .count {{ background: #6d28d9; color: white; padding: 2px 8px; border-radius: 10px; font-size: 0.75em; margin-left: 6px; }}
  .card {{ background: #1a1a2e; border-radius: 10px; padding: 14px; margin-bottom: 12px; border-left: 3px solid #444; }}
  .card.importance-5 {{ border-left-color: #f59e0b; background: #1f1a10; }}
  .card.importance-4 {{ border-left-color: #a78bfa; }}
  .card.importance-3 {{ border-left-color: #34d399; }}
  .card-header {{ display: flex; align-items: center; gap: 8px; margin-bottom: 8px; flex-wrap: wrap; }}
  .stars {{ font-size: 0.75em; }}
  .badge {{ font-size: 0.72em; padding: 2px 8px; border-radius: 8px; background: #2d2d4e; color: #c4b5fd; }}
  .score {{ font-size: 0.75em; color: #888; margin-left: auto; }}
  .title {{ font-size: 0.95em; font-weight: 600; line-height: 1.5; margin-bottom: 8px; }}
  .reason {{ font-size: 0.8em; color: #a3e635; margin-bottom: 10px; }}
  .article-link {{ font-size: 0.82em; color: #60a5fa; text-decoration: none; }}
  .article-link:hover {{ text-decoration: underline; }}
  @media (min-width: 768px) {{
    body {{ max-width: 800px; margin: 0 auto; padding: 24px; }}
    h1 {{ font-size: 1.8em; }}
  }}
</style>
</head>
<body>
<h1>🤖 AI情報ダッシュボード</h1>
<div class="date">📅 {date_str} | {len(items)}件</div>
<div class="sources">🟠 Hacker News &nbsp;|&nbsp; 💻 TechCrunch &nbsp;|&nbsp; 🚀 VentureBeat &nbsp;|&nbsp; 🔬 arXiv &nbsp;|&nbsp; 🟥 Reddit</div>
<div class="summary">
  <h2>⭐ 本日のTOP5</h2>
  <ol>{top5_html}</ol>
</div>
{cards_html}
</body>
</html>"""

# ─── Markdown生成 ─────────────────────────────────────
def generate_markdown(items, classifications, date_str):
    lines = [f"# AI情報ダッシュボード - {date_str}", "", f"収集件数: {len(items)}件", ""]
    cats = ["新機能/アップデート", "使い方/Tips", "研究/論文", "ツール紹介", "業界ニュース", "議論/考察"]
    grouped = {c: [] for c in cats}
    for item in sorted(items, key=lambda x: classifications.get(x["id"], {}).get("importance", 0), reverse=True):
        clf = classifications.get(item["id"], {})
        cat = clf.get("category", "業界ニュース")
        if cat not in grouped:
            cat = "業界ニュース"
        grouped[cat].append((item, clf))

    for cat in cats:
        cat_items = grouped.get(cat, [])
        if not cat_items:
            continue
        emoji = cat_items[0][1].get("emoji", "📌")
        lines.append(f"## {emoji} {cat}")
        for item, clf in cat_items:
            importance = clf.get("importance", 1)
            stars = "⭐" * importance
            reason = clf.get("reason", "")
            lines += [
                f"### {stars} {item['title']}",
                f"- 🔗 [{item['source']}]({item['url']})",
                f"- 💡 {reason}",
                "",
            ]
    return "\n".join(lines)

# ─── Discord通知 ──────────────────────────────────────
def send_discord(items, classifications, date_str):
    top5 = sorted(items, key=lambda x: classifications.get(x["id"], {}).get("importance", 0), reverse=True)[:5]
    lines = [
        f"**🤖 AI情報ダッシュボード - {date_str}**",
        f"本日 **{len(items)}件** のAI情報を収集しました！",
        "",
        "**⭐ TOP5**",
    ]
    for i, item in enumerate(top5, 1):
        clf = classifications.get(item["id"], {})
        emoji = clf.get("emoji", "📌")
        lines.append(f"{i}. {emoji} {item['title'][:80]}")

    dashboard_url = "https://ichiya0220kaneko-code.github.io/ai-tweet-dashboard/"
    lines.append(f"\n📊 [ダッシュボードを開く]({dashboard_url})")

    payload = {"content": "\n".join(lines)}
    r = requests.post(DISCORD_WEBHOOK_URL, json=payload)
    print(f"Discord通知: {r.status_code}")

# ─── メイン ───────────────────────────────────────────
def main():
    today = datetime.now(JST)
    date_str = today.strftime("%Y年%m月%d日")
    print(f"=== AI情報ダッシュボード {date_str} ===")

    all_items = []

    # 各ソースから収集
    all_items.extend(fetch_hackernews())
    all_items.extend(fetch_all_rss())
    all_items.extend(fetch_arxiv())
    all_items.extend(fetch_reddit())

    # 重複除去
    all_items = deduplicate(all_items)
    print(f"重複除去後: {len(all_items)}件")

    if not all_items:
        print("収集データなし。終了します。")
        return

    # Gemini分類（30件ずつ処理）
    print("Geminiで分類中...")
    classifications = {}
    batch_size = 30
    for i in range(0, len(all_items), batch_size):
        batch = all_items[i:i+batch_size]
        batch_clf = classify_items(batch)
        classifications.update(batch_clf)
        print(f"  {min(i+batch_size, len(all_items))}/{len(all_items)}件分類完了")

    # HTML出力
    html = generate_html(all_items, classifications, date_str)
    Path("docs/index.html").write_text(html, encoding="utf-8")
    print(f"docs/index.html 生成完了（{len(all_items)}件）")

    # Markdown出力
    md = generate_markdown(all_items, classifications, date_str)
    Path("obsidian").mkdir(exist_ok=True)
    md_path = f"obsidian/AI情報_{today.strftime('%Y-%m-%d')}.md"
    Path(md_path).write_text(md, encoding="utf-8")
    print(f"{md_path} 生成完了")

    # Discord通知
    send_discord(all_items, classifications, date_str)

    print("=== 完了 ===")

if __name__ == "__main__":
    main()
