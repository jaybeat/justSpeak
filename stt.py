"""本地语音识别（faster-whisper）。

模型在首次调用时加载（首次运行会自动下载权重）。transcribe() 直接吃
16kHz 单声道 int16 的 numpy 数组，转成 float32 后交给 Whisper，避免额外的
音频解码依赖。
"""

import numpy as np

from config import WHISPER_MODEL, WHISPER_DEVICE, WHISPER_COMPUTE, WHISPER_LANGUAGE

_model = None


def load_model():
    """懒加载并缓存 Whisper 模型。"""
    global _model
    if _model is None:
        from faster_whisper import WhisperModel  # 延迟导入，加快无 STT 场景启动
        print(f"[STT] 加载 faster-whisper 模型「{WHISPER_MODEL}」"
              f"（device={WHISPER_DEVICE}, compute={WHISPER_COMPUTE}）；首次会下载权重…")
        _model = WhisperModel(WHISPER_MODEL, device=WHISPER_DEVICE, compute_type=WHISPER_COMPUTE)
        print("[STT] 模型就绪。")
    return _model


def transcribe(audio_int16: np.ndarray) -> str:
    """把 16kHz 单声道 int16 音频转写为文字。"""
    if audio_int16 is None or len(audio_int16) == 0:
        return ""
    model = load_model()
    audio = audio_int16.astype(np.float32) / 32768.0
    segments, _info = model.transcribe(audio, language=WHISPER_LANGUAGE, beam_size=5)
    return "".join(seg.text for seg in segments).strip()
