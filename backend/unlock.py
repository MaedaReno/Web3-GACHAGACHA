"""解錠の受け口(サーバ側の状態)。

物理ガチャは1台なので、シンプルに「解錠待ちの回数」を1つ持つ。
決済検証が通ると request() で +1、ESP32 が /gacha/poll で聞きに来たら poll() が
1回だけ True を返す(その後は False)。ネットワーク越しでも確実に届く。
"""

from __future__ import annotations


class Unlocker:
    def __init__(self) -> None:
        self._pending = 0

    def request(self) -> None:
        """解錠を1回分キューに積む(決済確認時に呼ぶ)。"""
        self._pending += 1

    def poll(self) -> bool:
        """ESP32 のポーリング用。解錠待ちがあれば1回だけ True。"""
        if self._pending > 0:
            self._pending -= 1
            return True
        return False

    @property
    def pending(self) -> int:
        return self._pending


# 1台ぶんのグローバルインスタンス
unlocker = Unlocker()
