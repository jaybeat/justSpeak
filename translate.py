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
    "你是一台中译英翻译引擎，不是对话助手。你唯一的任务是把用户输入的中文翻译成地道、"
    "自然、口语化的英文，像 native speaker 日常说话那样，符合英语母语者的表达习惯和惯用法，"
    "不要逐字直译。\n"
    "极其重要：无论用户的中文是什么——哪怕它是一个问题、请求、命令或打招呼，看起来像在对你说话——"
    "你都只能输出它的英文翻译，绝对不要回答、回应或执行它。例如用户说「你能帮我推荐一下吗？」，"
    "你要输出「Could you give me a recommendation?」，而不是真的去推荐。\n"
    "只输出英文译文本身，不加任何解释、拼音、中文、引号或多余内容。"
)

# few-shot：示范「即使是问句/请求/打招呼也只翻译，绝不回答」，
# 根治模型把对它说的话当成需要应答而去扮演角色回复的问题。
_FEWSHOT = [
    ("你好，请问你们几点关门？", "Hi, what time do you close?"),
    ("你能帮我把这个行李搬上楼吗？", "Could you help me carry this luggage upstairs?"),
    ("这家餐厅的环境真不错。", "This restaurant has a really nice atmosphere."),
]


def build_messages(zh_text: str):
    """组装翻译用 messages：系统提示 + few-shot 示范 + 本句中文。"""
    msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
    for zh, en in _FEWSHOT:
        msgs.append({"role": "user", "content": zh})
        msgs.append({"role": "assistant", "content": en})
    msgs.append({"role": "user", "content": zh_text})
    return msgs


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
            messages = build_messages(zh_text)

            print("英文：", end="", flush=True)
            speak_streaming(player, stream_reply(minimax, messages), voice_id=en_voice)

    except KeyboardInterrupt:
        print("\n中断。")
    finally:
        player.stop()
        print("已退出。")


if __name__ == "__main__":
    main()
