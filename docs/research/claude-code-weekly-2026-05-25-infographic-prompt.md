# Claude Code 本週更新重點 — Infographic 生成 Prompt

> 配合 `claude-code-weekly-2026-05-25.md` 週報。手繪筆記風（sketchnote）、繁體中文、Top 8 重點。
> 用於文字生圖模型（建議：Gemini 3 圖像 / GPT-image / Seedream / Recraft 等對 CJK 文字較強者）。

---

## 一、主 Prompt（繁體中文，可直接貼上）

```text
一張直式手繪筆記風（sketchnote / doodle infographic）資訊圖表，主題是「Claude Code 本週更新重點」。
整體像用黑色細字筆加上少量螢光筆，在米白色紙上手繪而成：線條帶手感、略不工整，標題為手寫字體、
搭配緞帶橫幅，重點用手繪外框或對話泡泡框起來，重點之間以虛線箭頭串接，旁邊散布塗鴉小圖示。

配色：米白紙張背景；主線條墨黑；點綴暖橘、湖水藍、芥末黃三種螢光筆色，色塊帶不均勻塗抹感。
風格平面 2D、無寫實感、乾淨好讀。直式比例 2:3。所有文字必須是清晰可辨識的繁體中文。

版面結構：
- 最上方：手寫大標題「Claude Code 本週更新重點」配緞帶橫幅，下方小字副標
  「2026.05.13–05.23 ‧ 版本 2.1.133–2.1.150」。
- 主體：8 個編號重點，由上而下單欄流動排列，每項含「一個簡單線稿圖示 + 手寫小標 + 一行說明」。
- 第 3 項用紅色驚嘆號與紅色外框特別強調（標示為重大變更）。
- 最下方：一行手寫小字「完整週報見 docs/research」。

8 個重點內容（圖示 + 標題 + 說明）：
1. 〔儀表板螢幕圖示〕Agent View ── 用「claude agents」一個畫面看所有 session：執行中、等你、已完成
2. 〔標靶圖示〕/goal 指令 ── 設定完成條件，Claude 跨多輪持續工作直到達成
3. 〔紅色警示三角〕/simplify 改名 /code-review ── 重大變更：只回報 bug、不再自動改寫程式碼
4. 〔月亮圖示〕背景 session 強化 ── claude --bg、/resume 支援背景、pinned session 閒置不被砍
5. 〔齒輪圖示〕Hooks 讀得到 effort ── hook 與 Bash 指令可用 $CLAUDE_EFFORT 分流深掃或速掃
6. 〔扳手圖示〕Hook args exec form ── 直接啟動程式、不經 shell、路徑 placeholder 免加引號
7. 〔閃電圖示〕Fast mode 升級 ── 預設模型改用 Opus 4.7
8. 〔拼圖圖示〕新設定參數 ── worktree.baseRef、autoMode.hard_deny

風格關鍵字：hand-drawn sketchnote, doodle infographic, marker pen lettering,
warm cream paper texture, highlighter accent colors, flat 2D illustration,
clean readable traditional Chinese typography, no photorealism。
```

---

## 二、要渲染的文字內容（逐字，zh-TW）

> 若生圖工具支援「指定要渲染的文字」，把下列字串逐字貼入，避免模型自行造字。

- 大標題：`Claude Code 本週更新重點`
- 副標：`2026.05.13–05.23 ‧ 版本 2.1.133–2.1.150`
- 01 `Agent View` / `一個畫面看所有 session`
- 02 `/goal 指令` / `設完成條件，持續工作到達成`
- 03 `/simplify → /code-review` / `重大變更：只回報 bug，不再自動改碼`
- 04 `背景 session 強化` / `claude --bg、/resume、pinned session`
- 05 `Hooks 讀得到 effort` / `$CLAUDE_EFFORT 可分流深掃／速掃`
- 06 `Hook args exec form` / `直接啟動、不經 shell、路徑免引號`
- 07 `Fast mode 升級` / `預設模型改用 Opus 4.7`
- 08 `新設定參數` / `worktree.baseRef、autoMode.hard_deny`
- 頁尾：`完整週報見 docs/research`

---

## 三、英文版 Prompt（備用，給對英文指令解析較佳的模型）

```text
A vertical hand-drawn sketchnote-style infographic titled "Claude Code 本週更新重點"
(Claude Code weekly highlights). Drawn as if with a fine black pen plus a few highlighter
strokes on warm cream paper: slightly imperfect lines, hand-lettered headings on ribbon
banners, doodle icons, dotted connector arrows, key points enclosed in hand-drawn frames
or speech bubbles. Palette: cream paper background, black ink linework, accented with warm
orange, teal blue, and mustard yellow highlighter colors with uneven marker fill. Flat 2D,
no photorealism, clean and highly readable. Aspect ratio 2:3. All on-image text MUST be
crisp, legible Traditional Chinese.

Layout: top — hand-lettered title "Claude Code 本週更新重點" on a ribbon banner, with a
small subtitle "2026.05.13–05.23 ‧ 版本 2.1.133–2.1.150". Body — 8 numbered highlights
flowing top to bottom in a single column, each with a simple line-art icon, a hand-written
heading, and one explanatory line. Item 3 is emphasized with a red exclamation mark and red
frame (marked as a breaking change). Bottom — a small hand-written note "完整週報見 docs/research".

The 8 highlights (icon + heading + caption), render captions in Traditional Chinese:
1. dashboard screen icon — Agent View — 一個畫面看所有 session
2. target/bullseye icon — /goal 指令 — 設完成條件，持續工作到達成
3. red warning triangle — /simplify → /code-review — 重大變更：只回報 bug，不再自動改碼
4. crescent moon icon — 背景 session 強化 — claude --bg、/resume、pinned session
5. gear icon — Hooks 讀得到 effort — $CLAUDE_EFFORT 可分流深掃／速掃
6. wrench icon — Hook args exec form — 直接啟動、不經 shell、路徑免引號
7. lightning bolt icon — Fast mode 升級 — 預設模型改用 Opus 4.7
8. puzzle piece icon — 新設定參數 — worktree.baseRef、autoMode.hard_deny

Style keywords: hand-drawn sketchnote, doodle infographic, marker-pen hand-lettering,
warm cream paper texture, highlighter accents, flat 2D illustration, no photorealism.
```

---

## 四、使用建議

- **比例**：直式 `2:3`（或 `3:4`）最適合 8 項清單；若要投影片橫式可改 `16:9` 並排成雙欄。
- **中文渲染**：多數生圖模型對中文字仍易變形。優先選對 CJK 文字較強的模型（Gemini 3 圖像 /
  GPT-image / Seedream 4 / Recraft）。若文字仍亂碼，改用「先生圖無文字版面 → 再用 Canva/Figma
  補繁中文字」的兩段式做法，第二、三節的逐字內容可直接套用。
- **微調方向**：要更專業可把「手繪筆記風」換成第二節週報用的「簡潔企業風（淺色、扁平圖示）」；
  要更活潑可加重螢光筆塗抹與貼紙感。
- **驗證**：出圖後逐項核對 8 條文字與週報一致，特別是第 3 項（重大變更）不可漏掉紅色強調。
