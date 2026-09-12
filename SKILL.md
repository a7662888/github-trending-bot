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

## 📊 報表欄位（2026-09-12 增補）

除語言／今日新增／總星數外，另由 GitHub API 補三類欄位：

| 欄位 | 來源 | 為什麼需要 |
| :--- | :--- | :--- |
| **授權（SPDX）** | `/repos/{full_name}` → `license.spdx_id` | 對「把外部 repo 在地化進技能庫」的用法，**能不能用**先於值不值得用 |
| **Fork 數、Fork:Star 比** | 同上 | 比例低（如 1:5）代表真的被拿去改；比例高（如 1:18）偏收藏向，熱度未必等於可用性 |
| **建立日期** | 同上 `created_at` | 判斷成長曲線陡峭度，辨識短期衝星 |

### 授權分級（`classify_license()`）

| 顯示 | 意義 | 可否取用 |
| :--- | :--- | :--- |
| ✅ MIT / Apache-2.0 / BSD… | 寬鬆授權 | 可在地化取用 |
| ⚠️ GPL / AGPL / LGPL | copyleft | **僅可讀設計**；抄程式碼會讓衍生作品被迫同授權 |
| ⚠️ 自訂/未識別（`NOASSERTION`） | 偵測器比對不到 | **必須人工開 LICENSE 檔確認** |
| 🚫 無授權檔（`null`） | All rights reserved | 不得取用程式碼 |

> **`NOASSERTION` 不等於「沒有授權」。** 實案：`nashsu/llm_wiki` API 回 NOASSERTION，實際 LICENSE 檔是 GPL-3.0，只因檔頭加了自訂版權行導致比對失敗。看到這格一律手動開檔。

### API 額度

未授權為 60 req/hr，本服務單輪 15 筆無虞。設環境變數 `GITHUB_TOKEN` 可提高上限；API 失敗時該欄退回 `—`，不影響其餘報表產出。
