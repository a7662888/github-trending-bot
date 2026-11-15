"""Hugging Face 每日熱門（Agent 應用導向）：MCP Space、可呼叫工具的模型、Agent／醫學論文。

只用公開 API（免金鑰）；任何一段失敗都回傳空清單，不阻斷主報告寄送。
"""
import re
import datetime
import requests

HF_API = "https://huggingface.co/api"
HF_TOP_N = 5
TIMEOUT = 15

# 標題、標籤或描述命中即排除：無審查／去安全對齊模型、換臉與深偽、成人內容
BLOCK_RE = re.compile(
    r"uncensor|decensor|abliterat|heretic|nsfw|porn|nude|hentai|eros\b|10eros|"
    r"\bcum\b|\bsex|\bxxx\b|lewd|onlyfans|face[-_ ]?swap|deepfake|not-for-all-audiences",
    re.I,
)

# (標籤, 關鍵字 regex)；GitHub 與 HF 共用
AGENT_RULES = [
    ("🧩 技能包", r"\bskills?\b|skill\.md|agent skills"),
    ("🔌 MCP", r"\bmcp\b|model context protocol|mcp-server"),
    ("🕹️ Agent 框架", r"agent (framework|harness|toolkit|loop|workflow)|\bharness\b|multi-agent|agentic|orchestrat|autonomous agent|self-evolving agent"),
    ("🧠 記憶／Context", r"\bmemory\b|context (window|engineering|optimi)|persistent context|\brag\b|retrieval"),
    ("🌐 瀏覽器／電腦操作", r"browser|computer[- ]use|playwright|devtools|web automation|gui agent"),
    ("💻 寫程式代理", r"coding agent|claude code|\bcodex\b|\bcursor\b|\bcopilot\b|opencode|gemini cli"),
    ("🛠️ 工具呼叫", r"tool[- ]use|function[- ]calling|tool calling|\btools?\b.*\bagent"),
]
MED_RE = re.compile(
    r"medic|clinic|neuro|brain|\behr\b|radiolog|dementia|alzheimer|parkinson|stroke|"
    r"patholog|biomedic|health|patient|\bmri\b|\beeg\b",
    re.I,
)

# 論文須真的談 agent／工具呼叫／MCP（避免只因提到 memory、retrieval 就入選）
PAPER_GATE_RE = re.compile(r"\bagent|tool[- ]use|function[- ]calling|\bmcp\b", re.I)

PIPELINE_ZH = {
    "text-generation": "文字生成",
    "image-text-to-text": "圖文理解",
    "any-to-any": "多模態",
    "text-to-speech": "語音合成",
    "automatic-speech-recognition": "語音辨識",
    "text-to-image": "文生圖",
    "image-to-video": "圖生影片",
    "feature-extraction": "向量嵌入",
    "sentence-similarity": "向量嵌入",
}


def agent_tags(*texts):
    blob = " ".join(t for t in texts if t).lower()
    tags = [label for label, pat in AGENT_RULES if re.search(pat, blob, re.I)]
    if not tags and re.search(r"\bagents?\b", blob):
        tags.append("🤖 Agent 相關")
    if MED_RE.search(blob):
        tags.append("🩺 醫學／神經")
    return tags


def _get(path, params):
    try:
        r = requests.get(f"{HF_API}/{path}", params=params, timeout=TIMEOUT)
        if r.status_code == 200:
            return r.json()
        print(f"  [HF] {path} HTTP {r.status_code}", flush=True)
    except Exception as e:
        print(f"  [HF] {path} error: {e}", flush=True)
    return []


def _recent(key, history, today):
    prev = (history.get("records") or {}).get(key)
    if not prev:
        return False
    try:
        d = datetime.date.fromisoformat(str(prev.get("sent_date", ""))[:10])
        return today - datetime.timedelta(days=7) <= d < today
    except ValueError:
        return False


def _license(tags):
    lic = next((t.split(":", 1)[1] for t in tags if t.startswith("license:")), "")
    return lic or "未標示"


def _params_b(m):
    # 名稱標示優先：量化檔（NVFP4、GGUF）的 safetensors.total 是壓縮後元素數，會低估
    hit = re.search(r"(\d+(?:\.\d+)?)B(?![a-z])", m.get("id", "").split("/")[-1])
    if hit:
        return float(hit.group(1))
    total = (m.get("safetensors") or {}).get("total") or (m.get("gguf") or {}).get("total")
    return total / 1e9 if total else None


def fetch_spaces(history, today):
    data = _get("spaces", [("sort", "trendingScore"), ("direction", "-1"), ("limit", "100"),
                           ("expand[]", "cardData"), ("expand[]", "tags"),
                           ("expand[]", "likes"), ("expand[]", "trendingScore")])
    out, seen = [], set()
    for s in data:
        sid = s.get("id", "")
        card = s.get("cardData") or {}
        title = card.get("title") or sid
        desc = card.get("short_description") or ""
        tags = s.get("tags") or []
        if BLOCK_RE.search(" ".join([sid, title, desc] + tags)):
            continue
        atags = agent_tags(title, desc, " ".join(tags))
        if "🔌 MCP" not in atags and len(atags) < 2:
            continue
        family = re.split(r"[\s·:|\-]+", title.lower())[0]
        key = f"hf:space:{sid}"
        if family in seen or _recent(key, history, today):
            continue
        seen.add(family)
        out.append({
            "full_name": key, "kind": "space", "id": sid, "title": title, "desc_en": desc,
            "link": f"https://huggingface.co/spaces/{sid}", "likes": s.get("likes", 0),
            "trending": s.get("trendingScore", 0), "agent_tags": atags,
            "mcp": "mcp-server" in tags,
        })
        if len(out) >= HF_TOP_N:
            break
    return out


