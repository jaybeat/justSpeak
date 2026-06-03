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


def stream_reply(minimax, messages):
    """调用 MiniMax（OpenAI 兼容）流式接口，逐段 yield 文本增量。"""
    stream = minimax.chat.completions.create(
        model=MINIMAX_MODEL,
        messages=messages,
        stream=True,
        temperature=0.7,
        max_tokens=1024,
    )
    for chunk in stream:
        if not chunk.choices:
            continue
        text = getattr(chunk.choices[0].delta, "content", None)
        if text:
            yield text


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


def speak_streaming(player, text_stream) -> str:
    """消费 LLM 文本流，按句送 MiniMax TTS，边播边收集完整回复并返回。"""
    sentence_queue: "queue.Queue" = queue.Queue()
    reply_parts = []

    def tts_worker():
        while True:
            sentence = sentence_queue.get()
            if sentence is None:
                return
            for pcm in tts_stream(sentence):
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
