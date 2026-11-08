import os
import sys
import re
import html
import glob
import json
import time
import socket
import datetime
import urllib.parse
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import requests
from bs4 import BeautifulSoup

TAIPEI_TZ = datetime.timezone(datetime.timedelta(hours=8))
TOP_N = int(os.environ.get("TOP_N", "10"))
DEDUP_DAYS = int(os.environ.get("DEDUP_DAYS", "7"))
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def log(msg):
    print(msg, flush=True)


def load_config():
    env_config = {}
    if os.environ.get("SENDER_EMAIL"):
        env_config["sender_email"] = os.environ.get("SENDER_EMAIL")
    if os.environ.get("SMTP_PASSWORD"):
        env_config["smtp_password"] = os.environ.get("SMTP_PASSWORD")
    if os.environ.get("RECIPIENT_EMAIL"):
        env_config["recipient_email"] = os.environ.get("RECIPIENT_EMAIL")

    script_dir = os.path.dirname(os.path.abspath(__file__))
    if os.environ.get("GITHUB_ACTIONS") == "true":
        env_config["archive_dir"] = "archive"
        env_config["history_file"] = "history.json"
        env_config["smtp_server"] = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
        env_config["smtp_port"] = int(os.environ.get("SMTP_PORT", 465))
        return env_config

    config_path = os.path.join(script_dir, "config.json")
    local_config = {}
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                local_config = json.load(f)
        except Exception as e:
            log(f"Error loading local config: {e}")

    config = {
        "smtp_server": "smtp.gmail.com",
        "smtp_port": 465,
        "sender_email": "a7662888@gmail.com",
        "smtp_password": "your-gmail-app-password",
        "recipient_email": "a7662888@gmail.com",
        "archive_dir": os.path.join(script_dir, "archive"),
        "history_file": os.path.join(script_dir, "history.json"),
    }
    config.update(local_config)
    config.update(env_config)
    return config


