"""rooms.py の検証(WebSocket/SDK不要)。

    python -m backend.test_rooms
"""

from types import SimpleNamespace

from .game import Game
from .rooms import RoomManager


def _fake_agent():
    # Agent の代わり。ルーム管理が触るのは agent.game.state だけ。
    return SimpleNamespace(game=Game())


def test_create_room_gives_unique_codes():
    m = RoomManager(agent_factory=_fake_agent)
    codes = {m.create_room().code for _ in range(50)}
    assert len(codes) == 50


def test_controller_exclusivity():
    m = RoomManager(agent_factory=_fake_agent)
    room = m.create_room()
    ws1, ws2 = object(), object()
    r, err = m.join(room.code, ws1, "controller")
    assert err is None and r is room
    # 2人目のコントローラは拒否(接客中)
    r2, err2 = m.join(room.code, ws2, "controller")
    assert r2 is None and err2 is not None


def test_stage_can_have_multiple_connections():
    m = RoomManager(agent_factory=_fake_agent)
    room = m.create_room()
    _, e1 = m.join(room.code, object(), "stage")
    _, e2 = m.join(room.code, object(), "stage")
    assert e1 is None and e2 is None
    assert len(room.stages) == 2


def test_join_unknown_room():
    m = RoomManager(agent_factory=_fake_agent)
    r, err = m.join("ZZZZ", object(), "controller")
    assert r is None and err is not None


def test_snapshot_never_leaks_floor():
    m = RoomManager(agent_factory=_fake_agent)
    room = m.create_room()
    snap = room.state_snapshot()
    # 床値/実質下限は絶対にクライアントへ出さない
    assert "floor" not in snap and "effective_floor" not in snap
    assert set(snap) >= {"type", "price", "quiz_correct", "finalized", "final_price"}


def test_reset_room_gives_fresh_state():
    m = RoomManager(agent_factory=_fake_agent)
    room = m.create_room()
    code_before = room.code
    # 前のお客さんが値切って価格が動いた状態を作る
    room.agent.game.set_price(210)
    assert room.state_snapshot()["price"] == 210
    # 次のお客さんへ:会話・価格が新品に戻る。ルームコードは維持
    m.reset_room(room)
    assert room.code == code_before
    assert room.state_snapshot()["price"] == room.agent.game.state.list_price


def test_leave_cleans_up_empty_room():
    m = RoomManager(agent_factory=_fake_agent)
    room = m.create_room()
    ws = object()
    m.join(room.code, ws, "controller")
    m.leave(ws)
    assert m.get(room.code) is None  # 接続ゼロで破棄


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"  ok: {fn.__name__}")
    print(f"\n{len(fns)}/{len(fns)} passed")


if __name__ == "__main__":
    _run_all()
