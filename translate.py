"""中译英 / 中译日 语音翻译模式 — 说中文，朗读 + 显示地道译文，可运行时切换目标语言。

流程（每一句，互相独立）：
    回车录音 -> 本地 Whisper STT（中文）-> MiniMax 流式 LLM（翻译成地道口语译文）
    -> 句级流式 MiniMax TTS（对应语言音色）-> 无缝播放 + 同步显示译文

复用对话助手的整套管线，只把「对话 LLM」换成「翻译 LLM」，TTS 按目标语言切换音色。
在录音提示处输入 en / ja 可随时切换目标语言；默认语言读 .env 的 TARGET_LANG。
"""

import sys

try:  # Windows 控制台默认 GBK，强制 UTF-8 让中文/日文不乱码
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from config import make_minimax_client, TTS_SAMPLE_RATE, TARGET_LANG
from audio_io import record_until_enter, GaplessPlayer
from pipeline import transcribe, stream_reply, speak_streaming
from translate_core import LANGS, build_messages
import stt


def main():
    minimax = make_minimax_client()
    stt.load_model()  # 预加载 Whisper，避免第一句卡顿
    player = GaplessPlayer(sample_rate=TTS_SAMPLE_RATE)

    lang = TARGET_LANG if TARGET_LANG in LANGS else "en"

    print("=" * 48)
    print(" 中译英 / 中译日 语音翻译（MiniMax LLM/TTS + 本地 Whisper）")
    print(" 回车开始/结束录音；说中文，朗读并显示地道译文。")
    print(" 输入 en/ja 随时切换目标语言；输入 q 退出。")
    print("=" * 48)

    try:
        while True:
            prof = LANGS[lang]
            prompt = (f"\n▶ 回车开始录音（目标={prof['name']}；"
                      f"输入 en/ja 切换，q 退出）：")
            res = record_until_enter(prompt=prompt, commands=("en", "ja"))

            if res is None:
                break
            if isinstance(res, str):  # 语言切换命令
                lang = res
                print(f"已切换目标语言 -> {LANGS[lang]['name']}")
                continue
            if res.size == 0:
                print("没录到音频，请重试。")
                continue

            zh_text = transcribe(res)
            if not zh_text:
                print("没听清，请再说一次。")
                continue

            print(f"\n你（中文）：{zh_text}")
            messages = build_messages(zh_text, lang)

            print(f"{prof['name']}：", end="", flush=True)
            speak_streaming(player, stream_reply(minimax, messages), voice_id=prof["voice"])

    except KeyboardInterrupt:
        print("\n中断。")
    finally:
        player.stop()
        print("已退出。")


if __name__ == "__main__":
    main()
