"""后端 WS 端点自测（无浏览器、无麦克风）。

仿 test_chain.py 的思路验证 server/app.py 的 /ws/translate：
    用 MiniMax TTS 合成一段中文 PCM 当“用户按住说的话”，重采样到 16k，
    通过 Starlette TestClient 的 WebSocket 走一遍 start -> PCM 帧 -> end，
    断言收到：中文识别文本 + 译文文本 + 一段回流的 TTS PCM。

用 TestClient 在进程内跑 app（自动触发 startup 预加载），不需要单独起 uvicorn。
"""

import sys
import json

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np
from fastapi.testclient import TestClient

from config import TTS_SAMPLE_RATE, REC_SAMPLE_RATE
from tts import tts_stream
from server.app import app


def _synthesize_zh_16k(text: str) -> bytes:
    """用 MiniMax TTS 合成中文（24k），线性重采样到 16k int16，返回 PCM 字节。"""
    pcm24 = b"".join(tts_stream(text))
    a24 = np.frombuffer(pcm24, dtype=np.int16)
    n_out = int(len(a24) * REC_SAMPLE_RATE / TTS_SAMPLE_RATE)
    xp = np.linspace(0.0, 1.0, len(a24), endpoint=False)
    xq = np.linspace(0.0, 1.0, n_out, endpoint=False)
    a16 = np.interp(xq, xp, a24.astype(np.float32)).astype(np.int16)
    return a16.tobytes()


def main():
    print("=== 合成中文输入音频（MiniMax TTS -> 16k）===")
    pcm = _synthesize_zh_16k("你好，请问你们几点关门？")
    print(f"   输入 PCM 字节={len(pcm)}（16kHz int16）\n")

    print("=== 走 /ws/translate（lang=en）===")
    asr_text = None
    translation = None
    pcm_back = 0
    with TestClient(app) as client:               # 进入上下文会触发 startup 预加载 STT
        with client.websocket_connect("/ws/translate") as ws:
            ws.send_json({"type": "start", "lang": "en"})
            chunk = REC_SAMPLE_RATE * 2 // 10       # 100ms 一帧
            for i in range(0, len(pcm), chunk):
                ws.send_bytes(pcm[i:i + chunk])
            ws.send_json({"type": "end"})

            while True:
                m = ws.receive()
                if m.get("text") is not None:
                    d = json.loads(m["text"])
                    t = d.get("type")
                    if t == "asr":
                        asr_text = d["text"]
                        print(f"   识别中文：{asr_text}")
                    elif t == "translation":
                        translation = d["text"]
                        print(f"   译文(en)：{translation}")
                    elif t == "error":
                        print(f"   [错误] {d['text']}")
                        break
                    elif t == "turn_done":
                        break
                elif m.get("bytes") is not None:
                    pcm_back += len(m["bytes"])

    print(f"   回流 TTS PCM 字节={pcm_back}\n")

    ok = bool(asr_text and asr_text.strip()) and bool(translation and translation.strip()) and pcm_back > 0
    print("✅ WS 后端自测通过。" if ok else "❌ 自测未通过：缺少 识别/译文/音频 之一。")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
