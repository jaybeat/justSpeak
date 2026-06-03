# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Critical environment constraint

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

# No-mic end-to-end test: MiniMax LLM stream -> MiniMax TTS -> local Whisper STT round-trip.
# This is the primary verification harness (there are no unit tests).
./.venv/Scripts/python.exe test_chain.py

# Run the interactive assistant (multi-turn; Enter to start/stop recording, q to quit)
./.venv/Scripts/python.exe main.py

# Run the Chinese->English speech translation mode (speak Chinese, get idiomatic English spoken + shown)
./.venv/Scripts/python.exe translate.py
```

There is no build/lint step and no test framework — `test_chain.py` is how you confirm the
pipeline works without a microphone. The only path it does **not** cover is live mic capture
(`record_until_enter`), which needs an interactive human + mic.

## Architecture

A local low-latency voice assistant. Unlike the ElevenLabs+Claude cookbook it is modeled on,
**every cloud call is MiniMax** (LLM + TTS) and **STT is local** — because MiniMax has no ASR API
and the available ElevenLabs key was permission-restricted. All MiniMax calls are domestic
direct connections; **no proxy is involved anywhere**.

```
record_until_enter (16kHz int16)
  -> stt.transcribe         (local faster-whisper, CPU)
  -> stream_reply           (MiniMax LLM via openai SDK, stream=True)
  -> speak_streaming        (split into sentences, fan out to TTS)
       -> tts.tts_stream    (MiniMax T2A v2, httpx SSE, hex->PCM 24kHz)
       -> GaplessPlayer      (queue -> RawOutputStream write thread)
```

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
`pipeline.py`, and `WHISPER_MODEL` size in `.env` (STT is the slowest stage on CPU).

### Module roles

- `config.py` — loads `.env`, exposes `make_minimax_client()` (an `openai.OpenAI` pointed at the
  MiniMax OpenAI-compatible endpoint), and all model/voice/sample-rate constants. `REC_SAMPLE_RATE=16000`
  (Whisper input), `TTS_SAMPLE_RATE=24000` (MiniMax PCM output / playback).
- `stt.py` — lazily loads and caches a `faster_whisper.WhisperModel`; `transcribe(int16 ndarray)`.
- `tts.py` — `tts_stream(text)` POSTs to MiniMax `t2a_v2` with `stream:true`, parses `data:` SSE
  lines, and yields `bytes.fromhex(data.audio)`. Uses `httpx.Client(trust_env=False)` so it can
  never accidentally route through a system proxy.
- `audio_io.py` — `record_until_enter()` (returns int16 ndarray, or `None` if user quits) and
  `GaplessPlayer`.
- `pipeline.py` — glue: `transcribe`, `stream_reply`, `speak_streaming`.
- `main.py` — multi-turn loop holding `messages` history; forces UTF-8 stdout (Windows console is
  GBK and will otherwise garble Chinese); preloads the Whisper model at startup.

## Configuration

Copy `.env.example` to `.env` and fill `MINIMAX_API_KEY`. `.env` is gitignored — keep real keys
out of tracked files. Voice/model/whisper-size are all `.env`-tunable; `MINIMAX_VOICE_ID` selects
a MiniMax system voice (e.g. `female-shaonv`, `male-qn-qingse`).
