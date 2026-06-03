"""管线核心：本地 STT、MiniMax 流式 LLM、句子切分、MiniMax TTS worker。

低延迟关键 = 管线重叠：
    MiniMax LLM 流式吐字 -> 按句子边界切分 -> 每凑齐一句立刻丢给 TTS worker
    -> MiniMax T2A 流式合成 PCM -> 喂进 GaplessPlayer 播放队列。
LLM 还在生成后半段时，TTS / 播放已经在处理前半段，三段时间从“相加”变“重叠”。
"""

import re
import queue
import threading

from config import MINIMAX_MODEL
from tts import tts_stream
import stt as _stt

# 句子边界：中英文句号/问号/感叹号/换行
_SENTENCE_END = re.compile(r"[。.!?！？\n]")
# 无标点的长句兜底：累积超过这个字符数也强制 flush，避免迟迟不出声
_MAX_BUFFER = 60


def transcribe(audio_int16) -> str:
    """本地 faster-whisper 语音转文字。"""
    return _stt.transcribe(audio_int16)


def _strip_think(chunks):
    """流式剥离 `<think>...</think>` 思维链，逐段 yield 纯净文本。

    防御性兜底：推理模型（如 MiniMax-M3）在 OpenAI 兼容端点上可能把思考内联进
    content。标签可能被切在两个增量块之间，故用缓冲+状态机跨 chunk 处理，
    并保留可能构成标签前缀的尾部字符，避免把半个标签当正文吐出。
    """
    OPEN, CLOSE = "<think>", "</think>"
    buf, inside = "", False
    for c in chunks:
        buf += c
        while True:
            if not inside:
                i = buf.find(OPEN)
                if i == -1:
                    keep = len(OPEN) - 1  # 末尾可能是 "<think" 之类的前缀，先留着
                    if len(buf) > keep:
                        yield buf[:-keep]
                        buf = buf[-keep:]
                    break
                if i > 0:
                    yield buf[:i]
                buf, inside = buf[i + len(OPEN):], True
            else:
                j = buf.find(CLOSE)
                if j == -1:
                    keep = len(CLOSE) - 1
                    buf = buf[-keep:] if len(buf) > keep else buf
                    break
                buf, inside = buf[j + len(CLOSE):], False
    if buf and not inside:
        yield buf


def stream_reply(minimax, messages):
    """调用 MiniMax（OpenAI 兼容）流式接口，逐段 yield 纯净文本增量。

    extra_body 关闭 M3 思考（默认 adaptive）：翻译/口语对话无需深推理，关掉可消除
    `<think>` 泄漏、降低首字延迟与成本。再经 _strip_think 兜底，确保万一泄漏也不外泄。
    """
    stream = minimax.chat.completions.create(
        model=MINIMAX_MODEL,
        messages=messages,
        stream=True,
        temperature=0.7,
        max_tokens=1024,
        extra_body={"thinking": {"type": "disabled"}},
    )

    def _content_deltas():
        for chunk in stream:
            if not chunk.choices:
                continue
            text = getattr(chunk.choices[0].delta, "content", None)
            if text:
                yield text

    yield from _strip_think(_content_deltas())


def _flush_sentences(buffer: str, sentence_queue: "queue.Queue") -> str:
    """把 buffer 中的完整句子入队，返回剩余不完整片段。"""
    last_end = 0
    for m in _SENTENCE_END.finditer(buffer):
        sentence = buffer[last_end:m.end()].strip()
        if sentence:
            sentence_queue.put(sentence)
        last_end = m.end()

    remainder = buffer[last_end:]
    if len(remainder) >= _MAX_BUFFER:  # 长句无标点兜底
        chunk = remainder.strip()
        if chunk:
            sentence_queue.put(chunk)
        remainder = ""
    return remainder


def speak_streaming(player, text_stream, voice_id=None) -> str:
    """消费 LLM 文本流，按句送 MiniMax TTS，边播边收集完整回复并返回。

    voice_id 透传给 tts_stream；留空时用 config 默认音色（main.py 调用不变）。
    """
    sentence_queue: "queue.Queue" = queue.Queue()
    reply_parts = []

    def tts_worker():
        while True:
            sentence = sentence_queue.get()
            if sentence is None:
                return
            for pcm in tts_stream(sentence, voice_id):
                player.feed(pcm)

    worker = threading.Thread(target=tts_worker, daemon=True)
    worker.start()

    buffer = ""
    for text in text_stream:
        reply_parts.append(text)
        print(text, end="", flush=True)
        buffer += text
        buffer = _flush_sentences(buffer, sentence_queue)

    tail = buffer.strip()
    if tail:
        sentence_queue.put(tail)

    sentence_queue.put(None)  # 通知 worker 结束
    worker.join()             # 等所有句子都送进 TTS 并喂给 player
    player.finish()           # 等音频播完
    print()

    return "".join(reply_parts)
