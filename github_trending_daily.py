import os
import sys
import re
import glob
import json
import time
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

    # 自動從 archive 資料夾回填過去 7 天已出現過的 repo
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
            if file_date <= cutoff or file_date >= today:
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

    # 只保留最近 30 天紀錄
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


def translate_to_zh_tw(text):
    if not text or text == "No description":
        return "無專案描述"

    url = (
        "https://translate.googleapis.com/translate_a/single"
        f"?client=gtx&sl=auto&tl=zh-TW&dt=t&q={urllib.parse.quote(text)}"
    )
    for attempt in range(3):
        try:
            res = requests.get(url, timeout=10)
            if res.status_code == 200:
                result = res.json()
                translated_parts = [part[0] for part in result[0] if part and part[0]]
                zh = "".join(translated_parts).strip()
                # 常見中國大陸術語轉台灣慣用繁中術語
                zh = (
                    zh.replace("代碼", "程式碼")
                    .replace("視頻", "影片")
                    .replace("項目", "專案")
                    .replace("倉庫", "儲存庫")
                    .replace("數據", "資料")
                    .replace("開源項目", "開源專案")
                )
                return zh
        except Exception as e:
            if attempt == 2:
                log(f"Translation error: {e}")
            time.sleep(1)
    return text


def fetch_github_trending(since="daily"):
    url = f"https://github.com/trending?since={since}"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
    }

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

        stars_total_el = article.find("a", href=lambda h: h and h.endswith("/stargazers"))
        stars_total = stars_total_el.text.strip() if stars_total_el else "N/A"
        try:
            stars_int = int(stars_total.replace(",", "").strip())
        except Exception:
            stars_int = 0

        forks_el = article.find("a", href=lambda h: h and h.endswith("/forks"))
        forks = forks_el.text.strip() if forks_el else "N/A"

        repos.append({
            "owner": owner,
            "name": name,
            "full_name": repo_name,
            "link": repo_link,
            "desc_en": description_en,
            "desc_zh": "",
            "lang": lang,
            "stars_today": stars_today_cleaned,
            "stars_total": stars_total,
            "stars_int": stars_int,
            "forks": forks,
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


def fetch_repo_api_meta(repo):
    """查詢單一 repo 的 GitHub API 元資料與最新 Release tag。"""
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

    # 查詢最新 release tag（供「有更新再推送」判斷）
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

    return repo


def select_top_repos_with_dedup(candidates, history, today_str, top_n=TOP_N):
    """
    7 天內不重複篩選邏輯：
    - 若過去 7 天內未推送過：入選
    - 若過去 7 天內已推送過：檢查是否有新 Release 版本、描述更新、或星數暴增（+25% 且 >=1000 星）
      若有更新則標記 update_reason 並允許重新推送；否則略過。
    """
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
                if sent_date > cutoff and sent_date < today:
                    in_recent_window = True
            except Exception:
                pass

        if not in_recent_window:
            fetch_repo_api_meta(repo)
            selected.append(repo)
            if len(selected) >= top_n:
                break
            continue

        # 在 7 天內曾推送過 -> 先抓 API 檢查是否有重大更新
        fetch_repo_api_meta(repo)
        old_tag = (prev.get("release_tag") or "").strip()
        new_tag = (repo.get("release_tag") or "").strip()
        old_desc = (prev.get("desc_en") or "").strip()
        new_desc = (repo.get("desc_en") or "").strip()
        old_stars = int(prev.get("stars_int") or 0)
        new_stars = int(repo.get("stars_int") or 0)

        update_reasons = []
        if new_tag and old_tag and new_tag != old_tag:
            update_reasons.append(f"發布新版本 {new_tag}")
        elif new_tag and not old_tag and repo.get("release_published_at", "") > str(prev.get("sent_date", ""))[:10]:
            update_reasons.append(f"發布新版本 {new_tag}")

        if old_desc and new_desc and old_desc != new_desc:
            update_reasons.append("專案說明更新")

        if old_stars > 0 and (new_stars - old_stars) >= 1000 and (new_stars / old_stars) >= 1.25:
            update_reasons.append(f"星數暴增 +{new_stars - old_stars:,}")

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
        md += (
            f"| {idx} | [{repo['full_name']}]({repo['link']}){update_tag} | `{repo['lang']}` "
            f"| `+{repo['stars_today']}` | `{repo['stars_total']}` "
            f"| `{repo.get('forks', '-')}` | `{repo.get('fork_ratio', '-')}` "
            f"| {repo.get('license_display', '-')} | {repo.get('created_at', '-')} "
            f"| {repo['desc_zh']} |\n"
        )

    md += "\n\n---\n*本報告由 GitHub Actions 雲端排程自動產生（7 天內不重複、有更新再推送）。*"
    return md


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
        rel_info = f" &nbsp;|&nbsp; 最新版本 {repo['release_tag']}" if repo.get("release_tag") else ""

        rows_html += f"""
        <tr style="background-color: {bg_color}; border-bottom: 1px solid #30363d;">
            <td style="padding: 16px; vertical-align: top;">
                <div style="font-weight: bold; font-size: 16px; margin-bottom: 6px;">
                    <span style="color: #8b949e; margin-right: 6px;">#{idx}</span>
                    <a href="{repo['link']}" style="color: #58a6ff; text-decoration: none;">{repo['full_name']}</a>
                    {update_badge}
                </div>
                <div style="font-size: 14px; color: #c9d1d9; line-height: 1.5;">{repo['desc_zh']}</div>
                <div style="font-size: 12px; color: #8b949e; margin-top: 4px; font-style: italic;">Original: {repo['desc_en']}</div>
                <div style="font-size: 11px; color: #6e7681; margin-top: 6px;">
                    &#x1F374; Fork {repo.get('forks', '-')} &nbsp;|&nbsp; Fork:Star {repo.get('fork_ratio', '-')} &nbsp;|&nbsp; 建立 {repo.get('created_at', '-')}{rel_info}
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
                <div style="color: #6e7681; margin-top: 4px; font-size: 10px; line-height: 1.4; max-width: 130px;">{repo.get('license_note', '')}</div>
            </td>
        </tr>
        """

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>GitHub 每日熱門專案 Top {len(repos)}</title>
    </head>
    <body style="background-color: #0d1117; color: #c9d1d9; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif; margin: 0; padding: 20px;">
        <div style="max-width: 900px; margin: 0 auto; background-color: #161b22; border: 1px solid #30363d; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 12px rgba(0,0,0,0.5);">
            <div style="background: linear-gradient(135deg, #1f6feb 0%, #0d1117 100%); padding: 30px 20px; text-align: center; border-bottom: 1px solid #30363d;">
                <h1 style="color: #ffffff; margin: 0; font-size: 26px; letter-spacing: 1px;">🚀 GitHub 每日熱門專案 Top {len(repos)}</h1>
                <p style="color: #8b949e; margin: 10px 0 0 0; font-size: 14px;">資料日期: {date_str} (每日 06:43 自動推送｜7 天內不重複・有更新再推)</p>
            </div>

            <div style="overflow-x: auto;">
                <table style="width: 100%; border-collapse: collapse; text-align: left;">
                    <thead>
                        <tr style="background-color: #161b22; border-bottom: 2px solid #30363d; color: #8b949e; font-size: 13px; text-transform: uppercase;">
                            <th style="padding: 12px 16px;">Repository 專案資訊</th>
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

            <div style="background-color: #0d1117; padding: 20px; text-align: center; font-size: 12px; color: #8b949e; border-top: 1px solid #30363d;">
                <p style="margin: 0 0 8px 0;">本郵件由 GitHub Actions 雲端容器自動爬網、7 天去重與繁體中文翻譯生成，電腦未開機亦準時發送。</p>
            </div>
        </div>
    </body>
    </html>
    """
    return html


def _attempt_smtp_send(server_host, port, use_ssl, sender, password, recipients, msg_str):
    """
    單次 SMTP 寄信嘗試。
    注意：Python 內建 smtplib.login() 在 AUTH PLAIN 收到 535 BadCredentials 後，
    Gmail 會直接關閉連線，而 smtplib.login() 接著嘗試 AUTH LOGIN 會拋出
    SMTPServerDisconnected("Connection unexpectedly closed") 掩蓋真正的 535 密碼錯誤。
    因此這裡直接使用 auth_plain 並明確捕獲 535，讓錯誤訊息一目了然。
    """
    if use_ssl:
        server = smtplib.SMTP_SSL(server_host, port, timeout=30)
    else:
        server = smtplib.SMTP(server_host, port, timeout=30)
    try:
        server.ehlo()
        if not use_ssl:
            server.starttls()
            server.ehlo()
        # 僅執行單次 AUTH PLAIN，避免 Gmail 在 535 後斷線被二次 AUTH LOGIN 蓋掉真正錯誤
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


def send_email(config, html_content, date_str):
    sender = config.get("sender_email", "").strip().replace('"', "").replace("'", "")
    recipient = config.get("recipient_email", "")
    # 移除應用程式密碼中間可能包含的空白字元
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
    msg.attach(MIMEText(html_content, "html", "utf-8"))
    msg_str = msg.as_string()

    server_host = config.get("smtp_server", "smtp.gmail.com")
    max_retries = int(os.environ.get("SMTP_MAX_RETRIES", "12"))
    base_delay = int(os.environ.get("SMTP_RETRY_DELAY", "15"))

    # 交替使用 465 (SSL) 與 587 (STARTTLS) 重試直到成功寄出為止
    endpoints = [(465, True), (587, False)]

    for attempt in range(1, max_retries + 1):
        port, use_ssl = endpoints[(attempt - 1) % len(endpoints)]
        proto_label = "SSL:465" if use_ssl else "STARTTLS:587"
        try:
            log(f"[SMTP] Sending attempt {attempt}/{max_retries} via {server_host} ({proto_label}) to {recipients}...")
            _attempt_smtp_send(server_host, port, use_ssl, sender, password, recipients, msg_str)
            log(f"[SUCCESS] Email sent successfully to {recipients} on attempt {attempt}!")
            return True
        except smtplib.SMTPAuthenticationError as auth_err:
            err_msg = auth_err.smtp_error.decode("utf-8", errors="ignore") if isinstance(auth_err.smtp_error, bytes) else str(auth_err.smtp_error)
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
    if len(candidates) < TOP_N * 2:
        log("Fetching weekly trending as supplemental pool for 7-day deduplication...")
        weekly = fetch_github_trending(since="weekly")
        existing = {r["full_name"] for r in candidates}
        for w in weekly:
            if w["full_name"] not in existing:
                candidates.append(w)

    if not candidates:
        log("No repositories crawled. Exiting.")
        sys.exit(1)

    log(f"Selecting top {TOP_N} repositories (filtering 7-day duplicates unless updated)...")
    repos = select_top_repos_with_dedup(candidates, history, date_str, top_n=TOP_N)
    log(f"Selected {len(repos)} repositories for {date_str}.")

    for i, repo in enumerate(repos):
        log(f"Translating ({i+1}/{len(repos)}): {repo['full_name']}...")
        repo["desc_zh"] = translate_to_zh_tw(repo["desc_en"])

    # Archive to folder
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

    html_content = build_html_report(repos, date_str)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    preview_path = os.path.join(script_dir, "preview.html")
    try:
        with open(preview_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        log(f"Saved HTML preview to: {preview_path}")
    except Exception:
        pass

    email_status = send_email(config, html_content, date_str)
    if email_status:
        save_history(history_file, history, repos, date_str)
        log("Job completed successfully.")
    else:
        log("Job completed without sending email.")
        sys.exit(1)


if __name__ == "__main__":
    main()
