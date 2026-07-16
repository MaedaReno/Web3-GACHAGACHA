"""game.py のサーバ側ロジック検証(APIキー不要)。

    python -m backend.test_game      # 単体で実行
    pytest backend/test_game.py      # pytest でも可
"""

from . import config
from .game import Game, _normalize


class _FakeRng:
    """抽選を決定的にするための乱数スタブ。random() は与えた値を順に返す。"""

    def __init__(self, *values: float):
        self._values = list(values)

    def random(self) -> float:
        return self._values.pop(0) if self._values else 0.0


def _lucky_game(quiz_bank=None):
    """基準床値が必ず 1500(当たり運)になる Game を作る。"""
    return Game(quiz_bank=quiz_bank, rng=_FakeRng(0.0))


def test_price_never_below_floor():
    g = _lucky_game()
    r = g.set_price(10)  # 床値を大きく割る要求
    assert r["ok"] is False
    assert r["at_floor"] is True
    assert g.state.current_price == config.BASE_FLOOR_PRICE
    assert g.state.current_price >= config.ABSOLUTE_MIN_PRICE


def test_normal_negotiation_within_range():
    g = _lucky_game()
    r = g.set_price(1800)  # 元値2000から下限より上へ値下げ
    assert r["ok"] is True
    assert g.state.current_price == 1800


def test_base_floor_lottery_hits_1500_about_70_percent():
    # しきい値の直下は当たり(1500)、直上は外れ(1800)。約70%の配線を検証。
    assert Game(rng=_FakeRng(0.69)).state.base_floor == config.BASE_FLOOR_PRICE
    assert Game(rng=_FakeRng(0.71)).state.base_floor == config.UNLUCKY_FLOOR_PRICE


def test_price_is_monotonic_non_increasing():
    # 一度下げた値段より高くは戻せない(値切りは下げる方向のみ)
    g = _lucky_game()
    assert g.set_price(1700)["ok"] is True
    r = g.set_price(1900)
    assert r["ok"] is False
    assert g.state.current_price == 1700


def test_correct_quiz_unlocks_deeper_floor():
    # 本番 quiz_bank.json の内容に依存しないよう、専用の bank を注入する。
    # rng: 基準床値 1500(0.0)→ クイズは通常当たり 1000(0.5)。
    g = Game(
        quiz_bank=[{"id": "t1", "difficulty": "easy", "question": "テスト?", "answers": ["ブロック"]}],
        rng=_FakeRng(0.0, 0.5),
    )
    before = g.state.effective_floor
    g.offer_quiz("easy")
    r = g.grade_answer("ブロックです")
    assert r["correct"] is True
    after = g.state.effective_floor
    assert after == config.QUIZ_FLOOR_PRICE
    assert after < before
    # 正解後は前より安い額まで下げられる
    assert g.set_price(after)["ok"] is True


def test_quiz_jackpot_reaches_absolute_min_500():
    # クイズ抽選の大当たり(しきい値直下 0.05)で最安 500 まで解錠される。
    g = Game(
        quiz_bank=[{"id": "t1", "difficulty": "easy", "question": "?", "answers": ["ブロック"]}],
        rng=_FakeRng(0.0, 0.05),
    )
    g.offer_quiz("easy")
    g.grade_answer("ブロック")
    assert g.state.effective_floor == config.ABSOLUTE_MIN_PRICE == 500
    assert g.set_price(500)["ok"] is True


def test_kana_normalization_matches_across_scripts():
    # カタカナ答え「イチゴ」に対し、ひらがな回答「いちご」でも正解になる(表記ゆれ吸収)
    g = Game(quiz_bank=[
        {"id": "t1", "difficulty": "easy", "question": "?", "answers": ["イチゴ"]},
    ])
    g.offer_quiz("easy")
    assert g.grade_answer("いちご")["correct"] is True



def test_wrong_quiz_no_reward():
    g = _lucky_game()
    before = g.state.effective_floor
    g.offer_quiz("easy")
    r = g.grade_answer("わかりません")
    assert r["correct"] is False
    assert g.state.effective_floor == before


def test_absolute_min_is_respected_even_with_rewards():
    # クイズ大当たり(0.05)を積んでも ABSOLUTE_MIN(500)を割らない
    g = Game(rng=_FakeRng(0.71, *([0.05] * config.MAX_QUIZ_QUESTIONS)))
    for _ in range(config.MAX_QUIZ_QUESTIONS):
        q = g.offer_quiz()
        if not q.get("ok"):
            break
        # 正解を渡す: bank から正解を引いて渡す
        qid = q["quiz_id"]
        answer = next(x["answers"][0] for x in g.quiz_bank if x["id"] == qid)
        g.grade_answer(answer)
    assert g.state.effective_floor >= config.ABSOLUTE_MIN_PRICE
    r = g.set_price(1)
    assert r["clamped_price"] >= config.ABSOLUTE_MIN_PRICE


def test_finalize_locks_price():
    g = Game()
    g.set_price(1800)
    f = g.finalize_deal()
    assert f["ok"] is True and f["final_price"] == 1800
    # 確定後は変更不可
    assert g.set_price(1700)["ok"] is False
    assert g.state.final_price == 1800


def test_normalize_handles_width_and_symbols():
    assert _normalize("スマート・コントラクト") == _normalize("スマートコントラクト")
    assert _normalize("ＲＡＧ") == _normalize("rag")


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        fn()
        print(f"  ok: {fn.__name__}")
        passed += 1
    print(f"\n{passed}/{len(fns)} passed")


if __name__ == "__main__":
    _run_all()
