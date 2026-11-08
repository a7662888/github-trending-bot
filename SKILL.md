---
name: github-trending-daily
description: 每日爬取 GitHub 熱門專案 Top 10（7 天內不重複、有更新再推送），翻譯成繁體中文並寄送 Email 摘要
---

# 🚀 每日 GitHub 熱門 Repos 郵件服務 (github-trending-daily)

此技能提供每日上午 **06:43**（台灣時間）透過 GitHub Actions 雲端自動抓取 GitHub Trending 頁面 Top 10 專案，具備 **7 天內不重複篩選（若有新 Release、說明更新或星數暴增則重新推送）**、繁體中文翻譯、SPDX 授權分級與 SMTP 自動重試發信（465 SSL / 587 STARTTLS 雙通道退避重試）。

## 📁 檔案結構與雲端倉庫

- **本機正典路徑**：`D:\secondbrain\Skills\github-trending-daily\`
- **雲端 GitHub 倉庫**：`https://github.com/a7662888/github-trending-bot`
- **主要檔案**：
  1. **`SKILL.md`**：本說明文件。
  2. **`github_trending_daily.py`**：核心 Python 爬蟲、7 天去重、更新偵測、繁中翻譯與 SMTP 重試寄信程式。
  3. **`history.json`**：紀錄最近 30 天已寄送過的專案、星數與 Release 版本，供 7 天去重與更新比對使用。
  4. **`.github/workflows/daily_trending.yml`**：GitHub Actions 每日排程（UTC 22:43 = 台灣時間 06:43，電腦未開機照常執行）。
  5. **`archive/`**：每日產生的 Markdown 歷史歸檔報告。

## ⚙️ GitHub Secrets 設定（`a7662888/github-trending-bot`）

| Secret 名稱 | 用途 |
| :--- | :--- |
| `SENDER_EMAIL` | 寄件 Gmail 信箱（`a7662888@gmail.com`） |
| `SMTP_PASSWORD` | Google 帳戶兩步驟驗證下的 **16 位應用程式密碼（App Password）** |
| `RECIPIENT_EMAIL` | 收件人信箱（預設包含 `a7662888@gmail.com`） |

> ⚠️ **注意（2026-10-27 斷信原因紀錄）**：當 Google 帳號變更主密碼或安全性設定時，Google 會自動撤銷舊的應用程式密碼。此時 Gmail SMTP 在 `AUTH PLAIN` 回傳 `535-5.7.8 Username and Password not accepted` 後會立刻斷開連線，舊版 `smtplib.login()` 嘗試二次 `AUTH LOGIN` 時會拋出 `SMTPServerDisconnected: Connection unexpectedly closed` 掩蓋真正的 `535` 錯誤。新版已改為單次 `AUTH PLAIN` 明確捕捉 `535` 並支援 465/587 交替重試。

## 📊 報表欄位

除語言／今日新增／總星數外，另由 GitHub API 補三類欄位：

| 欄位 | 來源 | 為什麼需要 |
| :--- | :--- | :--- |
| **授權（SPDX）** | `/repos/{full_name}` → `license.spdx_id` | 對「把外部 repo 在地化進技能庫」的用法，**能不能用**先於值不值得用 |
| **Fork 數、Fork:Star 比** | 同上 | 比例低（如 1:5）代表真的被拿去改；比例高（如 1:18）偏收藏向，熱度未必等於可用性 |
| **建立日期與最新版本** | 同上 `created_at`、`/releases/latest` | 判斷成長曲線陡峭度與是否發布新版本 |

### 授權分級（`classify_license()`）

| 顯示 | 意義 | 可否取用 |
| :--- | :--- | :--- |
| ✅ MIT / Apache-2.0 / BSD… | 寬鬆授權 | 可在地化取用 |
| ⚠️ GPL / AGPL / LGPL | copyleft | **僅可讀設計**；抄程式碼會讓衍生作品被迫同授權 |
| ⚠️ 自訂/未識別（`NOASSERTION`） | 偵測器比對不到 | **必須人工開 LICENSE 檔確認** |
| 🚫 無授權檔（`null`） | All rights reserved | 不得取用程式碼 |