def load_history(history_file, archive_dir):
    """載入 7 天去重歷史紀錄；若無紀錄則自動從最近 7 天的 archive/*.md 回填。"""
    history = {"records": {}}
    if history_file and os.path.exists(history_file):
        try:
            with open(history_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and isinstance(data.get("records"), dict):
                    history = data
        except Exception as e:
            log(f"[Warn] Failed to read {history_file}: {e}")

    if archive_dir and os.path.exists(archive_dir):
        today = datetime.datetime.now(TAIPEI_TZ).date()
        cutoff = today - datetime.timedelta(days=DEDUP_DAYS)
        for md_path in sorted(glob.glob(os.path.join(archive_dir, "github-trending-*.md"))):
            m_date = re.search(r"github-trending-(\d{4}-\d{2}-\d{2})\.md$", md_path)
            if not m_date:
                continue
            try:
                file_date = datetime.date.fromisoformat(m_date.group(1))
            except ValueError:
                continue
            if file_date < cutoff or file_date >= today:
                continue
            try:
                content = open(md_path, "r", encoding="utf-8").read()
                for m_repo in re.finditer(r"\|\s*\[([^\]]+/[^\]]+)\]\(https://github\.com/[^)]+\)", content):
                    full_name = m_repo.group(1).strip()
                    if full_name not in history["records"]:
                        history["records"][full_name] = {
                            "sent_date": file_date.isoformat(),
                            "desc_en": "",
                            "stars_int": 0,
                            "release_tag": "",
                            "pushed_at": "",
                        }
            except Exception:
                pass

    return history


def save_history(history_file, history, repos, date_str):
    """將今日成功寄出的 repo 寫入 history.json，並清理超過 30 天的舊紀錄。"""
    if not history_file:
        return
    records = history.setdefault("records", {})
    for repo in repos:
        records[repo["full_name"]] = {
            "sent_date": date_str,
            "desc_en": repo.get("desc_en", ""),
            "stars_int": repo.get("stars_int", 0),
            "release_tag": repo.get("release_tag", ""),
            "pushed_at": repo.get("pushed_at", ""),
        }

    today = datetime.date.fromisoformat(date_str)
    cutoff_30d = today - datetime.timedelta(days=30)
    cleaned = {}
    for k, v in records.items():
        try:
            d = datetime.date.fromisoformat(str(v.get("sent_date", ""))[:10])
            if d >= cutoff_30d:
                cleaned[k] = v
        except Exception:
            cleaned[k] = v
    history["records"] = cleaned

    try:
        with open(history_file, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2, sort_keys=True)
        log(f"Updated deduplication history: {history_file} ({len(cleaned)} tracked repos)")
    except Exception as e:
        log(f"[Warn] Failed to save {history_file}: {e}")


TW_TERM_MAP = [
    ("開源項目", "開源專案"),
    ("軟件", "軟體"),
    ("硬件", "硬體"),
    ("代碼", "程式碼"),
    ("源碼", "原始碼"),
    ("視頻", "影片"),
    ("視訊", "影片"),
    ("音頻", "音訊"),
    ("項目", "專案"),
    ("倉庫", "儲存庫"),
    ("數據庫", "資料庫"),
    ("數據", "資料"),
    ("內存", "記憶體"),
    ("網絡", "網路"),
    ("接口", "介面"),
    ("默認", "預設"),
    ("支持", "支援"),
    ("信息", "資訊"),
    ("調用", "呼叫"),
    ("運行", "執行"),
    ("服務器", "伺服器"),
    ("客戶端", "用戶端"),
    ("智能體", "AI 代理（Agent）"),
    ("編碼代理", "寫程式代理（Coding Agent）"),
    ("格式化程序", "格式化工具"),
    ("程序", "程式"),
    ("標記", "Token"),
    ("座席", "Agent"),
]


def normalize_zh_tw(zh):
    for src, dst in TW_TERM_MAP:
        zh = zh.replace(src, dst)
    return zh.strip()


def _has_cjk(s):
    return bool(re.search(r"[\u4e00-\u9fff]", str(s or "")))


def translate_to_zh_tw(text):
    """三層翻譯瀑布（Google gtx + Browser UA -> clients5.google.com -> MyMemory），確保在雲端 Runner 不因限流退回英文。"""
    if not text or text == "No description":
        return "無專案描述"

    headers = {"User-Agent": BROWSER_UA, "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8"}
    sl = "auto" if _has_cjk(text) else "en"

    # Tier 1: translate.googleapis.com (with Browser User-Agent)
    try:
        url1 = (
            "https://translate.googleapis.com/translate_a/single"
            f"?client=gtx&sl={sl}&tl=zh-TW&dt=t&q={urllib.parse.quote(text)}"
        )
        r1 = requests.get(url1, headers=headers, timeout=10)
        if r1.status_code == 200:
            data = r1.json()
            zh = "".join(part[0] for part in data[0] if part and part[0]).strip()
            if _has_cjk(zh):
                return normalize_zh_tw(zh)
        else:
            log(f"  [Translate Tier 1 HTTP {r1.status_code}] Switching to Tier 2...")
    except Exception as e:
        log(f"  [Translate Tier 1 error: {e}] Switching to Tier 2...")

    # Tier 2: clients5.google.com (Chrome extension dictionary endpoint)
    try:
        url2 = f"https://clients5.google.com/translate_a/t?client=dict-chrome-ex&sl={sl}&tl=zh-TW"
        r2 = requests.post(url2, data={"q": text}, headers=headers, timeout=10)
        if r2.status_code == 200:
            data2 = r2.json()
            if isinstance(data2, list) and data2:
                first = data2[0]
                zh2 = first[0] if isinstance(first, list) else str(first)
                if _has_cjk(zh2):
                    return normalize_zh_tw(zh2)
        else:
            log(f"  [Translate Tier 2 HTTP {r2.status_code}] Switching to Tier 3...")
    except Exception as e:
        log(f"  [Translate Tier 2 error: {e}] Switching to Tier 3...")

    # Tier 3: MyMemory Translation API (non-Google independent cloud fallback)
    try:
        url3 = f"https://api.mymemory.translated.net/get?q={urllib.parse.quote(text[:480])}&langpair=en|zh-TW"
        r3 = requests.get(url3, headers=headers, timeout=10)
        if r3.status_code == 200:
            zh3 = (r3.json().get("responseData") or {}).get("translatedText") or ""
            if _has_cjk(zh3):
                return normalize_zh_tw(zh3)
    except Exception as e:
        log(f"  [Translate Tier 3 error: {e}]")

    return normalize_zh_tw(text)


def parse_int_stars(s):
    if not s:
        return 0
    m = re.search(r"([\d,]+)", str(s))
    if not m:
        return 0
    try:
        return int(m.group(1).replace(",", ""))
    except Exception:
        return 0


def fetch_github_trending(since="daily"):
    url = f"https://github.com/trending?since={since}"
    headers = {"User-Agent": BROWSER_UA}

    for attempt in range(3):
        try:
            response = requests.get(url, headers=headers, timeout=15)
            if response.status_code == 200:
                break
            log(f"Fetch trending ({since}) attempt {attempt+1} status: {response.status_code}")
        except Exception as e:
            log(f"Request error while fetching GitHub trending ({since}) attempt {attempt+1}: {e}")
        time.sleep(2)
    else:
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    articles = soup.find_all("article", class_="Box-row")
    repos = []

    for article in articles:
        h2 = article.find("h2")
        if not h2:
            continue
        a = h2.find("a")
        if not a:
            continue

        href = a.get("href", "")
        repo_link = f"https://github.com/{href.lstrip('/')}"
        repo_name = a.text.strip().replace("\n", "").replace(" ", "")

        parts = repo_name.split("/")
        owner, name = (parts[0], parts[1]) if len(parts) == 2 else ("", repo_name)

        p = article.find("p")
        description_en = p.text.strip() if p else "No description"

        lang_span = article.find("span", itemprop="programmingLanguage")
        lang = lang_span.text.strip() if lang_span else "N/A"

        stars_today_el = article.find(lambda tag: tag.name == "span" and "stars" in tag.text)
        stars_today = stars_today_el.text.strip() if stars_today_el else "N/A"
        stars_today_cleaned = (
            stars_today.replace("stars today", "")
            .replace("stars this week", "")
            .replace("stars this month", "")
            .strip()
        )
        stars_today_int = parse_int_stars(stars_today_cleaned)

        stars_total_el = article.find("a", href=lambda h: h and h.endswith("/stargazers"))
        stars_total = stars_total_el.text.strip() if stars_total_el else "N/A"
        stars_int = parse_int_stars(stars_total)

        forks_el = article.find("a", href=lambda h: h and h.endswith("/forks"))
        forks = forks_el.text.strip() if forks_el else "N/A"

        repos.append({
            "owner": owner,
            "name": name,
            "full_name": repo_name,
            "link": repo_link,
            "desc_en": description_en,
            "desc_zh": "",
            "readme_highlight_zh": "",
            "lang": lang,
            "stars_today": stars_today_cleaned,
            "stars_today_int": stars_today_int,
            "stars_total": stars_total,
            "stars_int": stars_int,
            "forks": forks,
            "topics": [],
            "homepage": "",
            "update_reason": "",
        })

    return repos


PERMISSIVE = {
    "MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC",
    "Unlicense", "0BSD", "MPL-2.0", "Zlib", "PostgreSQL"
}
COPYLEFT = {
    "GPL-2.0", "GPL-3.0", "AGPL-3.0", "LGPL-2.1", "LGPL-3.0",
    "GPL-2.0-only", "GPL-3.0-only", "GPL-3.0-or-later", "AGPL-3.0-only"
}


def classify_license(spdx):
    if spdx == "NOASSERTION":
        return "⚠️ 自訂/未識別", "需人工開 LICENSE 確認（偵測失敗，不等於無授權）"
    if not spdx or spdx == "NONE":
        return "🚫 無授權檔", "All rights reserved，不得取用程式碼"
    if spdx in PERMISSIVE:
        return f"✅ {spdx}", "寬鬆，可在地化取用"
    if spdx in COPYLEFT:
        return f"⚠️ {spdx}", "copyleft 傳染，衍生作品須同授權；僅可讀設計"
    return f"❓ {spdx}", "非常見授權，取用前人工確認"


def fetch_readme_summary_en(full_name, headers):
    """擷取專案 README 第一段實質文字說明，清除 HTML 標籤與符號列。"""
    try:
        h = dict(headers)
        h["Accept"] = "application/vnd.github.raw+json"
        r = requests.get(f"https://api.github.com/repos/{full_name}/readme", headers=h, timeout=10)
        if r.status_code != 200 or not r.text:
            return ""
        lines = r.text.splitlines()
        cleaned_lines = []
        in_code = False
        for line in lines[:150]:
            s = line.strip()
            if s.startswith("```"):
                in_code = not in_code
                continue
            if in_code:
                continue
            if not s:
                if cleaned_lines:
                    break
                continue
            s = html.unescape(s)
            s = re.sub(r"<[^>]+>", " ", s).strip()
            if (
                s.startswith("#")
                or s.startswith("!")
                or s.startswith("[![")
                or s.startswith("|")
                or s.startswith("---")
                or s.startswith(">")
                or re.match(r"^\[.*\]\(.*\)$", s)
            ):
                continue
            s = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", s)
            s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)
            s = re.sub(r"[*_`~•·|]+", " ", s)
            s = re.sub(r"\s+", " ", s).strip()
            if len(s) >= 30 and len(re.findall(r"[A-Za-z\u4e00-\u9fff]{2,}", s)) >= 5:
                cleaned_lines.append(s)
                if sum(len(x) for x in cleaned_lines) >= 180:
                    break
        summary = " ".join(cleaned_lines).strip()
        if len(summary) > 240:
            summary = summary[:237].rsplit(" ", 1)[0] + "..."
        return summary
    except Exception:
        return ""


