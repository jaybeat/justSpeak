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


class _CloudBackendTemplate(STTBackend):
    """云 ASR 后端模板（占位，未实现）。MiniMax 平台暂无 ASR，故云端需自接他家。

    接入步骤：
      1. 复制本类并改名，如 AliyunParaformerBackend / IFlytekBackend。
      2. 在 transcribe() 里把 16kHz 单声道 int16 ndarray 发给云 ASR、返回识别文本：
         - 取原始 PCM 字节：audio_int16.tobytes()（已是 16-bit 小端）；
         - 需要 WAV 容器时用标准库 wave 包一层（16000Hz / 1ch / 2bytes）；
         - 鉴权与 endpoint 从 config 读（在 config.py 新增对应 env 变量）。
      3. 在下方 _BACKENDS 注册：{"aliyun": AliyunParaformerBackend}。
      4. .env 设 STT_BACKEND=aliyun 即可启用。
    管线其余部分（录音、pipeline、TTS、播放）无需任何改动。
    """

    def transcribe(self, audio_int16):
        raise NotImplementedError(
            "当前 STT 后端为占位模板，尚未实现。请参考 stt.py 中 _CloudBackendTemplate "
            "的说明接入具体云 ASR，或把 .env 的 STT_BACKEND 设回 local 使用本地 Whisper。"
        )


# 后端注册表：名字 -> 工厂。新增云后端在此登记。
_BACKENDS = {
    "local": LocalWhisperBackend,
    # "aliyun": AliyunParaformerBackend,   # 示例：实现后取消注释并登记
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
