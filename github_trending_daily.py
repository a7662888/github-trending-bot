import os
import sys
import json
import datetime
import urllib.parse
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import requests
from bs4 import BeautifulSoup

def load_config():
    # Detect environment variables first (supplied by GitHub Secrets/Actions)
    env_config = {}
    if os.environ.get("SENDER_EMAIL"):
        env_config["sender_email"] = os.environ.get("SENDER_EMAIL")
    if os.environ.get("SMTP_PASSWORD"):
        env_config["smtp_password"] = os.environ.get("SMTP_PASSWORD")
    if os.environ.get("RECIPIENT_EMAIL"):
        env_config["recipient_email"] = os.environ.get("RECIPIENT_EMAIL")
    
    # If running in GitHub Actions, set archive_dir to relative "archive" folder
    if os.environ.get("GITHUB_ACTIONS") == "true":
        env_config["archive_dir"] = "archive"
        env_config["smtp_server"] = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
        env_config["smtp_port"] = int(os.environ.get("SMTP_PORT", 465))
        return env_config
        
    # Local fallback
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, "config.json")
    local_config = {}
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                local_config = json.load(f)
        except Exception as e:
            print(f"Error loading local config: {e}")
            
    # Merge environment variables over local config
    config = {
        "smtp_server": "smtp.gmail.com",
        "smtp_port": 465,
        "sender_email": "your-email@gmail.com",
        "smtp_password": "your-gmail-app-password",
        "recipient_email": "a7662888@gmail.com",
        "archive_dir": "e:\\OneDrive\\Obsidian Vault\\github-trending-archive"
    }
    config.update(local_config)
    config.update(env_config)
    return config

def translate_to_zh_tw(text):
    if not text or text == "No description":
        return "無專案描述"
    
    url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl=zh-TW&dt=t&q={urllib.parse.quote(text)}"
    try:
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            result = res.json()
            translated_parts = [part[0] for part in result[0] if part and part[0]]
            return "".join(translated_parts)
    except Exception as e:
        print(f"Translation error: {e}")
    return text

def fetch_github_trending():
    url = "https://github.com/trending"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code != 200:
            print(f"Failed to fetch GitHub trending, status code: {response.status_code}")
            return []
    except Exception as e:
        print(f"Request error while fetching GitHub trending: {e}")
        return []
        
    soup = BeautifulSoup(response.text, 'html.parser')
    articles = soup.find_all('article', class_='Box-row')
    repos = []
    
    for article in articles:
        h2 = article.find('h2')
        if not h2:
            continue
        a = h2.find('a')
        if not a:
            continue
            
        href = a.get('href', '')
        repo_link = f"https://github.com/{href.lstrip('/')}"
        repo_name = a.text.strip().replace('\n', '').replace(' ', '')
        
        parts = repo_name.split('/')
        if len(parts) == 2:
            owner, name = parts[0], parts[1]
        else:
            owner, name = "", repo_name
            
        p = article.find('p')
        description_en = p.text.strip() if p else "No description"
        
        lang_span = article.find('span', itemprop='programmingLanguage')
        lang = lang_span.text.strip() if lang_span else "N/A"
        
        stars_today_el = article.find(lambda tag: tag.name == 'span' and 'stars' in tag.text)
        stars_today = stars_today_el.text.strip() if stars_today_el else "N/A"
        stars_today_cleaned = stars_today.replace("stars today", "").replace("stars this week", "").replace("stars this month", "").strip()
        
        stars_total_el = article.find('a', href=lambda h: h and h.endswith('/stargazers'))
        stars_total = stars_total_el.text.strip() if stars_total_el else "N/A"
        
        forks_el = article.find('a', href=lambda h: h and h.endswith('/forks'))
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
            "forks": forks
        })
        
    return repos

def build_markdown_report(repos, date_str):
    md = f"""---
title: "GitHub 每日熱門專案 [{date_str}]"
tags:
  - github
  - trending
  - ai-generated
date: {date_str}
---

# 🚀 GitHub 每日熱門專案報告 ({date_str})

| 專案名稱 (連結) | 開發語言 | 本日新增星星 | 總星星數 | 繁體中文專案摘要 |
| :--- | :---: | :---: | :---: | :--- |
"""
    for repo in repos:
        md += f"| [{repo['full_name']}]({repo['link']}) | `{repo['lang']}` | `+{repo['stars_today']}` | `{repo['stars_total']}` | {repo['desc_zh']} |\n"
        
    md += "\n\n---\n*本報告由 Python 爬蟲與 Google 翻譯 API 自動產生並歸檔。*"
    return md

