"""ルーム管理(WebSocket 非依存の純ロジック)。

1ルーム = 1取引。大画面(ステージ)がルームを作り、そのコードをQRで表示 →
お客さんのスマホ(コントローラ)が同じルームに参加する。ルームは1取引ずつ排他
(同時に2人が同じガチャを操作しないよう、アクティブなコントローラは1つに限る)。

WebSocket の送受信は server.py が担当し、ここは状態と「何を配信すべきか」だけを持つ。
テスト時は Agent をフェイクに差し替えられるよう、agent_factory を注入できる。
"""

from __future__ import annotations

import random
import string
from dataclasses import dataclass, field
from typing import Callable

from .llm import Agent

# 紛らわしい文字(0/O, 1/I/L)を除いたコード用アルファベット
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def _make_code(n: int = 4) -> str:
    return "".join(random.choice(_CODE_ALPHABET) for _ in range(n))


@dataclass
class Room:
    code: str
    agent: Agent
    controllers: set = field(default_factory=set)  # 接続中のコントローラ(ws)
    stages: set = field(default_factory=set)        # 接続中のステージ(ws)

    def has_active_controller(self) -> bool:
        return len(self.controllers) > 0

    def state_snapshot(self) -> dict:
        """クライアントへ送ってよい状態だけを返す。床値(effective_floor)は絶対に含めない。"""
        s = self.agent.game.state
        return {
            "type": "state",
            "price": s.current_price,
            "list_price": s.list_price,
            "quiz_correct": s.quiz_correct,
            "finalized": s.deal_finalized,
            "final_price": s.final_price,
            "rewards": s.rewards,
        }


class RoomManager:
    def __init__(self, agent_factory: Callable[[], Agent] | None = None):
        self._agent_factory = agent_factory or Agent
        self.rooms: dict[str, Room] = {}

    def create_room(self) -> Room:
        """新規ルームを作成(ステージが開くときに呼ぶ)。一意なコードを採番する。"""
        for _ in range(100):
            code = _make_code()
            if code not in self.rooms:
                room = Room(code=code, agent=self._agent_factory())
                self.rooms[code] = room
                return room
        raise RuntimeError("ルームコードの採番に失敗しました")

    def get(self, code: str) -> Room | None:
        return self.rooms.get((code or "").upper())

    def reset_room(self, room: Room) -> None:
        """お客さんが替わるときに、会話・価格を新品に戻す(同じルームコードは維持)。"""
        room.agent = self._agent_factory()

    def join(self, code: str, ws, role: str) -> tuple[Room | None, str | None]:
        """ルームへ参加。戻り値 (room, error)。error が非Noneなら参加拒否。"""
        room = self.get(code)
        if room is None:
            return None, "そのルームは存在しません。"
        if role == "controller":
            if room.has_active_controller() and ws not in room.controllers:
                return None, "このガチャは接客中です。少し待ってね。"
            room.controllers.add(ws)
        elif role == "stage":
            room.stages.add(ws)
        else:
            return None, f"未知のロール: {role}"
        return room, None

    def leave(self, ws) -> None:
        """切断時にすべてのルームから除く。空(接続ゼロ)になったルームは破棄。"""
        empty = []
        for code, room in self.rooms.items():
            room.controllers.discard(ws)
            room.stages.discard(ws)
            if not room.controllers and not room.stages:
                empty.append(code)
        for code in empty:
            del self.rooms[code]

    def members(self, room: Room) -> list:
        return list(room.controllers) + list(room.stages)
