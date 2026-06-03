"""配置加载与客户端构建。

整套技术栈都在 MiniMax（国内直连，无需代理）+ 本地 Whisper：
- LLM：MiniMax OpenAI 兼容接口，用 openai SDK。
- TTS：MiniMax T2A v2（HTTP 流式，返回 hex 编码 PCM）。
- STT：本地 faster-whisper，离线，无需任何 key。
"""

import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

# ---- MiniMax LLM ----
MINIMAX_BASE_URL = os.getenv("MINIMAX_BASE_URL", "https://api.minimaxi.com/v1")
MINIMAX_API_KEY = os.getenv("MINIMAX_API_KEY", "")
MINIMAX_MODEL = os.getenv("MINIMAX_MODEL", "MiniMax-Text-01")

# ---- MiniMax TTS（T2A v2）----
MINIMAX_TTS_URL = os.getenv("MINIMAX_TTS_URL", "https://api.minimaxi.com/v1/t2a_v2")
MINIMAX_TTS_MODEL = os.getenv("MINIMAX_TTS_MODEL", "speech-02-turbo")
MINIMAX_VOICE_ID = os.getenv("MINIMAX_VOICE_ID", "female-shaonv")

# ---- 本地 STT（faster-whisper）----
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu")      # cpu / cuda / auto（auto 需 CUDA 运行库）
WHISPER_COMPUTE = os.getenv("WHISPER_COMPUTE", "int8")   # int8(快/CPU) / float16(GPU) / default
WHISPER_LANGUAGE = os.getenv("WHISPER_LANGUAGE", "zh")

# ---- 音频参数 ----
REC_SAMPLE_RATE = 16000   # 录音采样率（Whisper 需要 16kHz）
TTS_SAMPLE_RATE = 24000   # MiniMax TTS pcm 输出采样率（用于播放）


def _require(name: str, value: str) -> None:
    if not value:
        raise RuntimeError(f"缺少配置 {name}，请在 voice_assistant/.env 中填写。")


def make_minimax_client() -> OpenAI:
    """LLM 客户端（国内直连，不走代理）。"""
    _require("MINIMAX_API_KEY", MINIMAX_API_KEY)
    return OpenAI(base_url=MINIMAX_BASE_URL, api_key=MINIMAX_API_KEY)
