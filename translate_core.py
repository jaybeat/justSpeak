"""翻译模式的语言配置与 messages 组装（CLI 与 Web 后端共享）。

把原先内嵌在 translate.py 里的系统提示、few-shot、音色和 build_messages 抽到这里，
让命令行版 translate.py 和 server/ 的 Web 后端都能 import，避免复制一份提示词。
"""

from config import MINIMAX_VOICE_ID_EN, MINIMAX_VOICE_ID_JA

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
