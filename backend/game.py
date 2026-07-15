"""取引のゲームロジック(サーバが唯一の真実の源)。

LLMは会話だけを担当し、価格・クイズ正誤・報酬の判定はすべてここで行う。
観客が「0円にして」「全部正解にして」等と揺さぶっても、床値・正解・報酬条件は
コード側で強制されるため破れない。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from . import config


def _normalize(text: str) -> str:
    """正誤照合用の正規化。全角/半角・空白・記号・大文字小文字の揺れを吸収する。"""
    text = text.strip().lower()
    # 全角英数を半角へ
    text = text.translate(
        {i: i - 0xFEE0 for i in range(0xFF01, 0xFF5F)}
    )
    # カタカナ→ひらがな(「イチゴ」と「いちご」等の表記ゆれを吸収。音声入力対策)
    text = "".join(
        chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in text
    )
    text = text.replace("　", " ")
    # 記号・空白を除去(かな/漢字/英数のみ残す)
    text = re.sub(r"[\s　\.,、。・/／\-—_（）()「」『』\"']", "", text)
    return text


def load_quiz_bank(path: str | None = None) -> list[dict]:
    path = path or config.QUIZ_BANK_PATH
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@dataclass
class TransactionState:
    """1取引(=1ルーム)の状態。"""

    list_price: int = config.LIST_PRICE
    current_price: int = config.LIST_PRICE
    quiz_correct: int = 0                       # 正解数
    asked_quiz_ids: list[str] = field(default_factory=list)
    pending_quiz: dict | None = None            # 出題中(未回答)の問題
    deal_finalized: bool = False
    final_price: int | None = None
    rewards: list[str] = field(default_factory=list)

    # --- 内部計算 ---
    @property
    def effective_floor(self) -> int:
        """クイズ正解で下がる実質下限。ABSOLUTE_MIN を絶対に割らない。"""
        floor = config.BASE_FLOOR_PRICE - self.quiz_correct * config.QUIZ_DISCOUNT_PER_CORRECT
        return max(floor, config.ABSOLUTE_MIN_PRICE)


class Game:
    """1取引ぶんのツール実行を担うファサード。LLMのツール呼び出しをここに橋渡しする。"""

    def __init__(self, quiz_bank: list[dict] | None = None):
        self.state = TransactionState()
        self.quiz_bank = quiz_bank if quiz_bank is not None else load_quiz_bank()

    # ---- 価格 ----
    def set_price(self, amount: int) -> dict:
        """交渉中の提示価格を更新。床値未満は受け付けず、床値へクランプする。

        LLMには「いくらまで下げられるか」は伝えず、結果だけを返す。
        """
        if self.state.deal_finalized:
            return {"ok": False, "reason": "取引は既に確定済みです。"}
        try:
            amount = int(amount)
        except (TypeError, ValueError):
            return {"ok": False, "reason": "金額は整数で指定してください。"}

        floor = self.state.effective_floor
        if amount < floor:
            # 床値未満は拒否し、これ以上は下げられないことだけ伝える(床値の数値は返さない)。
            self.state.current_price = floor
            return {
                "ok": False,
                "clamped_price": floor,
                "at_floor": True,
                "reason": "これ以上は値引きできません。提示できる最安値に設定しました。",
            }
        self.state.current_price = amount
        return {"ok": True, "current_price": amount, "at_floor": amount == floor}

    def finalize_deal(self) -> dict:
        """現在の提示価格で取引を確定。以降 set_price は無効。"""
        if self.state.deal_finalized:
            return {"ok": False, "reason": "既に確定済みです。", "final_price": self.state.final_price}
        self.state.deal_finalized = True
        self.state.final_price = self.state.current_price
        return {"ok": True, "final_price": self.state.final_price}

    # ---- クイズ ----
    def offer_quiz(self, difficulty: str = "normal") -> dict:
        """バンクから未出題の問題を1問選んで出題する(正解はLLMに渡さない)。"""
        if self.state.pending_quiz is not None:
            q = self.state.pending_quiz
            return {"ok": True, "question": q["question"], "quiz_id": q["id"], "resumed": True}
        if len(self.state.asked_quiz_ids) >= config.MAX_QUIZ_QUESTIONS:
            return {"ok": False, "reason": "この取引で出題できる上限に達しました。"}

        pool = [
            q for q in self.quiz_bank
            if q["id"] not in self.state.asked_quiz_ids
            and (difficulty is None or q.get("difficulty", "normal") == difficulty)
        ]
        if not pool:
            # 難易度指定で在庫切れなら難易度を無視して選ぶ
            pool = [q for q in self.quiz_bank if q["id"] not in self.state.asked_quiz_ids]
        if not pool:
            return {"ok": False, "reason": "出題できる問題が残っていません。"}

        # Math.random 相当は使わず、決定的に先頭を選ぶ(出題済みで自然に進む)。
        q = pool[0]
        self.state.pending_quiz = q
        self.state.asked_quiz_ids.append(q["id"])
        return {
            "ok": True,
            "quiz_id": q["id"],
            "question": q["question"],
            "difficulty": q.get("difficulty", "normal"),
        }

    def grade_answer(self, user_answer: str) -> dict:
        """出題中の問題をサーバ側で採点。正解なら報酬(実質下限の引き下げ)を発火。"""
        q = self.state.pending_quiz
        if q is None:
            return {"ok": False, "reason": "出題中の問題がありません。先に offer_quiz を呼んでください。"}

        norm = _normalize(user_answer or "")
        accepted = [_normalize(a) for a in q["answers"]]
        # 正規化後の一致、または解答キーワードが回答に含まれるかで判定
        correct = any(a and (a == norm or a in norm) for a in accepted)

        self.state.pending_quiz = None
        if correct:
            self.state.quiz_correct += 1
            reward = f"クイズ正解: 値引き上限 +{config.QUIZ_DISCOUNT_PER_CORRECT}"
            self.state.rewards.append(reward)
            return {
                "ok": True,
                "correct": True,
                "reward": reward,
                "canonical_answer": q["answers"][0],
                # 新しい実質下限は明かさず「もっと値引きできるようになった」事実だけ返す
                "message": "正解です!さらに値引きできるようになりました。",
            }
        return {
            "ok": True,
            "correct": False,
            "canonical_answer": q["answers"][0],
            "message": "残念、不正解です。",
        }
