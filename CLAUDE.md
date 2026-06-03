# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Critical environment constraint

> Applies only to the **local Whisper** STT backend (`STT_BACKEND=local`). With the cloud
> STT backend (`STT_BACKEND=aliyun`), `faster-whisper`/`ctranslate2` is never imported, so the
> Anaconda DLL issue below does not arise.

This machine's Anaconda (`D:\anaconda3`) has broken native ML DLLs: `ctranslate2` (the faster-whisper backend) **access-violation segfaults at model load** under the Anaconda interpreter — even in a venv created *from* Anaconda (it inherits `home = D:\anaconda3`). `KMP_DUPLICATE_LIB_OK` and PATH stripping do **not** fix it.

- The venv **must** be built from a clean non-Anaconda Python. One is installed at
  `C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe`.
- Always invoke the project with `.\.venv\Scripts\python.exe` (PowerShell) / `./.venv/Scripts/python.exe` (bash) — **never** bare `python` (that resolves to Anaconda).
- After building a venv, sanity-check: `sys.base_prefix` must NOT contain "anaconda".
- `WHISPER_DEVICE=cpu` is required — there is no CUDA runtime (`auto`/`cuda` fails on missing `cublas64_12.dll`).

## Commands

```bash
# Build venv from the clean Python (NOT anaconda) — see constraint above
"$LOCALAPPDATA/Programs/Python/Python312/python.exe" -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements.txt

# No-mic end-to-end test: MiniMax LLM stream -> MiniMax TTS -> STT round-trip (whichever
# STT_BACKEND is active). This is the primary verification harness (there are no unit tests).
./.venv/Scripts/python.exe test_chain.py

# Run the interactive assistant (multi-turn; Enter to start/stop recording, q to quit)
./.venv/Scripts/python.exe main.py

# Run the Chinese->English speech translation mode (speak Chinese, get idiomatic English spoken + shown)
./.venv/Scripts/python.exe translate.py
```

### Web / PWA（按住说话的语音翻译，浏览器/手机）

```bash
# 1) 后端：FastAPI + WebSocket，复用桌面管线（在 voice_assistant/ 目录跑）
./.venv/Scripts/python.exe -m uvicorn server.app:app --host 0.0.0.0 --port 8000

# 2) 前端：React + Vite（dev 服务器把 /ws、/healthz 代理到后端 :8000）
cd web && npm install && npm run dev      # 桌面 http://localhost:5173
cd web && npm run build && npm run preview # 跑生产构建（Service Worker 仅在此生效）

# 后端无浏览器自测（仿 test_chain）：合成中文 -> WS -> 断言识别+译文+回流 PCM
./.venv/Scripts/python.exe test_ws.py
```

> 手机实测：浏览器麦克风（`getUserMedia`）只在 **HTTPS 或 localhost** 下可用。手机连电脑要走
> `https://局域网IP` 自签证书或临时隧道（cloudflared/ngrok）。iOS 安装态需在「按住」手势内解锁 AudioContext。

There is no build/lint step and no test framework — `test_chain.py` is how you confirm the
pipeline works without a microphone. The only path it does **not** cover is live mic capture
(`record_until_enter`), which needs an interactive human + mic.

## Architecture

