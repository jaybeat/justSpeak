"""MiniMax TTS（T2A v2）流式语音合成。

调用 HTTP 流式接口，逐块解析 SSE（`data:` 行），把每个 hex 编码的 PCM 块
解码成原始字节 yield 出去（24kHz、单声道、int16），直接可喂给播放器。
国内直连，显式 trust_env=False 确保不会误走系统代理。
"""

import json

import httpx

from config import (
    MINIMAX_TTS_URL,
    MINIMAX_TTS_MODEL,
    MINIMAX_VOICE_ID,
    MINIMAX_API_KEY,
    TTS_SAMPLE_RATE,
)


def tts_stream(text: str):
    """流式合成，逐块 yield PCM bytes（24kHz, mono, int16）。"""
    body = {
        "model": MINIMAX_TTS_MODEL,
        "text": text,
        "stream": True,
        # 让服务端不要在最后再下发一次「整段聚合音频」，从源头避免重复
        "stream_options": {"exclude_aggregated_audio": True},
        "voice_setting": {"voice_id": MINIMAX_VOICE_ID, "speed": 1, "vol": 1, "pitch": 0},
        "audio_setting": {"sample_rate": TTS_SAMPLE_RATE, "format": "pcm", "channel": 1},
    }
    headers = {
        "Authorization": f"Bearer {MINIMAX_API_KEY}",
        "Content-Type": "application/json",
    }
    # trust_env=False：MiniMax 国内直连，绝不走系统代理
    with httpx.Client(timeout=60, trust_env=False) as client:
        with client.stream("POST", MINIMAX_TTS_URL, headers=headers, json=body) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if not line or not line.startswith("data:"):
                    continue
                payload = json.loads(line[5:].strip())
                data = payload.get("data") or {}
                # status==1 是增量块；status==2 是末尾的整段聚合块，会把整句音频
                # 再返回一次，必须丢弃，否则部分句子会被播放两遍。
                if data.get("status") != 1:
                    continue
                audio_hex = data.get("audio")
                if audio_hex:
                    yield bytes.fromhex(audio_hex)
