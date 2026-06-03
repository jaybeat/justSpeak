"""中译英语音翻译模式 — 说中文，朗读 + 显示地道英文。

流程（每一句，互相独立）：
    回车录音 -> 本地 Whisper STT（中文）-> MiniMax 流式 LLM（翻译成地道口语英文）
    -> 句级流式 MiniMax TTS（英文音色）-> 无缝播放 + 同步显示英文译文

复用对话助手的整套管线，只把「对话 LLM」换成「翻译 LLM」，TTS 改用英文音色。
"""

import sys

try:  # Windows 控制台默认 GBK，强制 UTF-8 让中文不乱码
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from config import make_minimax_client, TTS_SAMPLE_RATE, MINIMAX_VOICE_ID_EN
from audio_io import record_until_enter, GaplessPlayer
from pipeline import transcribe, stream_reply, speak_streaming
import stt

SYSTEM_PROMPT = (
    "你是一名专业的中译英口译员。把用户说的中文翻译成地道、自然的英文，"
    "要像 native speaker 日常说话那样口语化，符合英语母语者的表达习惯和惯用法，"
    "不要逐字直译。只输出英文译文本身，不要加任何解释、拼音、中文或引号。"
)


def main():
    minimax = make_minimax_client()
    stt.load_model()  # 预加载 Whisper，避免第一句卡顿
    player = GaplessPlayer(sample_rate=TTS_SAMPLE_RATE)

    en_voice = MINIMAX_VOICE_ID_EN or None  # 留空则 tts_stream 自动回退默认音色

    print("=" * 48)
    print(" 中译英语音翻译（MiniMax LLM/TTS + 本地 Whisper）")
    print(" 回车开始/结束录音；说中文，朗读并显示地道英文。")
    print(" 在开始提示处输入 q 退出。")
    print("=" * 48)

    try:
        while True:
            audio = record_until_enter()
            if audio is None:
                break
            if audio.size == 0:
                print("没录到音频，请重试。")
                continue

            zh_text = transcribe(audio)
            if not zh_text:
                print("没听清，请再说一次。")
                continue

            print(f"\n你（中文）：{zh_text}")
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": zh_text},
            ]

            print("英文：", end="", flush=True)
            speak_streaming(player, stream_reply(minimax, messages), voice_id=en_voice)

    except KeyboardInterrupt:
        print("\n中断。")
    finally:
        player.stop()
        print("已退出。")


if __name__ == "__main__":
    main()