def fetch_models(history, today):
    data = _get("models", [("sort", "trendingScore"), ("direction", "-1"), ("limit", "100"),
                           ("expand[]", "tags"), ("expand[]", "likes"), ("expand[]", "pipeline_tag"),
                           ("expand[]", "trendingScore"), ("expand[]", "safetensors"),
                           ("expand[]", "gguf"), ("expand[]", "createdAt")])
    tagged, general, seen = [], [], set()
    for m in data:
        mid = m.get("id", "")
        tags = m.get("tags") or []
        if BLOCK_RE.search(" ".join([mid] + tags)):
            continue
        base = re.sub(r"[-_](gguf|nvfp4|fp8|awq|gptq|mlx|q\d\w*|\d+bit|bf16|int\d)\b.*$", "", mid.lower())
        key = f"hf:model:{mid}"
        if base in seen or _recent(key, history, today):
            continue
        pipe = m.get("pipeline_tag") or ""
        agentic = bool({"tool-use", "function-calling", "agent", "agentic"} & set(tags))
        chat_llm = "conversational" in tags and pipe in ("text-generation", "image-text-to-text", "")
        if not (agentic or chat_llm):
            continue
        p = _params_b(m)
        item = {
            "full_name": key, "kind": "model", "id": mid, "link": f"https://huggingface.co/{mid}",
            "pipeline": PIPELINE_ZH.get(pipe, pipe or "未標示"), "likes": m.get("likes", 0),
            "trending": m.get("trendingScore", 0), "license": _license(tags),
            "params": f"{p:.1f}B" if p else "未標示",
            # 6GB 顯示卡以 4-bit 量化約可載入 8B 以下；估計值，實際依 context 長度而定
            "local_hint": "≤8B，6GB 顯卡 4-bit 量化可試（估計）" if p and p <= 8 else "",
            "gguf": "gguf" in tags,
            "agent_tags": (["🛠️ 工具呼叫"] if agentic else ["💬 通用對話 LLM"]) + (["🩺 醫學／神經"] if MED_RE.search(mid) else []),
            "created_at": (m.get("createdAt") or "")[:10],
        }
        seen.add(base)
        (tagged if agentic else general).append(item)
    return (tagged + general)[:HF_TOP_N]


def fetch_papers(history, today):
    data = _get("daily_papers", [("limit", "100")])
    cutoff = (today - datetime.timedelta(days=3)).isoformat()
    picks = []
    for it in data:
        p = it.get("paper") or {}
        pid = p.get("id", "")
        day = str(p.get("submittedOnDailyAt") or it.get("publishedAt") or "")[:10]
        if day < cutoff:
            continue
        title = p.get("title") or it.get("title") or ""
        kws = p.get("ai_keywords") or []
        summary = p.get("ai_summary") or ""
        atags = agent_tags(title, summary, " ".join(kws))
        blob = f"{title} {summary} {' '.join(kws)}"
        if not (PAPER_GATE_RE.search(blob) or "🩺 醫學／神經" in atags):
            continue
        key = f"hf:paper:{pid}"
        if _recent(key, history, today):
            continue
        picks.append({
            "full_name": key, "kind": "paper", "id": pid, "title": title,
            "desc_en": summary or (p.get("summary") or "")[:300],
            "link": f"https://huggingface.co/papers/{pid}", "arxiv": f"https://arxiv.org/abs/{pid}",
            "upvotes": p.get("upvotes", 0), "agent_tags": atags, "date": day,
        })
    picks.sort(key=lambda x: x["upvotes"], reverse=True)
    return picks[:HF_TOP_N]


def fetch_hf_sections(history, today):
    return {
        "spaces": fetch_spaces(history, today),
        "models": fetch_models(history, today),
        "papers": fetch_papers(history, today),
    }


if __name__ == "__main__":
    # 自檢：命中規則、排除規則與實際抓取（需網路）
    assert "🔌 MCP" in agent_tags("Chrome DevTools MCP for coding agents")
    assert "💻 寫程式代理" in agent_tags("Skills for Claude Code")
    assert BLOCK_RE.search("Qwen-9B-UNCENSORED-heretic") and BLOCK_RE.search("best-face-swap")
    assert BLOCK_RE.search("Wan2.2 14B Cum explosion lora")
    assert not BLOCK_RE.search("Qwen/Qwen3.8-27B") and not BLOCK_RE.search("Sussex cohort")
    secs = fetch_hf_sections({"records": {}}, datetime.date.today())
    for k, v in secs.items():
        print(k, len(v))
        for x in v:
            print("  ", x["id"], x.get("agent_tags"), x.get("params", ""), x.get("upvotes", ""))