def build_html_report(repos, date_str):
    rows_html = ""
    for idx, repo in enumerate(repos):
        bg_color = "#1e222b" if idx % 2 == 0 else "#161b22"
        lang_color = "#6f42c1"
        if repo['lang'] == "Python": lang_color = "#3572A5"
        elif repo['lang'] in ["JavaScript", "TypeScript"]: lang_color = "#f1e05a" if repo['lang'] == "JavaScript" else "#3178c6"
        elif repo['lang'] == "Go": lang_color = "#00ADD8"
        elif repo['lang'] == "Rust": lang_color = "#dea584"
        elif repo['lang'] == "C++": lang_color = "#f34b7d"
        elif repo['lang'] == "Swift": lang_color = "#f05138"
        elif repo['lang'] == "HTML": lang_color = "#e34c26"
        elif repo['lang'] == "CSS": lang_color = "#563d7c"
        
        text_color = "#000" if repo['lang'] == "JavaScript" else "#fff"
        
        rows_html += f"""
        <tr style="background-color: {bg_color}; border-bottom: 1px solid #30363d;">
            <td style="padding: 16px; vertical-align: top;">
                <div style="font-weight: bold; font-size: 16px; margin-bottom: 6px;">
                    <a href="{repo['link']}" style="color: #58a6ff; text-decoration: none; hover: underline;">{repo['full_name']}</a>
                </div>
                <div style="font-size: 14px; color: #c9d1d9; line-height: 1.5;">{repo['desc_zh']}</div>
                <div style="font-size: 12px; color: #8b949e; margin-top: 4px; font-style: italic;">Original: {repo['desc_en']}</div>
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
        </tr>
        """
        
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>GitHub 每日熱門專案報告</title>
    </head>
    <body style="background-color: #0d1117; color: #c9d1d9; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif; margin: 0; padding: 20px;">
        <div style="max-width: 900px; margin: 0 auto; background-color: #161b22; border: 1px solid #30363d; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 12px rgba(0,0,0,0.5);">
            <div style="background: linear-gradient(135deg, #1f6feb 0%, #0d1117 100%); padding: 30px 20px; text-align: center; border-bottom: 1px solid #30363d;">
                <h1 style="color: #ffffff; margin: 0; font-size: 26px; letter-spacing: 1px;">🚀 GitHub 每日熱門專案報告</h1>
                <p style="color: #8b949e; margin: 10px 0 0 0; font-size: 14px;">資料日期: {date_str} (每日早晨自動推送)</p>
            </div>
            
            <div style="overflow-x: auto;">
                <table style="width: 100%; border-collapse: collapse; text-align: left;">
                    <thead>
                        <tr style="background-color: #161b22; border-bottom: 2px solid #30363d; color: #8b949e; font-size: 13px; text-transform: uppercase;">
                            <th style="padding: 12px 16px;">Repository 專案資訊</th>
                            <th style="padding: 12px 16px; text-align: center;">主要語言</th>
                            <th style="padding: 12px 16px; text-align: center;">今日新增</th>
                            <th style="padding: 12px 16px; text-align: center;">總星星數</th>
                        </tr>
                    </thead>
                    <tbody>
                        {rows_html}
                    </tbody>
                </table>
            </div>
            
            <div style="background-color: #0d1117; padding: 20px; text-align: center; font-size: 12px; color: #8b949e; border-top: 1px solid #30363d;">
                <p style="margin: 0 0 8px 0;">本郵件由 GitHub Actions 雲端容器自動爬網與翻譯生成，每日早上定時發送。</p>
            </div>
        </div>
    </body>
    </html>
    """
    return html

def send_email(config, html_content, date_str):
    sender = config.get("sender_email")
    recipient = config.get("recipient_email")
    password = config.get("smtp_password")
    
    if not sender or not password or sender == "your-email@gmail.com":
        print("[WARNING] Email credentials not configured. Skipping email sending.")
        return False
        
    msg = MIMEMultipart('alternative')
    msg['Subject'] = f"🚀 GitHub 每日熱門專案報告 [{date_str}]"
    msg['From'] = f"GitHub Trending Robot <{sender}>"
    msg['To'] = recipient
    
    msg.attach(MIMEText(html_content, 'html'))
    
    try:
        port = config.get("smtp_port", 465)
        server_host = config.get("smtp_server", "smtp.gmail.com")
        
        if port == 465:
            server = smtplib.SMTP_SSL(server_host, port, timeout=20)
        else:
            server = smtplib.SMTP(server_host, port, timeout=20)
            server.starttls()
            
        server.login(sender, password)
        server.sendmail(sender, [recipient], msg.as_string())
        server.quit()
        print("Email sent successfully!")
        return True
    except Exception as e:
        print(f"Failed to send email: {e}")
        return False

def main():
    print(f"Starting GitHub Trending Daily Service - {datetime.datetime.now()}")
    
    config = load_config()
    if not config:
        print("No valid configuration found. Exiting.")
        sys.exit(1)
        
    print("Fetching GitHub trending repositories...")
    repos = fetch_github_trending()
    if not repos:
        print("No repositories crawled. Exiting.")
        sys.exit(1)
        
    repos = repos[:15]
    print(f"Processing top {len(repos)} repositories...")
    
    for i, repo in enumerate(repos):
        print(f"Translating ({i+1}/{len(repos)}): {repo['full_name']}...")
        repo['desc_zh'] = translate_to_zh_tw(repo['desc_en'])
        
    date_str = datetime.date.today().strftime("%Y-%m-%d")
    
    # Archive to folder
    archive_dir = config.get("archive_dir")
    if archive_dir:
        try:
            os.makedirs(archive_dir, exist_ok=True)
            archive_path = os.path.join(archive_dir, f"github-trending-{date_str}.md")
            md_content = build_markdown_report(repos, date_str)
            with open(archive_path, "w", encoding="utf-8") as f:
                f.write(md_content)
            print(f"Archived report: {archive_path}")
        except Exception as e:
            print(f"Failed to archive: {e}")
            
    html_content = build_html_report(repos, date_str)
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    preview_path = os.path.join(script_dir, "preview.html")
    try:
        with open(preview_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        print(f"Saved HTML preview to: {preview_path}")
    except Exception as e:
        pass
        
    email_status = send_email(config, html_content, date_str)
    if email_status:
        print("Job completed successfully.")
    else:
        print("Job completed without sending email.")
        sys.exit(1)

if __name__ == "__main__":
    main()