def fetch_repo_api_meta(repo):
    """查詢單一 repo 的 GitHub API 元資料、Topics、Homepage、最新 Release 與 README 摘要。"""
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "github-trending-daily",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    repo.setdefault("license_display", "—")
    repo.setdefault("license_note", "未查詢")
    repo.setdefault("created_at", "—")
    repo.setdefault("fork_ratio", "—")
    repo.setdefault("release_tag", "")
    repo.setdefault("pushed_at", "")
    repo.setdefault("topics", [])
    repo.setdefault("homepage", "")
    repo.setdefault("readme_en", "")

    try:
        r = requests.get(
            f"https://api.github.com/repos/{repo['full_name']}",
            headers=headers,
            timeout=15,
        )
        if r.status_code == 200:
            d = r.json()
            spdx = (d.get("license") or {}).get("spdx_id")
            repo["license_display"], repo["license_note"] = classify_license(spdx)
            repo["created_at"] = (d.get("created_at") or "")[:10] or "—"
            repo["pushed_at"] = d.get("pushed_at") or ""
            repo["topics"] = (d.get("topics") or [])[:5]
            homepage = (d.get("homepage") or "").strip()
            if homepage and homepage.startswith(("http://", "https://")):
                repo["homepage"] = homepage
            if d.get("description"):
                repo["desc_en"] = d["description"].strip()
            stars = d.get("stargazers_count")
            forks = d.get("forks_count")
            if isinstance(stars, int):
                repo["stars_int"] = stars
                repo["stars_total"] = f"{stars:,}"
            if isinstance(forks, int):
                repo["forks"] = f"{forks:,}"
            if isinstance(stars, int) and isinstance(forks, int) and forks > 0:
                repo["fork_ratio"] = f"1:{round(stars / forks)}"
        else:
            log(f"  API {r.status_code} for {repo['full_name']}")
    except Exception as e:
        log(f"  API error for {repo['full_name']}: {e}")

    try:
        r_rel = requests.get(
            f"https://api.github.com/repos/{repo['full_name']}/releases/latest",
            headers=headers,
            timeout=10,
        )
        if r_rel.status_code == 200:
            rel_data = r_rel.json()
            repo["release_tag"] = (rel_data.get("tag_name") or "").strip()
            repo["release_published_at"] = (rel_data.get("published_at") or "")[:10]
    except Exception:
        pass

    readme_en = fetch_readme_summary_en(repo["full_name"], headers)
    if readme_en and readme_en.lower() != repo.get("desc_en", "").lower():
        repo["readme_en"] = readme_en

    return repo


