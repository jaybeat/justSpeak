"""音频输入输出：麦克风录音 + 无缝（gapless）播放。

- record_until_enter(): 回车开始 / 再按回车结束，返回 16kHz 单声道 int16 的 numpy 数组
  （直接喂给本地 Whisper，无需写 WAV 文件）。
- GaplessPlayer: 单条 OutputStream + 后台写线程，按队列连续播放 PCM，实现无缝拼接。
"""

import time
import queue
import threading

import numpy as np
import sounddevice as sd

from config import REC_SAMPLE_RATE, TTS_SAMPLE_RATE


def record_until_enter(prompt=None, commands=()):
    """回车开始录音，再按回车结束。

    参数:
        prompt   -> 自定义开始提示文案（默认沿用原提示）
        commands -> 一组可识别的命令字符串（小写）；用户输入其一时不录音，直接把该命令冒泡返回

    返回:
        None        -> 用户在开始提示处输入 q，表示退出
        str         -> 用户输入了 commands 中的某个命令（如语言切换 "en"/"ja"），原样返回
        空 ndarray  -> 没有录到任何音频
        ndarray     -> 16kHz 单声道 int16 的一维数组
    """
    cmd = input(prompt or "\n▶ 回车开始录音（输入 q 退出）：")
    s = cmd.strip().lower()
    if s == "q":
        return None
    if s in commands:
        return s

    frames = []

    def callback(indata, frame_count, time_info, status):
        if status:
            print(f"[录音警告] {status}", flush=True)
        frames.append(indata.copy())

    stream = sd.InputStream(
        samplerate=REC_SAMPLE_RATE,
        channels=1,
        dtype="int16",
        callback=callback,
    )
    with stream:
        print("● 正在录音…… 再按回车结束。")
        input()  # 阻塞主线程，录音在 PortAudio 回调线程里进行

    if not frames:
        return np.empty(0, dtype=np.int16)

    return np.concatenate(frames, axis=0).reshape(-1)


class GaplessPlayer:
    """无缝播放队列。

    feed() 把 PCM 块入队；后台线程用阻塞式 RawOutputStream.write() 连续写出，
    write 本身提供背压，天然实现无缝、按序播放。
    """

    def __init__(self, sample_rate: int = TTS_SAMPLE_RATE):
        self.sample_rate = sample_rate
        self._queue: "queue.Queue[bytes | None]" = queue.Queue()
        self._stream = sd.RawOutputStream(
            samplerate=sample_rate,
            channels=1,
            dtype="int16",
        )
        self._stream.start()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        carry = b""  # 跨块残留的半个采样（保证写入长度是 2 的倍数）
        while True:
            chunk = self._queue.get()
            try:
                if chunk is None:
                    if carry:
                        self._stream.write(carry + b"\x00")
                        carry = b""
                    return
                data = carry + chunk
                aligned = len(data) - (len(data) % 2)
                carry = data[aligned:]
                if aligned:
                    self._stream.write(data[:aligned])
            finally:
                self._queue.task_done()

    def feed(self, pcm_bytes: bytes):
        if pcm_bytes:
            self._queue.put(pcm_bytes)

    def finish(self):
        """等待已入队的音频全部写出，并留出尾音播放时间。"""
        self._queue.join()
        time.sleep(0.3)

    def stop(self):
        self._queue.put(None)
        self._thread.join(timeout=2)
        self._stream.stop()
        self._stream.close()
