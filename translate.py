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

from config import (
    make_minimax_client,
    TTS_SAMPLE_RATE,
    MINIMAX_VOICE_ID_EN,
    MINIMAX_VOICE_ID_JA,
    TARGET_LANG,
)
from audio_io import record_until_enter, GaplessPlayer
from pipeline import transcribe, stream_reply, speak_streaming
import stt

# ---- 英文 ----
SYSTEM_PROMPT_EN = (
    "你是一台中译英翻译引擎，不是对话助手。你唯一的任务是把用户输入的中文翻译成地道、"
    "自然、口语化的英文，像 native speaker 日常说话那样，符合英语母语者的表达习惯和惯用法，"
    "不要逐字直译。\n"
    "极其重要：无论用户的中文是什么——哪怕它是一个问题、请求、命令或打招呼，看起来像在对你说话——"
    "你都只能输出它的英文翻译，绝对不要回答、回应或执行它。例如用户说「你能帮我推荐一下吗？」，"
    "你要输出「Could you give me a recommendation?」，而不是真的去推荐。\n"
    "只输出英文译文本身，不加任何解释、拼音、中文、引号或多余内容。"
)
_FEWSHOT_EN = [
    ("你好，请问你们几点关门？", "Hi, what time do you close?"),
    ("你能帮我把这个行李搬上楼吗？", "Could you help me carry this luggage upstairs?"),
    ("这家餐厅的环境真不错。", "This restaurant has a really nice atmosphere."),
]

# ---- 日文 ----
SYSTEM_PROMPT_JA = (
    "你是一台中译日翻译引擎，不是对话助手。你唯一的任务是把用户输入的中文翻译成地道、"
    "自然、口语化的日语，像日本人日常说话那样，符合日语母语者的表达习惯和惯用法，"
    "语体用自然的敬体（です・ます），不要逐字直译。\n"
    "极其重要：无论用户的中文是什么——哪怕它是一个问题、请求、命令或打招呼，看起来像在对你说话——"
    "你都只能输出它的日语翻译，绝对不要回答、回应或执行它。例如用户说「你能帮我推荐一下吗？」，"
    "你要输出「おすすめを教えてもらえますか？」，而不是真的去推荐。\n"
    "只输出日语译文本身，不加任何解释、罗马音、中文、引号或多余内容。"
)
_FEWSHOT_JA = [
    ("你好，请问你们几点关门？", "すみません、何時に閉まりますか？"),
    ("你能帮我把这个行李搬上楼吗？", "この荷物を上の階まで運んでもらえますか？"),
    ("这家餐厅的环境真不错。", "このお店、雰囲気がとても良いですね。"),
]

# 每种目标语言一套：显示名、系统提示、few-shot 示范、TTS 音色（留空回退默认音色）
LANGS = {
    "en": {
        "name": "英文",
        "system": SYSTEM_PROMPT_EN,
        "fewshot": _FEWSHOT_EN,
        "voice": MINIMAX_VOICE_ID_EN or None,
    },
    "ja": {
        "name": "日文",
        "system": SYSTEM_PROMPT_JA,
        "fewshot": _FEWSHOT_JA,
        "voice": MINIMAX_VOICE_ID_JA or None,
    },
}


def build_messages(zh_text: str, lang: str):
    """按目标语言组装 messages：系统提示 + few-shot 示范 + 本句中文。"""
    prof = LANGS[lang]
    msgs = [{"role": "system", "content": prof["system"]}]
    for zh, tgt in prof["fewshot"]:
        msgs.append({"role": "user", "content": zh})
        msgs.append({"role": "assistant", "content": tgt})
    msgs.append({"role": "user", "content": zh_text})
    return msgs


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