A low-latency voice assistant. **LLM + TTS are always MiniMax**; **STT is a separate vendor**
(MiniMax still has no ASR API, and the available ElevenLabs key was permission-restricted). STT
is pluggable (see `stt.py`): `local` = offline faster-whisper on CPU, `aliyun` = Alibaba Cloud
Paraformer real-time ASR (the current default in `.env` — ~1.4s vs local Whisper's ~5s on CPU).
All MiniMax and DashScope calls are domestic direct connections; **no proxy is involved anywhere**.

```
record_until_enter (16kHz int16)
  -> stt.transcribe         (pluggable: local Whisper CPU  |  Aliyun Paraformer cloud)
  -> stream_reply           (MiniMax LLM via openai SDK, stream=True)
  -> speak_streaming        (split into sentences, fan out to TTS)
       -> tts.tts_stream    (MiniMax T2A v2, httpx SSE, hex->PCM 24kHz)
       -> GaplessPlayer      (queue -> RawOutputStream write thread)
```

> Roadmap: this repo is the server-side core for an upcoming **PWA** (browser mic capture +
> client-side VAD endpointing + streamed playback). The pluggable `STTBackend` and the streaming
> pipeline are designed to carry over to that client/server split.

### The low-latency design (the part that spans files)

The point of the code is **pipeline overlap** via two producer/consumer queues, so LLM
generation, TTS synthesis, and audio playback run concurrently instead of sequentially:

1. `pipeline.stream_reply` yields LLM text deltas as they arrive.
2. `pipeline.speak_streaming` accumulates deltas and `_flush_sentences` splits on sentence
   boundaries (`[。.!?！？\n]`, with a `_MAX_BUFFER=60`-char forced flush for long
   punctuation-less spans). Each complete sentence is pushed to `sentence_queue`.
3. A background **TTS worker thread** pulls sentences, calls `tts.tts_stream`, and feeds each
   decoded PCM chunk to the player. So sentence N is being synthesized while the LLM is still
   producing sentence N+1.
4. `audio_io.GaplessPlayer` is the second queue: a single long-lived `RawOutputStream` whose
   own thread does blocking `.write()` calls, giving gapless, back-pressured playback. It
   frame-aligns across chunk boundaries (`carry` for odd byte splits).

When editing latency behavior, the knobs are: the sentence-boundary regex / `_MAX_BUFFER` in
`pipeline.py`, and the STT backend (`STT_BACKEND` in `.env`). With `local`, STT is the slowest
stage on CPU and `WHISPER_MODEL` size is the main lever; with `aliyun` (cloud Paraformer) STT is
no longer the bottleneck.

### Module roles

- `config.py` — loads `.env`, exposes `make_minimax_client()` (an `openai.OpenAI` pointed at the
  MiniMax OpenAI-compatible endpoint), and all model/voice/sample-rate constants. `REC_SAMPLE_RATE=16000`
  (Whisper input), `TTS_SAMPLE_RATE=24000` (MiniMax PCM output / playback).
- `stt.py` — pluggable STT backends selected by `STT_BACKEND` (code default `local`; `.env` ships
  `aliyun`). `LocalWhisperBackend` lazily loads/caches a `faster_whisper.WhisperModel`.
  `AliyunParaformerBackend` streams the recorded clip (100ms PCM frames) to DashScope Paraformer
  real-time ASR and accumulates sentence-final text. Public facade `load_model()` /
  `transcribe(int16 ndarray)` is backend-agnostic. To add another cloud ASR (火山引擎 / 讯飞 /
  腾讯云): subclass `STTBackend`, register in `_BACKENDS` (mirror `AliyunParaformerBackend`);
  nothing else in the pipeline changes.
- `tts.py` — `tts_stream(text)` POSTs to MiniMax `t2a_v2` with `stream:true`, parses `data:` SSE
  lines, and yields `bytes.fromhex(data.audio)`. Uses `httpx.Client(trust_env=False)` so it can
  never accidentally route through a system proxy.
- `audio_io.py` — `record_until_enter()` (returns int16 ndarray, or `None` if user quits) and
  `GaplessPlayer`.
- `pipeline.py` — glue: `transcribe`, `stream_reply`, `speak_streaming`.
- `main.py` — multi-turn loop holding `messages` history; forces UTF-8 stdout (Windows console is
  GBK and will otherwise garble Chinese); preloads the active STT backend at startup.
- `translate_core.py` — `LANGS` + `build_messages()`（翻译系统提示/few-shot/音色），由 CLI
  `translate.py` 与 Web 后端共享，避免复制提示词。

### Web/PWA 分层（`server/` + `web/`）

第一阶段「按住说话」的语音翻译 PWA。**复用桌面管线，不重写业务逻辑**：

- `server/app.py` — FastAPI + WebSocket `/ws/translate`。协议：客户端发 `{"type":"start","lang"}`
  → 二进制 PCM16/16k 帧 → `{"type":"end"}`；后端转写→翻译→句级 TTS，把 PCM(24k) 二进制与
  识别/译文文本(JSON) 回推。关键桥接 `WebSocketSink`（`feed`/`finish` 鸭子类型）直接喂给
  `pipeline.speak_streaming`，连句级 TTS 重叠的低延迟一起复用，**未改 pipeline.py**。
- `web/` — React + Vite PWA。`src/audio.js`=采集(16k)/播放(24k) 两个 AudioWorklet（播放即
  `GaplessPlayer` 的浏览器版）；`src/session.js`=WS + 一个 turn 的起止，**`start()/end()` 是 VAD 接缝**
  （现由「按住」按钮调用，将来免提模式由 Silero VAD 的 `onSpeechStart/onSpeechEnd` 调同样两个方法）；
  `public/*-worklet.js`=两个 worklet 处理器；`public/sw.js`+`manifest.webmanifest`=可安装 PWA。
- `test_ws.py` — Web 后端的无浏览器自测（对应 CLI 的 `test_chain.py`）。

> 未做（已留接缝）：真·边说边转（后端把帧实时转发 Paraformer）、免提 VAD、WebRTC 传输。

## Configuration

Copy `.env.example` to `.env` and fill `MINIMAX_API_KEY` (always) plus `DASHSCOPE_API_KEY` (when
`STT_BACKEND=aliyun`). `.env` is gitignored — keep real keys out of tracked files. Voice / LLM
model / TTS model / STT backend / whisper-size are all `.env`-tunable; `MINIMAX_VOICE_ID` selects
a MiniMax system voice (e.g. `female-shaonv`, `male-qn-qingse`).
