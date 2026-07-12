"""Agent のツール実行ループをオフライン検証(anthropic SDK 不要)。

フェイククライアントで tool_use → tool_result → 最終テキストの流れを再現し、
ツールが実際に game.py を動かすこと、メッセージ組み立てが正しいことを確認する。

    python -m backend.test_agent_loop
"""

from types import SimpleNamespace

from .game import Game
from .llm import Agent
from .rag import Retriever


def _text(t):
    return SimpleNamespace(type="text", text=t)


def _tool_use(tid, name, inp):
    return SimpleNamespace(type="tool_use", id=tid, name=name, input=inp)


class FakeClient:
    """create() が呼ばれるたび、あらかじめ用意した応答を順に返す。"""

    def __init__(self, scripted):
        self._scripted = list(scripted)
        self.calls = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        content, stop = self._scripted.pop(0)
        return SimpleNamespace(content=content, stop_reason=stop)


def test_tool_use_drives_game_and_returns_text():
    scripted = [
        # 1回目: set_price(250) を要求
        ([_text("ええで、ほな"), _tool_use("t1", "set_price", {"amount": 250})], "tool_use"),
        # 2回目: ツール結果を受けて最終発話
        ([_text("毎度!250トークンでどや?")], "end_turn"),
    ]
    fake = FakeClient(scripted)
    agent = Agent(game=Game(), retriever=Retriever(), client=fake)

    reply = agent.send("300は高い、250にして")

    assert reply == "毎度!250トークンでどや?"
    assert agent.game.state.current_price == 250
    # 2回 create が呼ばれ、2回目には tool_result を含む user メッセージが渡っている
    assert len(fake.calls) == 2
    last_msgs = fake.calls[1]["messages"]
    assert any(
        m["role"] == "user"
        and isinstance(m["content"], list)
        and m["content"][0].get("type") == "tool_result"
        for m in last_msgs
    )


def test_floor_clamp_is_enforced_through_the_loop():
    # LLM が床値を割る set_price を出しても、game 側でクランプされる
    scripted = [
        ([_tool_use("t1", "set_price", {"amount": 10})], "tool_use"),
        ([_text("それは勘弁や、これが精一杯")], "end_turn"),
    ]
    agent = Agent(game=Game(), retriever=Retriever(), client=FakeClient(scripted))
    agent.send("10トークンにして")
    assert agent.game.state.current_price >= 100  # ABSOLUTE_MIN 以上


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"  ok: {fn.__name__}")
    print(f"\n{len(fns)}/{len(fns)} passed")


if __name__ == "__main__":
    _run_all()