def select_top_repos_with_dedup(candidates, history, today_str, top_n=TOP_N):
    records = history.get("records", {})
    today = datetime.date.fromisoformat(today_str)
    cutoff = today - datetime.timedelta(days=DEDUP_DAYS)

    selected = []
    seen_names = set()

    for repo in candidates:
        full_name = repo["full_name"]
        if full_name in seen_names:
            continue
        seen_names.add(full_name)

        prev = records.get(full_name)
        in_recent_window = False
        if prev and prev.get("sent_date"):
            try:
                sent_date = datetime.date.fromisoformat(str(prev["sent_date"])[:10])
                if sent_date >= cutoff and sent_date < today:
                    in_recent_window = True
            except Exception:
                pass

        if not in_recent_window:
            fetch_repo_api_meta(repo)
            selected.append(repo)
            if len(selected) >= top_n:
                break
            continue

        fetch_repo_api_meta(repo)
        old_tag = (prev.get("release_tag") or "").strip()
        new_tag = (repo.get("release_tag") or "").strip()
        old_desc = (prev.get("desc_en") or "").strip()
        new_desc = (repo.get("desc_en") or "").strip()
        old_stars = int(prev.get("stars_int") or 0)
        new_stars = int(repo.get("stars_int") or 0)
        old_pushed = (prev.get("pushed_at") or "")[:10]
        new_pushed = (repo.get("pushed_at") or "")[:10]

        update_reasons = []
        if new_tag and old_tag and new_tag != old_tag:
            update_reasons.append(f"發布新版本 {new_tag}")
        elif new_tag and not old_tag and repo.get("release_published_at", "") > str(prev.get("sent_date", ""))[:10]:
            update_reasons.append(f"發布新版本 {new_tag}")

        if old_desc and new_desc and old_desc != new_desc:
            update_reasons.append("專案說明更新")

        if old_stars > 0 and (new_stars - old_stars) >= 1000 and (new_stars / old_stars) >= 1.20:
            update_reasons.append(f"星數暴增 +{new_stars - old_stars:,}")
        elif new_pushed and old_pushed and new_pushed > old_pushed and repo.get("stars_today_int", 0) >= 500:
            update_reasons.append(f"近期更新 ({new_pushed}) 且今日再增 +{repo['stars_today']} 星")

        if update_reasons:
            repo["update_reason"] = "、".join(update_reasons)
            log(f"  [Re-push] {full_name} (sent on {prev.get('sent_date')}) has update: {repo['update_reason']}")
            selected.append(repo)
            if len(selected) >= top_n:
                break
        else:
            log(f"  [Skip] {full_name} already sent on {prev.get('sent_date')} with no new update.")

    return selected


