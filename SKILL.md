---
name: github-trending-daily
description: 每日爬取 GitHub 熱門專案，翻譯成繁體中文並寄送 Email 摘要
---

# 🚀 每日 GitHub 熱門 Repos 郵件服務 (github-trending-daily)

此技能提供每日抓取 GitHub Trending 頁面，翻譯專案描述為繁體中文，格式化為精美郵件並自動發送至指定電子信箱。

## 📁 檔案結構說明

本技能位於 `e:\OneDrive\Obsidian Vault\skills\github-trending-daily\`，包含：
1. **`SKILL.md`**：本說明文件。
2. **`config.json`**：設定檔，用於配置寄件人/收件人 Email 及 SMTP 密碼。
3. **`github_trending_daily.py`**：核心 Python 爬蟲、翻譯與寄信程式。
4. **`run_task.bat`**：供 Windows 排程器呼叫的執行檔。
5. **`register_scheduler.ps1`**：一鍵註冊 Windows 工作排程器任務的 PowerShell 腳本。

## ⚙️ 安裝與設定步驟

1. **設定金鑰與信箱**：
   打開 `config.json`，將其中的發信 SMTP 資訊以及收件人信箱填寫完畢。
   例如若使用 Gmail，需先至 Google 帳戶啟用「雙重驗證」，並申請一個「應用程式密碼 (App Password)」。

2. **註冊 Windows 工作排程器**：
   以系統管理員身分執行 `register_scheduler.ps1` 即可註冊每日排程。預設時間為每天早上 8:30。

3. **手動測試執行**：
   可以直接點擊執行 `run_task.bat` 或在終端機中執行：
   ```bash
   python github_trending_daily.py
   ```
