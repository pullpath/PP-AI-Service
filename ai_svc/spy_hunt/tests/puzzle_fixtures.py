from __future__ import annotations

from typing import Dict, Tuple

NAMES = ["Milo", "Juno", "Pip", "Nova", "Remy"]
CLUES_R1 = ["It has keys.", "Big and heavy.", "You hear it in churches.", "Black and white.", "Takes years to learn."]
CLUES_R2 = ["Found in many homes.", "Pedals involved.", "Needs air to sound.", "Lessons are common.", "Often in a hall."]
ZH = ["有琴键。", "又大又重。", "在教堂里能听到。", "黑白相间。", "要学很多年。",
      "很多家里有。", "有踏板。", "需要空气才会响。", "常有课程。", "常在大厅里。"]


def sample_puzzle(spy_seat: int = 2) -> Tuple[dict, dict]:
    clues = CLUES_R1 + CLUES_R2
    statements = []
    for i, text in enumerate(clues):
        statements.append({
            "id": i + 1, "round": 1 if i < 5 else 2, "stage": 0, "seat": i % 5,
            "kind": "statement", "text": text, "lang": "en",
            "translations": {"zh-Hans": ZH[i]}, "created_at": 0,
        })
    spy_word = {"en": "organ", "zh-Hans": "风琴"}
    public = {
        "origin_lang": "en",
        "civilian_word": {"en": "piano", "zh-Hans": "钢琴"},
        "players": [{"seat": s, "name": n} for s, n in enumerate(NAMES)],
        "statements": statements,
        "options": [spy_word,
                    {"en": "guitar", "zh-Hans": "吉他"},
                    {"en": "drum", "zh-Hans": "鼓"},
                    {"en": "flute", "zh-Hans": "长笛"}],
    }
    answer: Dict = {
        "spy_seat": spy_seat,
        "spy_word": spy_word,
        "civilian_word": {"en": "piano", "zh-Hans": "钢琴"},
        "option_index": 0,
    }
    return public, answer