def build_markdown_report(repos, date_str):
    md = f"""---
title: "GitHub 每日熱門專案 Top {len(repos)} [{date_str}]"
tags:
  - github
  - trending
  - ai-generated
date: {date_str}
---

# 🚀 GitHub 每日熱門專案報告 Top {len(repos)} ({date_str})

| # | 專案名稱 (連結) | 開發語言 | 本日新增星星 | 總星星數 | Fork | Fork:Star | 授權 | 建立日期 | 繁體中文專案摘要 |
| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
"""
    for idx, repo in enumerate(repos, 1):
        update_tag = f" 🔄 *({repo['update_reason']})*" if repo.get("update_reason") else ""
        full_zh = repo["desc_zh"]
        if repo.get("readme_highlight_zh") and repo["readme_highlight_zh"] != repo["desc_zh"]:
            full_zh += f"<br>💡 **功能亮點**：{repo['readme_highlight_zh']}"
        md += (
            f"| {idx} | [{repo['full_name']}]({repo['link']}){update_tag} | `{repo['lang']}` "
            f"| `+{repo['stars_today']}` | `{repo['stars_total']}` "
            f"| `{repo.get('forks', '-')}` | `{repo.get('fork_ratio', '-')}` "
            f"| {repo.get('license_display', '-')} | {repo.get('created_at', '-')} "
            f"| {full_zh} |\n"
        )

    md += "\n\n---\n*本報告由 GitHub Actions 雲端排程自動產生（每日 06:43・7 天內不重複・有更新再推送）。*"
    return md


def build_plain_text_report(repos, date_str):
    lines = [
        f"🚀 GitHub 每日熱門專案 Top {len(repos)} ({date_str})",
        "每日 06:43 自動推送｜7 天內不重複・有更新再推",
        "=" * 60,
        "",
    ]
    for idx, repo in enumerate(repos, 1):
        upd = f" [🔄 {repo['update_reason']}]" if repo.get("update_reason") else ""
        lines.append(f"#{idx} {repo['full_name']}{upd}")
        lines.append(f"🔗 連結：{repo['link']}")
        lines.append(f"📝 繁中說明：{repo['desc_zh']}")
        if repo.get("readme_highlight_zh") and repo["readme_highlight_zh"] != repo["desc_zh"]:
            lines.append(f"💡 功能亮點：{repo['readme_highlight_zh']}")
        lines.append(
            f"📊 語言：{repo['lang']} | 今日 +{repo['stars_today']} ★ | 總星數 {repo['stars_total']} | 授權 {repo.get('license_display', '-')}"
        )
        lines.append("-" * 60)
    return "\n".join(lines)


