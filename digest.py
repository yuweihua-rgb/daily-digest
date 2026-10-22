import os
import re
import html
import time
import smtplib
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import feedparser
import markdown
from google import genai

# ====== 設定區：想改來源、篇數、時間範圍就改這裡 ======
FEEDS = [
    ("Supply Chain Dive", "https://www.supplychaindive.com/feeds/news/"),
    ("TechCrunch", "https://techcrunch.com/feed/"),
    ("CNBC", "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
    ("TechCrunch Fintech", "https://techcrunch.com/category/fintech/feed/"),
    ("Harvard Business Review", "https://feeds.hbr.org/harvardbusiness"),
    ("科技新報", "https://technews.tw/feed/"),
    ("INSIDE", "https://www.inside.com.tw/feed"),
    ("數位時代", "https://www.bnext.com.tw/rss"),
]
MAX_PER_FEED = 6      # 每個來源最多取幾篇
HOURS = 24            # 只取過去幾小時內的文章
DESC_LIMIT = 300      # 每篇摘錄最多幾個字元
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
# =====================================================

PROMPT = """以下是過去 24 小時來自多個來源的新文章，格式為「[來源] 標題 | 連結 | 摘要」。
請用繁體中文整理成每日產業簡報：

1.【今日最重要 3 則】各 2 句說明重點與為何重要，附連結
2.【分類摘要】依主題分為：供應鏈與製造、科技與新創、金融科技與財經、管理與商業、台灣在地動態。每則 1–2 句，附連結
3. 重複報導同一事件的只保留一則
4. 英文內容請翻譯成繁體中文，專有名詞保留英文
5. 最後加一行【今日觀察】，用 1–2 句總結整體趨勢

沒有內容的分類請略過。連結請使用 Markdown 格式 [標題](網址)。

文章資料：
{articles}
"""


def clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def fetch_articles() -> str:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=HOURS)
    lines = []
    for name, url in FEEDS:
        try:
            feed = feedparser.parse(url, agent="Mozilla/5.0 (DailyDigestBot)")
            if not feed.entries:
                print(f"[警告] {name} 沒有取得文章，請確認網址：{url}")
                continue
            count = 0
            for e in feed.entries:
                t = e.get("published_parsed") or e.get("updated_parsed")
                if t:
                    published = datetime(*t[:6], tzinfo=timezone.utc)
                    if published < cutoff:
                        continue
                title = clean(e.get("title", ""))
                link = e.get("link", "")
                desc = clean(e.get("summary", ""))[:DESC_LIMIT]
                lines.append(f"[{name}] {title} | {link} | {desc}")
                count += 1
                if count >= MAX_PER_FEED:
                    break
            print(f"{name}: {count} 篇")
        except Exception as ex:
            print(f"[錯誤] {name} 抓取失敗：{ex}")
    return "\n".join(lines)


def summarize(articles: str) -> str:
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    last_error = None
    for attempt in range(3):
        try:
            resp = client.models.generate_content(
                model=MODEL, contents=PROMPT.format(articles=articles)
            )
            return resp.text
        except Exception as ex:
            last_error = ex
            print(f"Gemini 呼叫失敗（第 {attempt + 1} 次）：{ex}")
            time.sleep(10 * (attempt + 1))
    raise RuntimeError(f"Gemini 連續失敗：{last_error}")


def send_email(subject: str, body_md: str) -> None:
    sender = os.environ["GMAIL_ADDRESS"]
    password = os.environ["GMAIL_APP_PASSWORD"]
    recipient = os.environ.get("MAIL_TO", sender)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient
    msg.attach(MIMEText(body_md, "plain", "utf-8"))
    msg.attach(MIMEText(markdown.markdown(body_md), "html", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender, password)
        server.sendmail(sender, [recipient], msg.as_string())


def main() -> None:
    articles = fetch_articles()
    if not articles.strip():
        print("過去 24 小時沒有新文章，今天不寄信。")
        return
    summary = summarize(articles)
    today = datetime.now(ZoneInfo("Asia/Taipei")).strftime("%Y-%m-%d")
    send_email(f"每日產業簡報 {today}", summary)
    print("已寄出摘要。")


if __name__ == "__main__":
    main()
