"""语音识别（STT）—— 可插拔后端。

默认后端 `local`：本地 faster-whisper，离线、免费、无需任何 key（见 LocalWhisperBackend）。
通过 .env 的 STT_BACKEND 选择后端；想接云 ASR 时，照 _CloudBackendTemplate 写一个类、
在 _BACKENDS 注册即可，管线其余部分（pipeline.transcribe / main.py / translate.py）无需改动。

对外接口（被 main.py / translate.py / pipeline.py / test_chain.py 使用，保持不变）：
    load_model()                      预加载/初始化当前后端，避免首句卡顿
    transcribe(audio_int16) -> str    16kHz 单声道 int16 ndarray -> 识别文本
"""

import numpy as np

from config import (
    STT_BACKEND,
    WHISPER_MODEL,
    WHISPER_DEVICE,
    WHISPER_COMPUTE,
    WHISPER_LANGUAGE,
    REC_SAMPLE_RATE,
    DASHSCOPE_API_KEY,
    PARAFORMER_MODEL,
)


class STTBackend:
    """STT 后端接口。新后端继承它，实现 load()（可选）与 transcribe()。"""

    def load(self) -> None:
        """可选：预加载模型 / 建立连接，避免第一句卡顿。默认无操作。"""

    def transcribe(self, audio_int16: np.ndarray) -> str:
        raise NotImplementedError


class LocalWhisperBackend(STTBackend):
    """本地 faster-whisper：离线、免费、无需任何 key（默认后端）。"""

    def __init__(self):
        self._model = None

    def load(self):
        if self._model is None:
            from faster_whisper import WhisperModel  # 延迟导入，加快无 STT 场景启动
            print(f"[STT] 加载 faster-whisper 模型「{WHISPER_MODEL}」"
                  f"（device={WHISPER_DEVICE}, compute={WHISPER_COMPUTE}）；首次会下载权重…")
            self._model = WhisperModel(
                WHISPER_MODEL, device=WHISPER_DEVICE, compute_type=WHISPER_COMPUTE
            )
            print("[STT] 模型就绪。")
        return self._model

    def transcribe(self, audio_int16):
        if audio_int16 is None or len(audio_int16) == 0:
            return ""
        model = self.load()
        audio = audio_int16.astype(np.float32) / 32768.0
        segments, _info = model.transcribe(audio, language=WHISPER_LANGUAGE, beam_size=5)
        return "".join(seg.text for seg in segments).strip()


class AliyunParaformerBackend(STTBackend):
    """阿里云百炼 Paraformer 实时 ASR：中文、低延迟、国内直连，需 DASHSCOPE_API_KEY。

    交互模式不变（整段录完再转写）：把整段 16kHz int16 PCM 按 100ms 分帧喂进流式
    Recognition，仅在句子终态时累积文本。后续 PWA 阶段可把它升级为真·边说边转。

    其它云 ASR（火山引擎 seed-asr / 讯飞 RTASR / 腾讯云）照此类再写一个并在 _BACKENDS
    登记即可，管线其余部分（录音、pipeline、TTS、播放）无需任何改动。
    """

    _CHUNK = REC_SAMPLE_RATE * 2 // 10  # 100ms @ 16kHz mono int16 = 3200 字节

    def load(self):
        if not DASHSCOPE_API_KEY:
            raise RuntimeError(
                "缺少 DASHSCOPE_API_KEY，请在 voice_assistant/.env 填写，"
                "或把 STT_BACKEND 设回 local 使用本地 Whisper。"
            )
        import dashscope  # 延迟导入，加快无云 STT 场景启动
        dashscope.api_key = DASHSCOPE_API_KEY

    def transcribe(self, audio_int16):
        if audio_int16 is None or len(audio_int16) == 0:
            return ""
        self.load()
        from dashscope.audio.asr import Recognition, RecognitionCallback, RecognitionResult

        parts = []

        class _CB(RecognitionCallback):
            def on_event(self, result):
                s = result.get_sentence()
                # 一句话期间 on_event 会多次回调、text 逐渐增长，只在终态取，避免重复累加
                if isinstance(s, dict) and s.get("text") and RecognitionResult.is_sentence_end(s):
                    parts.append(s["text"])

        rec = Recognition(
            model=PARAFORMER_MODEL,
            format="pcm",
            sample_rate=REC_SAMPLE_RATE,
            language_hints=["zh"],
            callback=_CB(),
        )
        pcm = audio_int16.tobytes()  # 已是 16-bit 小端
        rec.start()
        try:
            for i in range(0, len(pcm), self._CHUNK):
                rec.send_audio_frame(pcm[i:i + self._CHUNK])
        finally:
            rec.stop()  # 阻塞直到终态回调完成
        return "".join(parts).strip()


# 后端注册表：名字 -> 工厂。新增云后端在此登记。
_BACKENDS = {
    "local": LocalWhisperBackend,
    "aliyun": AliyunParaformerBackend,
}

_backend = None


def _get_backend() -> STTBackend:
    """按 STT_BACKEND 惰性创建并缓存当前后端实例。"""
    global _backend
    if _backend is None:
        name = (STT_BACKEND or "local").strip().lower()
        factory = _BACKENDS.get(name)
        if factory is None:
            raise RuntimeError(
                f"未知 STT_BACKEND「{name}」。可选：{', '.join(_BACKENDS)}。"
                f"请在 voice_assistant/.env 中修正（默认 local）。"
            )
        _backend = factory()
    return _backend


def load_model() -> None:
    """预加载/初始化当前 STT 后端（接口名保持不变，main.py/translate.py 调用不动）。"""
    _get_backend().load()


def transcribe(audio_int16: np.ndarray) -> str:
    """把 16kHz 单声道 int16 音频转写为文字（分派到当前后端）。"""
    return _get_backend().transcribe(audio_int16)
