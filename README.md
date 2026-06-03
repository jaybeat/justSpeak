# 本地低延迟语音助手（MiniMax + 本地 Whisper）

参考 [ElevenLabs + Claude cookbook](https://platform.claude.com/cookbook/third-party-elevenlabs-low-latency-stt-claude-tts) 的**全程流式 + 管线重叠**低延迟思路，把整套栈落到 **MiniMax + 本地 Whisper**：

```
回车录音 → 本地 Whisper(STT) → MiniMax 流式(LLM) → 句级流式 MiniMax(TTS) → 无缝播放
```

- **LLM**：MiniMax（OpenAI 兼容接口，用 `openai` SDK，国内直连）
- **TTS**：MiniMax T2A v2（HTTP 流式，返回 hex 编码 PCM，国内直连）
- **STT**：本地 `faster-whisper`（离线、无需任何 key、支持中文）
- **不需要代理**：全部国内直连或本地。

> 为什么 STT 用本地 Whisper：MiniMax **没有**语音识别（ASR）API，只有合成/克隆。
> ElevenLabs 又因 key 权限不可用，所以 STT 用本地 Whisper，既离线又免 key。

## 低延迟原理

MiniMax LLM 流式吐字 → 正则按中英文句子边界切分 → 每凑齐一句立刻送 MiniMax TTS
流式合成 → PCM 块进 `GaplessPlayer` 播放队列被单条 `OutputStream` 连续播放。
**LLM 生成 / TTS 合成 / 音频播放三者重叠**，而非串行相加。

## 1. 安装（必须用「非 anaconda」的干净 Python 建 venv）

> ⚠️ 重要：本机 anaconda 的 Intel DLL 会让 `ctranslate2`（Whisper 后端）**加载即闪退**
> （access violation）。所以 venv 必须用 python.org 的干净 Python 来建，**不能**用 anaconda 的。
> 本项目已用 winget 安装了 `Python 3.12.10` 到
> `C:\Users\Administrator\AppData\Local\Programs\Python\Python312\`。

```powershell
cd voice_assistant
$PY = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $PY -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

之后所有命令都用 `.\.venv\Scripts\python.exe` 运行（不要用 `python`，那是 anaconda 的）。

> STT 默认跑 **CPU**（`WHISPER_DEVICE=cpu`）。本机没有 CUDA 运行库，设 `auto`/`cuda` 会因
> 缺 `cublas64_12.dll` 报错。有正确 CUDA 环境时再改回 `cuda`。

## 2. 配置

`.env` 已就绪（MiniMax key 已填）。可按需调整：

| 变量 | 说明 |
| --- | --- |
| `MINIMAX_BASE_URL` / `MINIMAX_API_KEY` / `MINIMAX_MODEL` | LLM 接口、密钥、模型名 |
| `MINIMAX_TTS_URL` / `MINIMAX_TTS_MODEL` / `MINIMAX_VOICE_ID` | TTS 接口、模型（`speech-02-turbo`）、音色 |
| `WHISPER_MODEL` | `tiny`/`base`/`small`/`medium`/`large-v3`，越大越准越慢（默认 `small`） |
| `WHISPER_DEVICE` | `auto`/`cpu`/`cuda` |
| `WHISPER_COMPUTE` | `int8`(CPU 快) / `float16`(GPU) / `default` |
| `WHISPER_LANGUAGE` | 默认 `zh` |

## 3. 链路自测（无需麦克风）

```powershell
.\.venv\Scripts\python.exe test_chain.py
```

依次验证：MiniMax LLM 流式 → MiniMax TTS（存为 `test_tts.wav`）→ 本地 Whisper 把合成音频转回文字。
首次会下载 Whisper 模型（`small` 约 460MB）。

## 4. 运行

```powershell
.\.venv\Scripts\python.exe main.py
```

- **回车**开始录音 → 说话 → 再按**回车**结束。
- 终端打印识别文本和 MiniMax 流式回复，扬声器在 LLM 没说完时就开始播放。
- 在「回车开始录音」提示处输入 **q** 退出。

## 5. 常见问题

- **第一轮慢**：首次加载/下载 Whisper 模型；`main.py` 已在启动时预加载。想更快可把 `WHISPER_MODEL` 调小（如 `base`）。
- **识别不准**：把 `WHISPER_MODEL` 调大（`medium`/`large-v3`），或确认录音设备正常（`python -m sounddevice`）。
- **MiniMax 连不上**：核对 `MINIMAX_BASE_URL` / `MINIMAX_MODEL` 和 key。
- **换音色**：改 `MINIMAX_VOICE_ID`（如 `male-qn-qingse`、`female-shaonv` 等 MiniMax 系统音色）。
