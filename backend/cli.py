"""Phase 1 テストハーネス: ターミナルでガチャ店長と文字で対話する。

使い方:
    python -m backend.cli            # Claude と対話(ANTHROPIC_API_KEY 等が必要)
    python -m backend.cli --debug    # 毎ターン、価格・クイズ等の内部状態も表示

内部状態(床値・正解数など)はサーバ側の真実。ここで覗いて、LLMの発話と食い違って
いないか(床値を割っていないか、勝手に正解にしていないか)を検証する。
"""

from __future__ import annotations

import sys

from .game import Game
from .llm import Agent
from .rag import Retriever


def _dump_state(agent: Agent) -> str:
    s = agent.game.state
    return (
        f"  [state] price={s.current_price} floor={s.effective_floor} "
        f"quiz_correct={s.quiz_correct} finalized={s.deal_finalized} "
        f"final={s.final_price} rewards={s.rewards}"
    )


def main() -> None:
    debug = "--debug" in sys.argv
    agent = Agent(game=Game(), retriever=Retriever())

    print("=== ガチャ店長 (Phase 1 / テキスト対話) ===")
    print("「こんにちは」などと話しかけてください。終了は Ctrl-C か 'quit'。\n")

    # 口火を切ってもらう
    try:
        opening = agent.send("(お客さんがガチャの前に立った)まず挨拶して、簡単に案内して。")
        print(f"店長> {opening}\n")
        if debug:
            print(_dump_state(agent) + "\n")
    except Exception as e:  # noqa: BLE001
        print(f"[エラー] 初回応答に失敗: {e}")
        print("ANTHROPIC_API_KEY もしくは `ant auth login` の認証を確認してください。")
        return

    while True:
        try:
            user = input("あなた> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n終了します。")
            break
        if not user:
            continue
        if user.lower() in {"quit", "exit"}:
            break

        try:
            reply = agent.send(user)
        except Exception as e:  # noqa: BLE001
            print(f"[エラー] {e}")
            continue

        print(f"店長> {reply}\n")
        if debug:
            print(_dump_state(agent) + "\n")


if __name__ == "__main__":
    main()
