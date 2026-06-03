"""无麦克风的链路自测：MiniMax LLM 流式 -> MiniMax TTS -> 本地 Whisper STT 回环。

不依赖麦克风：用 MiniMax TTS 合成一段中文音频当作“用户输入”，再用本地 Whisper
把它转回文字，从而验证 LLM + TTS + STT 三段是否都通。
"""

import sys
import time
import wave

try:  # Windows 控制台默认 GBK，强制 UTF-8 让中文不乱码
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np

from config import make_minimax_client, TTS_SAMPLE_RATE, REC_SAMPLE_RATE, STT_BACKEND
from pipeline import stream_reply
from tts import tts_stream
import stt


def _resample_to_int16(pcm_int16: np.ndarray, sr_in: int, sr_out: int) -> np.ndarray:
    """简单线性重采样（TTS 是 24kHz，Whisper 要 16kHz）。"""
    if sr_in == sr_out:
        return pcm_int16
    n_out = int(len(pcm_int16) * sr_out / sr_in)
    xp = np.linspace(0.0, 1.0, len(pcm_int16), endpoint=False)
    xq = np.linspace(0.0, 1.0, n_out, endpoint=False)
    return np.interp(xq, xp, pcm_int16.astype(np.float32)).astype(np.int16)


def test_llm():
    print("=== 1. MiniMax LLM 流式 ===")
    minimax = make_minimax_client()
    t0 = time.time()
    first = None
    reply = ""
    for chunk in stream_reply(minimax, [{"role": "user", "content": "用一句话介绍你自己"}]):
        if first is None:
            first = time.time()
        reply += chunk
        print(chunk, end="", flush=True)
    print()
    ttft = (first - t0) if first else -1
    print(f"   [首 token {ttft:.2f}s] 回复长度={len(reply)}\n")
    return reply


def test_tts() -> np.ndarray:
    print("=== 2. MiniMax TTS（流式 pcm_24000） ===")
    text = "你好，这是一个语音助手的链路测试。"
    t0 = time.time()
    firstc = None
    pcm = b""
    for chunk in tts_stream(text):
        if firstc is None:
            firstc = time.time()
        pcm += chunk
    ttfc = (firstc - t0) if firstc else -1
    audio = np.frombuffer(pcm, dtype=np.int16)
    print(f"   [首音频块 {ttfc:.2f}s] PCM 字节={len(pcm)}  采样点={len(audio)}")
    with wave.open("test_tts.wav", "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(TTS_SAMPLE_RATE)
        wf.writeframes(pcm)
    print("   已保存 test_tts.wav\n")
    return audio


def test_stt(tts_audio_24k: np.ndarray):
    print(f"=== 3. STT（后端={STT_BACKEND}，回环识别合成音频） ===")
    audio_16k = _resample_to_int16(tts_audio_24k, TTS_SAMPLE_RATE, REC_SAMPLE_RATE)
    t0 = time.time()
    text_back = stt.transcribe(audio_16k)
    print(f"   [{time.time() - t0:.2f}s] 识别结果：{text_back}\n")
    return text_back


if __name__ == "__main__":
    test_llm()
    audio = test_tts()
    test_stt(audio)
    print("链路自测完成。")
