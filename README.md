# justSpeak · 按住说话的语音翻译

说**中文**，实时**朗读 + 显示**地道口语**英文 / 日文**。手机可装成 **PWA**「按住说话」，也有桌面命令行版。底层是一套**全程流式 + 管线重叠**的低延迟语音管线，两端复用。

```
按住说话(浏览器/麦克风) → STT 转写 → MiniMax 流式翻译(LLM) → 句级流式 TTS → 无缝播放 + 显示译文
```

## 技术栈

- **LLM**：MiniMax（`MiniMax-Text-01`，OpenAI 兼容接口，国内直连）——非推理模型，首字延迟低，适合实时语音。
- **TTS**：MiniMax T2A v2（`speech-2.8-turbo`，HTTP 流式、低延迟）。
- **STT（可插拔）**：默认 **阿里云百炼 Paraformer 实时 ASR**（云端、中文低延迟，需 `DASHSCOPE_API_KEY`）；
  可切换 **本地 `faster-whisper`**（离线、免 key）。见 `stt.py` 的 `STT_BACKEND`。
- **全程国内直连，不走代理。**

> 为什么 STT 用第三方：MiniMax **没有**语音识别(ASR)API，只有合成/克隆。所以 STT 用阿里云 Paraformer(云端)或本地 Whisper(离线)。

## 低延迟原理

MiniMax LLM 流式吐字 → 按中英文句子边界切分 → 每凑齐一句**立刻**送 TTS 流式合成 → PCM 块进播放队列连续播放。
**LLM 生成 / TTS 合成 / 音频播放三者重叠**，而非串行相加。桌面端是 `GaplessPlayer`，浏览器端是等价的 AudioWorklet 播放队列。

---

## 用法 A：PWA（手机 / 浏览器，按住说话）

`server/`（FastAPI + WebSocket）复用桌面管线，`web/`（React + Vite）是按住说话的 PWA 前端。

```bash
# 1) 后端(在 voice_assistant/ 目录)
./.venv/Scripts/python.exe -m uvicorn server.app:app --host 0.0.0.0 --port 8000

# 2) 前端(dev 服务器把 /ws、/healthz 代理到后端 :8000)
cd web && npm install && npm run dev        # 桌面 http://localhost:5173
# 跑生产构建(Service Worker / 可安装 PWA 仅在此生效)：
cd web && npm run build && npm run preview
```

- **按住**圆钮说中文、**松手**出翻译并朗读；可切「中→英 / 中→日」。首次按下时浏览器会请求麦克风权限。
- 后端无浏览器自测：`./.venv/Scripts/python.exe test_ws.py`。

> 📱 手机实测：浏览器麦克风(`getUserMedia`)只在 **HTTPS 或 localhost** 下可用。手机连电脑要走
> `https://局域网IP`(自签证书)或临时隧道(cloudflared / ngrok)。

## 用法 B：桌面命令行

```powershell
# 多轮语音对话助手：回车开始/结束录音，q 退出
.\.venv\Scripts\python.exe main.py

# 中译英 / 中译日 语音翻译：说中文，朗读+显示译文；录音提示处输入 en/ja 随时切换
.\.venv\Scripts\python.exe translate.py

# 无麦克风链路自测：MiniMax LLM → TTS → STT 回环
.\.venv\Scripts\python.exe test_chain.py
```

---

## 安装

```powershell
cd voice_assistant
$PY = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $PY -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

之后命令都用 `.\.venv\Scripts\python.exe`。前端另需 Node.js（`web/` 里 `npm install`）。

> ⚠️ 仅当使用**本地 Whisper**（`STT_BACKEND=local`）时：venv 必须用 python.org 的**干净 Python** 建，
> 不能用 anaconda（其 Intel DLL 会让 `ctranslate2` 加载即闪退）；且需 `WHISPER_DEVICE=cpu`（本机无 CUDA）。
> 用云端 STT（`aliyun`）则不导入 Whisper，无此约束。

## 配置（`.env`）

拷贝 `.env.example` 为 `.env`，按需填写：

| 变量 | 说明 |
| --- | --- |
| `MINIMAX_API_KEY` | MiniMax 密钥（LLM + TTS，必填） |
| `MINIMAX_MODEL` | LLM 模型（默认 `MiniMax-Text-01`） |
| `MINIMAX_TTS_MODEL` / `MINIMAX_VOICE_ID` | TTS 模型（默认 `speech-2.8-turbo`）、音色 |
| `MINIMAX_VOICE_ID_EN` / `MINIMAX_VOICE_ID_JA` | 翻译模式朗读英文 / 日文的音色 |
| `STT_BACKEND` | `aliyun`（默认，云端 Paraformer）/ `local`（本地 Whisper） |
| `DASHSCOPE_API_KEY` / `PARAFORMER_MODEL` | 阿里云百炼密钥、模型（`STT_BACKEND=aliyun` 时） |
| `WHISPER_MODEL` / `WHISPER_DEVICE` / `WHISPER_LANGUAGE` | 本地 Whisper 参数（`STT_BACKEND=local` 时） |
| `TARGET_LANG` | 翻译默认目标语言：`en` / `ja` |

> `.env` 已 gitignore，真实密钥不入库。

## 目录

- `server/` — FastAPI + WebSocket（`/ws/translate`），桥接现有管线给浏览器。
- `web/` — React + Vite PWA（采集/播放两个 AudioWorklet、按住说话、可安装）。
- `pipeline.py` / `stt.py` / `tts.py` / `config.py` / `translate_core.py` — 共享的低延迟管线与可插拔 STT。
- `main.py` / `translate.py` — 桌面命令行入口。

## Roadmap（已留接缝，未做）

- 真·边说边转（后端把音频帧实时转发 Paraformer）；
- 免提对话模式（浏览器端 Silero VAD 自动断句，复用同一套 turn 起止）；
- 弱网下更稳的 WebRTC 传输。
