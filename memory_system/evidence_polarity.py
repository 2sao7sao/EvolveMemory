"""Directional checks for preference evidence.

A record key/value is only evidence for a profile when the quoted user text
actually expresses that preference. A negation ("不是一概越短越好") points the
other way, and an unrelated task sentence ("给一个动作就好") is no evidence at
all. These are conservative lexical checks, not a semantic parser; the semantic
review still owns ambiguous language.
"""
from __future__ import annotations

import re

SUPPORT = "support"
COUNTER = "counter"
UNRELATED = "unrelated"

# (key, value) -> (terms that express the value, terms that express its opposite).
# Only preference-like slots with a clear direction are covered; anything else
# keeps the previous mapping behaviour.
_PREFERENCE_TERMS: dict[tuple[str, str], tuple[tuple[str, ...], tuple[str, ...]]] = {
    ("detail_preference", "concise"): (
        ("简洁", "简短", "精简", "越短", "短一点", "短答", "几句话", "brief", "concise", "shorter"),
        ("啰嗦", "冗长", "太长", "长篇", "verbose", "too long"),
    ),
    ("detail_preference", "detailed"): (
        ("详细", "细节", "展开", "深入", "多给信息", "detail", "detailed", "longer", "elaborate"),
        ("简洁", "简短", "精简", "越短", "太短", "几句话", "brief", "concise", "shorter"),
    ),
    ("communication_style", "direct"): (
        ("直接", "直白", "开门见山", "direct", "straight"),
        ("委婉", "含蓄", "绕", "tactful", "gentle"),
    ),
    ("communication_pace", "slow"): (
        ("慢慢", "慢一点", "放慢", "slow"),
        ("快点", "加快", "fast", "quicker"),
    ),
    ("planning_preference", "checklist"): (("清单", "checklist"), ()),
    ("response_opening", "answer_first"): (
        ("先给结论", "结论先行", "先说结论", "answer first", "answer_first", "conclusion first"),
        (),
    ),
    ("explanation_structure", "step_by_step"): (
        ("分步骤", "按步骤", "步骤", "step", "step_by_step"),
        (),
    ),
    ("decision_preference", "recommend"): (
        ("建议", "推荐", "帮我决定", "recommend", "recommendation"),
        (),
    ),
    ("decision_preference", "options"): (
        ("方案", "选项", "options", "option"),
        ("推荐", "帮我决定", "recommend"),
    ),
    ("learning_preference", "example_first"): (
        ("例子", "举例", "案例", "example"),
        ("原理", "principle"),
    ),
    ("learning_preference", "principle_first"): (
        ("原理", "principle"),
        ("例子", "举例", "example"),
    ),
    ("collaboration_preference", "challenge"): (
        ("挑战", "挑刺", "质疑", "challenge", "critique"),
        (),
    ),
    ("collaboration_preference", "socratic"): (
        ("教练", "提问引导", "socratic", "coach"),
        (),
    ),
}

_EN_NEGATION = re.compile(
    r"\b(?:not|no longer|never|don't|doesn't|didn't|isn't|aren't|won't|wouldn't)\b"
)
_CN_NEGATION_CUES = (
    "不是", "并非", "并不", "并没有", "没有", "不要", "不用", "不必", "无需",
    "不需要", "不想", "不希望", "不喜欢", "不太", "不再", "别再", "不觉得",
    "不认为", "从不", "从未", "从来不",
)
# "别" is a negation only when it is not part of a word like 特别/区别/性别.
_BIE_FALSE_PREFIXES = "特分级类性告派区离识别"
_NEGATION_WINDOW = 12

_ONE_OFF_MARKERS = (
    "这次", "本轮", "这轮", "本次", "这一轮", "这个例子", "这例子", "就这一次",
    "仅这一次", "仅限这次", "暂时", "先这样", "今天", "今晚", "眼下",
    "this time", "this turn", "for this example", "just this once",
    "today only", "for now",
)
_DURABLE_MARKERS = (
    "以后", "今后", "长期", "一直", "每次", "总是", "始终", "往后", "永久", "天天",
    "今天起", "从现在起", "从今天起",
    "from now on", "always", "every time", "long-term", "long term", "permanent",
)


def _negated(prefix: str) -> bool:
    """Whether a negation cue sits just before the preference term."""
    for match in _EN_NEGATION.finditer(prefix):
        if len(prefix) - match.end() <= _NEGATION_WINDOW:
            return True
    for cue in _CN_NEGATION_CUES:
        index = prefix.rfind(cue)
        if index != -1 and len(prefix) - (index + len(cue)) <= _NEGATION_WINDOW:
            return True
    for index, char in enumerate(prefix):
        if char == "别" and (index == 0 or prefix[index - 1] not in _BIE_FALSE_PREFIXES):
            if len(prefix) - index - 1 <= _NEGATION_WINDOW:
                return True
    return False


def preference_quote_alignment(quote: str, key: str, value: object) -> str | None:
    """Read the quote's direction for one stored preference.

    Returns "support", "counter" or "unrelated" for covered slots, and None when
    the slot has no directional lexicon (legacy behaviour).
    """
    terms = _PREFERENCE_TERMS.get((str(key), str(value)))
    if terms is None:
        return None
    support_terms, oppose_terms = terms
    lowered = str(quote).lower()
    mentions: list[tuple[int, str]] = []
    for term in support_terms:
        position = lowered.find(term.lower())
        if position >= 0:
            mentions.append((position, SUPPORT))
    for term in oppose_terms:
        position = lowered.find(term.lower())
        if position >= 0:
            mentions.append((position, COUNTER))
    if not mentions:
        return UNRELATED
    position, side = sorted(mentions)[0]
    clause_start = 0
    for separator in "，,。.!！?？;；:\n":
        clause_start = max(clause_start, lowered.rfind(separator, 0, position) + 1)
    if _negated(lowered[clause_start:position]):
        side = COUNTER if side == SUPPORT else SUPPORT
    return side


def is_one_off_instruction(text: str) -> bool:
    """Whether the text scopes the request to this turn/example, not a pattern."""
    lowered = str(text).lower()
    if any(marker in lowered for marker in _DURABLE_MARKERS):
        return False
    return any(marker in lowered for marker in _ONE_OFF_MARKERS)