def build_html_report(repos, date_str):
    rows_html = ""
    for idx, repo in enumerate(repos, 1):
        bg_color = "#1e222b" if idx % 2 == 1 else "#161b22"
        lang_color = "#6f42c1"
        if repo["lang"] == "Python":
            lang_color = "#3572A5"
        elif repo["lang"] in ["JavaScript", "TypeScript"]:
            lang_color = "#f1e05a" if repo["lang"] == "JavaScript" else "#3178c6"
        elif repo["lang"] == "Go":
            lang_color = "#00ADD8"
        elif repo["lang"] == "Rust":
            lang_color = "#dea584"
        elif repo["lang"] == "C++":
            lang_color = "#f34b7d"
        elif repo["lang"] == "Swift":
            lang_color = "#f05138"
        elif repo["lang"] == "HTML":
            lang_color = "#e34c26"
        elif repo["lang"] == "CSS":
            lang_color = "#563d7c"

        text_color = "#000" if repo["lang"] == "JavaScript" else "#fff"
        update_badge = ""
        if repo.get("update_reason"):
            update_badge = (
                f'<span style="background-color:#9e6a03;color:#fff;padding:2px 8px;'
                f'border-radius:10px;font-size:11px;margin-left:8px;">🔄 {repo["update_reason"]}</span>'
            )

        rel_info = f" &nbsp;|&nbsp; 最新版 {repo['release_tag']}" if repo.get("release_tag") else ""
        homepage_link = ""
        if repo.get("homepage"):
            homepage_link = (
                f' &nbsp;|&nbsp; <a href="{repo["homepage"]}" '
                f'style="color:#58a6ff;text-decoration:none;" target="_blank">🌐 官網/Demo</a>'
            )

        readme_block = ""
        if repo.get("readme_highlight_zh") and repo["readme_highlight_zh"] != repo["desc_zh"]:
            readme_block = (
                f'<div style="font-size: 13px; color: #b1bac4; line-height: 1.5; margin-top: 6px; '
                f'padding: 6px 10px; background-color: #0d1117; border-left: 3px solid #1f6feb; border-radius: 4px;">'
                f'💡 <b>功能亮點：</b>{repo["readme_highlight_zh"]}</div>'
            )

        topics_html = ""
        if repo.get("topics"):
            tags = "".join(
                f'<span style="display:inline-block;background-color:#1f2937;color:#79c0ff;'
                f'padding:1px 7px;border-radius:10px;font-size:11px;margin-right:5px;margin-top:4px;">#{t}</span>'
                for t in repo["topics"]
            )
            topics_html = f'<div style="margin-top: 4px;">{tags}</div>'

        rows_html += f"""
        <tr style="background-color: {bg_color}; border-bottom: 1px solid #30363d;">
            <td style="padding: 16px; vertical-align: top;">
                <div style="font-weight: bold; font-size: 16px; margin-bottom: 6px;">
                    <span style="color: #8b949e; margin-right: 6px;">#{idx}</span>
                    <a href="{repo['link']}" style="color: #58a6ff; text-decoration: none;" target="_blank">{repo['full_name']}</a>
                    {update_badge}
                </div>
                <div style="font-size: 14px; color: #e6edf3; line-height: 1.5; font-weight: 500;">{repo['desc_zh']}</div>
                {readme_block}
                <div style="font-size: 12px; color: #8b949e; margin-top: 5px; font-style: italic;">Original: {repo['desc_en']}</div>
                {topics_html}
                <div style="font-size: 11px; color: #8b949e; margin-top: 6px;">
                    &#x1F374; Fork {repo.get('forks', '-')} &nbsp;|&nbsp; Fork:Star {repo.get('fork_ratio', '-')} &nbsp;|&nbsp; 建立 {repo.get('created_at', '-')}{rel_info}{homepage_link}
                </div>
            </td>
            <td style="padding: 16px; text-align: center; vertical-align: middle;">
                <span style="background-color: {lang_color}; color: {text_color}; padding: 3px 8px; border-radius: 12px; font-size: 12px; font-weight: bold; white-space: nowrap;">
                    {repo['lang']}
                </span>
            </td>
            <td style="padding: 16px; text-align: center; vertical-align: middle; color: #3fb950; font-weight: bold; font-size: 14px; white-space: nowrap;">
                +{repo['stars_today']} ★
            </td>
            <td style="padding: 16px; text-align: center; vertical-align: middle; color: #e3b341; font-weight: bold; font-size: 14px; white-space: nowrap;">
                {repo['stars_total']}
            </td>
            <td style="padding: 16px; text-align: center; vertical-align: middle; font-size: 12px; color: #c9d1d9;">
                <div style="white-space: nowrap; font-weight: bold;">{repo.get('license_display', '-')}</div>
                <div style="color: #8b949e; margin-top: 4px; font-size: 10px; line-height: 1.4; max-width: 130px;">{repo.get('license_note', '')}</div>
            </td>
        </tr>
        """

    html_doc = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>GitHub 每日熱門專案 Top {len(repos)}</title>
    </head>
    <body style="background-color: #0d1117; color: #c9d1d9; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif; margin: 0; padding: 20px;">
        <div style="max-width: 920px; margin: 0 auto; background-color: #161b22; border: 1px solid #30363d; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 12px rgba(0,0,0,0.5);">
            <div style="background: linear-gradient(135deg, #1f6feb 0%, #0d1117 100%); padding: 28px 20px; text-align: center; border-bottom: 1px solid #30363d;">
                <h1 style="color: #ffffff; margin: 0; font-size: 26px; letter-spacing: 1px;">🚀 GitHub 每日熱門專案 Top {len(repos)}</h1>
                <p style="color: #c9d1d9; margin: 10px 0 0 0; font-size: 14px;">資料日期: {date_str} (每日 06:43 自動推送｜7 天內不重複・有更新再推)</p>
            </div>

            <div style="overflow-x: auto;">
                <table style="width: 100%; border-collapse: collapse; text-align: left;">
                    <thead>
                        <tr style="background-color: #161b22; border-bottom: 2px solid #30363d; color: #8b949e; font-size: 13px; text-transform: uppercase;">
                            <th style="padding: 12px 16px;">Repository 專案資訊與繁中亮點</th>
                            <th style="padding: 12px 16px; text-align: center;">主要語言</th>
                            <th style="padding: 12px 16px; text-align: center;">今日新增</th>
                            <th style="padding: 12px 16px; text-align: center;">總星星數</th>
                            <th style="padding: 12px 16px; text-align: center;">授權</th>
                        </tr>
                    </thead>
                    <tbody>
                        {rows_html}
                    </tbody>
                </table>
            </div>

            <div style="background-color: #0d1117; padding: 18px; text-align: center; font-size: 12px; color: #8b949e; border-top: 1px solid #30363d;">
                <p style="margin: 0;">本郵件由 GitHub Actions 雲端容器自動爬網、README 亮點擷取、7 天去重與繁體中文翻譯生成，電腦未開機亦準時發送。</p>
            </div>
        </div>
    </body>
    </html>
    """
    return html_doc


def _resolve_ipv4_host(server_host):
    try:
        infos = socket.getaddrinfo(server_host, None, socket.AF_INET, socket.SOCK_STREAM)
        if infos:
            return infos[0][4][0]
    except Exception:
        pass
    return server_host


def _attempt_smtp_send(server_host, port, use_ssl, sender, password, recipients, msg_str, force_ipv4=False):
    connect_host = _resolve_ipv4_host(server_host) if force_ipv4 else server_host
    if use_ssl:
        server = smtplib.SMTP_SSL(connect_host, port, timeout=30)
    else:
        server = smtplib.SMTP(connect_host, port, timeout=30)
    try:
        server.ehlo()
        if not use_ssl:
            server.starttls()
            server.ehlo()
        code, resp = server.docmd(
            "AUTH",
            "PLAIN " + smtplib.encode_base64(f"\0{sender}\0{password}".encode("utf-8"), eol=""),
        )
        if code != 235:
            raise smtplib.SMTPAuthenticationError(code, resp)
        server.sendmail(sender, recipients, msg_str)
        try:
            server.quit()
        except Exception:
            pass
    finally:
        try:
            server.close()
        except Exception:
            pass


def send_email(config, plain_content, html_content, date_str):
    sender = config.get("sender_email", "").strip().replace('"', "").replace("'", "")
    recipient = config.get("recipient_email", "")
    password = re.sub(r"\s+", "", config.get("smtp_password", "").strip())

    if not sender or not password or sender == "your-email@gmail.com":
        log("[WARNING] Email credentials not configured. Skipping email sending.")
        return False

    recipients = []
    for r in (recipient + ",a7662888@gmail.com").split(","):
        r_clean = r.strip().replace('"', "").replace("'", "").replace("<", "").replace(">", "")
        if r_clean and r_clean not in recipients:
            recipients.append(r_clean)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"🚀 GitHub 每日熱門專案 Top {TOP_N} [{date_str}]"
    msg["From"] = f"GitHub Trending Robot <{sender}>"
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(plain_content, "plain", "utf-8"))
    msg.attach(MIMEText(html_content, "html", "utf-8"))
    msg_str = msg.as_string()

    server_host = config.get("smtp_server", "smtp.gmail.com")
    max_retries = int(os.environ.get("SMTP_MAX_RETRIES", "12"))
    base_delay = int(os.environ.get("SMTP_RETRY_DELAY", "15"))

    endpoints = [
        (465, True, False),
        (587, False, False),
        (465, True, True),
        (587, False, True),
    ]

    for attempt in range(1, max_retries + 1):
        port, use_ssl, force_ipv4 = endpoints[(attempt - 1) % len(endpoints)]
        proto_label = f"{'SSL' if use_ssl else 'STARTTLS'}:{port}{'/IPv4' if force_ipv4 else ''}"
        try:
            log(f"[SMTP] Sending attempt {attempt}/{max_retries} via {server_host} ({proto_label}) to {recipients}...")
            _attempt_smtp_send(server_host, port, use_ssl, sender, password, recipients, msg_str, force_ipv4=force_ipv4)
            log(f"[SUCCESS] Email sent successfully to {recipients} on attempt {attempt}!")
            return True
        except smtplib.SMTPAuthenticationError as auth_err:
            err_msg = (
                auth_err.smtp_error.decode("utf-8", errors="ignore")
                if isinstance(auth_err.smtp_error, bytes)
                else str(auth_err.smtp_error)
            )
            log(
                f"[FATAL AUTH ERROR] Gmail 拒絕登入 (HTTP/SMTP {auth_err.smtp_code}): {err_msg}\n"
                "👉 原因：GitHub Secrets 中的 SMTP_PASSWORD (Gmail 16 位應用程式密碼) 已失效或被撤銷。\n"
                "👉 解決方式：請至 https://myaccount.google.com/apppasswords 產生新的 16 位應用程式密碼並更新至 GitHub Secret `SMTP_PASSWORD`。"
            )
            return False
        except Exception as e:
            log(f"[WARN] Attempt {attempt}/{max_retries} ({proto_label}) failed: {type(e).__name__}: {e}")
            if attempt < max_retries:
                sleep_sec = min(base_delay * attempt, 90)
                log(f"Waiting {sleep_sec}s before next retry...")
                time.sleep(sleep_sec)

    log(f"[ERROR] Exhausted all {max_retries} attempts without sending email.")
    return False


def main():
    now_taipei = datetime.datetime.now(TAIPEI_TZ)
    date_str = now_taipei.strftime("%Y-%m-%d")
    log(f"Starting GitHub Trending Daily Service - {now_taipei.isoformat()}")

    config = load_config()
    if not config:
        log("No valid configuration found. Exiting.")
        sys.exit(1)

    history_file = config.get("history_file")
    archive_dir = config.get("archive_dir")
    history = load_history(history_file, archive_dir)
    log(f"Loaded 7-day deduplication history ({len(history.get('records', {}))} records).")

    log("Fetching GitHub daily trending repositories...")
    candidates = fetch_github_trending(since="daily")
    for fallback_since in ("weekly", "monthly"):
        if len(candidates) >= TOP_N * 3:
            break
        log(f"Fetching {fallback_since} trending as supplemental pool for 7-day deduplication...")
        extra = fetch_github_trending(since=fallback_since)
        existing = {r["full_name"] for r in candidates}
        for item in extra:
            if item["full_name"] not in existing:
                candidates.append(item)
                existing.add(item["full_name"])

    if not candidates:
        log("No repositories crawled. Exiting.")
        sys.exit(1)

    log(f"Selecting top {TOP_N} repositories (filtering 7-day duplicates unless updated)...")
    repos = select_top_repos_with_dedup(candidates, history, date_str, top_n=TOP_N)
    log(f"Selected {len(repos)} repositories for {date_str}.")

    for i, repo in enumerate(repos):
        log(f"Translating ({i+1}/{len(repos)}): {repo['full_name']}...")
        repo["desc_zh"] = translate_to_zh_tw(repo["desc_en"])
        if repo.get("readme_en"):
            repo["readme_highlight_zh"] = translate_to_zh_tw(repo["readme_en"])

    if archive_dir:
        try:
            os.makedirs(archive_dir, exist_ok=True)
            archive_path = os.path.join(archive_dir, f"github-trending-{date_str}.md")
            md_content = build_markdown_report(repos, date_str)
            with open(archive_path, "w", encoding="utf-8") as f:
                f.write(md_content)
            log(f"Archived report: {archive_path}")
        except Exception as e:
            log(f"Failed to archive: {e}")

    plain_content = build_plain_text_report(repos, date_str)
    html_content = build_html_report(repos, date_str)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    preview_path = os.path.join(script_dir, "preview.html")
    try:
        with open(preview_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        log(f"Saved HTML preview to: {preview_path}")
    except Exception:
        pass

    email_status = send_email(config, plain_content, html_content, date_str)
    if email_status:
        save_history(history_file, history, repos, date_str)
        log("Job completed successfully.")
    else:
        log("Job completed without sending email.")
        sys.exit(1)


if __name__ == "__main__":
    main()
