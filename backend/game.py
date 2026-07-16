"""取引のゲームロジック(サーバが唯一の真実の源)。

LLMは会話だけを担当し、価格・クイズ正誤・報酬の判定はすべてここで行う。
観客が「0円にして」「全部正解にして」等と揺さぶっても、床値・正解・報酬条件は
コード側で強制されるため破れない。
"""

from __future__ import annotations

import json
import random
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
    negotiation_turns: int = 0                  # お客さんの発話回数(交渉ターン)
    # 取引開始時に一度だけ引く「運」。通常交渉で 1500 まで下げられるか(約70%)。
    base_floor: int = config.BASE_FLOOR_PRICE
    # クイズ正解で解錠される深い下限(正解時に確定)。未正解なら None。
    quiz_floor: int | None = None

    # --- 内部計算 ---
    @property
    def effective_floor(self) -> int:
        """この取引の実質下限。クイズ正解時はより深い床値に切り替わる。

        床値は取引開始時の「運」とクイズ結果でサーバが決め、ABSOLUTE_MIN を絶対に割らない。
        """
        floor = self.quiz_floor if self.quiz_floor is not None else self.base_floor
        return max(floor, config.ABSOLUTE_MIN_PRICE)


class Game:
    """1取引ぶんのツール実行を担うファサード。LLMのツール呼び出しをここに橋渡しする。"""

    def __init__(self, quiz_bank: list[dict] | None = None, rng: random.Random | None = None):
        # 床値の「運」を引く乱数源。テストでは seed 済み Random を注入して決定的にできる。
        self.rng = rng if rng is not None else random.Random()
        self.state = TransactionState(base_floor=self._roll_base_floor())
        self.quiz_bank = quiz_bank if quiz_bank is not None else load_quiz_bank()

    # ---- 床値の抽選(LLMには一切見せない) ----
    def _roll_base_floor(self) -> int:
        """通常交渉の下限を抽選。約 BASE_FLOOR_PROB で 1500、外れると 1800 止まり。"""
        if self.rng.random() < config.BASE_FLOOR_PROB:
            return config.BASE_FLOOR_PRICE
        return config.UNLUCKY_FLOOR_PRICE

    def _roll_quiz_floor(self) -> int:
        """クイズ正解時に解錠される下限。通常は 1000、まれに大当たりで 500(最安)。"""
        if self.rng.random() < config.QUIZ_JACKPOT_PROB:
            return config.QUIZ_JACKPOT_PRICE
        return config.QUIZ_FLOOR_PRICE

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

        # 単調減少: 一度下げた値段より高くは戻さない(値切りは下げる方向のみ)。
        if amount > self.state.current_price:
            return {
                "ok": False,
                "current_price": self.state.current_price,
                "reason": "一度提示した値段より高くはできません。",
            }

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
            # 正解で深い下限を解錠。既に解錠済みなら、より安い方だけを採用する。
            rolled = self._roll_quiz_floor()
            if self.state.quiz_floor is None or rolled < self.state.quiz_floor:
                self.state.quiz_floor = rolled
            reward = f"クイズ正解: 値引き下限を {self.state.effective_floor} まで解錠"
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
