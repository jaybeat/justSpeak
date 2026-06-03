"""PWA 后端：FastAPI + WebSocket 语音翻译端点。

复用现有桌面管线（stt / pipeline / tts / translate_core），不重写业务逻辑：
    浏览器按住说话 -> 经 WS 把 PCM16/16k 帧推上来 -> 松手发 {"type":"end"}
    -> stt.transcribe(阿里云) -> build_messages(lang) -> stream_reply(LLM 流式)
    -> 句级 tts_stream 合成 -> PCM(24k) 二进制回推，识别中文/译文文本以 JSON 回推。

关键桥接：管线里的 speak_streaming(player, ...) 靠 player.feed(pcm)/finish() 鸭子类型工作。
这里实现一个 WebSocketSink 当“player”，feed 改成把 PCM 通过 WS 发回浏览器，
从而连“句级 TTS 重叠”的低延迟特性一起复用，无需改动 pipeline.py。

运行（在 voice_assistant/ 目录下）：
    ./.venv/Scripts/python.exe -m uvicorn server.app:app --host 0.0.0.0 --port 8000
"""

import sys
import json
import asyncio

import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

try:  # Windows 控制台默认 GBK，强制 UTF-8 让中文不乱码
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from config import make_minimax_client
from pipeline import stream_reply, speak_streaming
from translate_core import LANGS, build_messages
import stt

app = FastAPI(title="justSpeak 语音翻译后端")

# LLM 客户端进程内复用；STT 后端在启动时预加载，避免第一句卡顿
_minimax = make_minimax_client()


@app.on_event("startup")
def _preload():
    stt.load_model()


@app.get("/healthz")
def healthz():
    return {"ok": True, "langs": list(LANGS)}


class WebSocketSink:
    """把同步管线的 PCM/文本输出桥接到异步 WebSocket。

    speak_streaming 在后台线程里调用 feed()/finish()；这里用 run_coroutine_threadsafe
    把发送动作调度回事件循环并阻塞等其完成，天然形成背压（发不出去就不继续合成）。
    """

    def __init__(self, ws: WebSocket, loop: asyncio.AbstractEventLoop):
        self._ws = ws
        self._loop = loop

    def _run(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result()

    def feed(self, pcm: bytes):  # 被 TTS worker 线程调用
        if pcm:
            self._run(self._ws.send_bytes(pcm))

    def finish(self):  # speak_streaming 末尾调用；流式发送无需服务端额外等待
        pass

    def send_json(self, obj):
        self._run(self._ws.send_json(obj))


def _process_turn(pcm_bytes: bytes, lang: str, sink: WebSocketSink):
    """一次完整的翻译 turn（阻塞，跑在线程里）：转写 -> 翻译流式 -> TTS 流式回推。"""
    audio = np.frombuffer(pcm_bytes, dtype=np.int16)
    zh_text = stt.transcribe(audio)
    sink.send_json({"type": "asr", "text": zh_text})
    if not zh_text.strip():
        sink.send_json({"type": "error", "text": "没听清，请再说一次。"})
        return

    messages = build_messages(zh_text, lang)
    voice = LANGS[lang]["voice"]

    def _tee_text(gen):
        # 译文边生成边推给浏览器显示，同时透传给 speak_streaming 去合成
        for delta in gen:
            sink.send_json({"type": "translation_delta", "text": delta})
            yield delta

    reply = speak_streaming(sink, _tee_text(stream_reply(_minimax, messages)), voice_id=voice)
    sink.send_json({"type": "translation", "text": reply})


@app.websocket("/ws/translate")
async def ws_translate(ws: WebSocket):
    await ws.accept()
    loop = asyncio.get_running_loop()
    sink = WebSocketSink(ws, loop)
    buf = bytearray()
    lang = "en"
    try:
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            if msg.get("bytes") is not None:        # 录音帧
                buf.extend(msg["bytes"])
            elif msg.get("text") is not None:        # 控制消息
                data = json.loads(msg["text"])
                kind = data.get("type")
                if kind == "start":
                    buf.clear()
                    lang = data.get("lang", "en")
                    if lang not in LANGS:
                        lang = "en"
                elif kind == "end":
                    pcm = bytes(buf)
                    buf.clear()
                    await asyncio.to_thread(_process_turn, pcm, lang, sink)
                    await ws.send_json({"type": "turn_done"})
    except WebSocketDisconnect:
        pass
