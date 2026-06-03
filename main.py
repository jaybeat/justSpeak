"""本地低延迟语音助手 — 多轮连续对话主循环。

技术栈：MiniMax(LLM) + MiniMax(TTS) + 本地 Whisper(STT)，国内直连，无需代理。
流程（每一轮）：
    回车录音 -> 本地 Whisper STT -> MiniMax 流式 LLM -> 句级流式 MiniMax TTS -> 无缝播放 -> 写回历史
"""

import sys

try:  # Windows 控制台默认 GBK，强制 UTF-8 让中文不乱码
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from config import make_minimax_client, TTS_SAMPLE_RATE
from audio_io import record_until_enter, GaplessPlayer
from pipeline import transcribe, stream_reply, speak_streaming
import stt

SYSTEM_PROMPT = (
    "你是一个友好、简洁的中文语音助手。回答要口语化、简短自然，"
    "像聊天一样，避免长篇大论和列表符号。"
)


def main():
    minimax = make_minimax_client()
    stt.load_model()  # 预加载 Whisper，避免第一轮卡顿
    player = GaplessPlayer(sample_rate=TTS_SAMPLE_RATE)

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    print("=" * 48)
    print(" 语音助手已启动（MiniMax LLM/TTS + 本地 Whisper）")
    print(" 回车开始/结束录音；在开始提示处输入 q 退出。")
    print("=" * 48)

    try:
        while True:
            audio = record_until_enter()
            if audio is None:
                break
            if audio.size == 0:
                print("没录到音频，请重试。")
                continue

            user_text = transcribe(audio)
            if not user_text:
                print("没听清，请再说一次。")
                continue

            print(f"\n你：{user_text}")
            messages.append({"role": "user", "content": user_text})

            print("助手：", end="", flush=True)
            reply = speak_streaming(player, stream_reply(minimax, messages))
            messages.append({"role": "assistant", "content": reply})

    except KeyboardInterrupt:
        print("\n中断。")
    finally:
        player.stop()
        print("已退出。")


if __name__ == "__main__":
    main()
