"""game.py のサーバ側ロジック検証(APIキー不要)。

    python -m backend.test_game      # 単体で実行
    pytest backend/test_game.py      # pytest でも可
"""

from . import config
from .game import Game, _normalize


def test_price_never_below_floor():
    g = Game()
    r = g.set_price(10)  # 床値を大きく割る要求
    assert r["ok"] is False
    assert r["at_floor"] is True
    assert g.state.current_price == config.BASE_FLOOR_PRICE
    assert g.state.current_price >= config.ABSOLUTE_MIN_PRICE


def test_normal_negotiation_within_range():
    g = Game()
    r = g.set_price(250)
    assert r["ok"] is True
    assert g.state.current_price == 250


def test_correct_quiz_lowers_effective_floor():
    # 本番 quiz_bank.json の内容に依存しないよう、専用の bank を注入する
    g = Game(quiz_bank=[
        {"id": "t1", "difficulty": "easy", "question": "テスト?", "answers": ["ブロック"]},
    ])
    before = g.state.effective_floor
    g.offer_quiz("easy")
    r = g.grade_answer("ブロックです")
    assert r["correct"] is True
    after = g.state.effective_floor
    assert after == before - config.QUIZ_DISCOUNT_PER_CORRECT
    # 正解後は前より安い額まで下げられる
    assert g.set_price(after)["ok"] is True


def test_kana_normalization_matches_across_scripts():
    # カタカナ答え「イチゴ」に対し、ひらがな回答「いちご」でも正解になる(表記ゆれ吸収)
    g = Game(quiz_bank=[
        {"id": "t1", "difficulty": "easy", "question": "?", "answers": ["イチゴ"]},
    ])
    g.offer_quiz("easy")
    assert g.grade_answer("いちご")["correct"] is True



def test_wrong_quiz_no_reward():
    g = Game()
    before = g.state.effective_floor
    g.offer_quiz("easy")
    r = g.grade_answer("わかりません")
    assert r["correct"] is False
    assert g.state.effective_floor == before


def test_absolute_min_is_respected_even_with_rewards():
    g = Game()
    # 正解を上限まで積んでも ABSOLUTE_MIN を割らない
    for _ in range(config.MAX_QUIZ_QUESTIONS):
        q = g.offer_quiz()
        if not q.get("ok"):
            break
        # 正解を渡す: pending の canonical answer を使わずとも、grade は照合するので
        # ここでは bank から正解を引いて渡す
        qid = q["quiz_id"]
        answer = next(x["answers"][0] for x in g.quiz_bank if x["id"] == qid)
        g.grade_answer(answer)
    assert g.state.effective_floor >= config.ABSOLUTE_MIN_PRICE
    r = g.set_price(1)
    assert r["clamped_price"] >= config.ABSOLUTE_MIN_PRICE


def test_finalize_locks_price():
    g = Game()
    g.set_price(250)
    f = g.finalize_deal()
    assert f["ok"] is True and f["final_price"] == 250
    # 確定後は変更不可
    assert g.set_price(200)["ok"] is False
    assert g.state.final_price == 250


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
