"""エンドツーエンドの動作確認(サーバ起動不要・単体で完結)。

FastAPI アプリを内部で直接起動し、ステージ(大画面)役とコントローラ(スマホ)役の
2つの WebSocket を張って会話を1〜2往復流す。店長の返事・価格が返ること、そして
同じ返事がステージ側にも届くこと(2画面同期)を確認して読みやすく表示する。

    ANTHROPIC_API_KEY=... python scripts/e2e_check.py

※実際に Claude を呼ぶので、ごく少額の API 利用料がかかります。
"""

from __future__ import annotations

import os
import sys

# プロジェクト直下を import パスに追加(scripts/ から実行しても backend を読めるように)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from backend.server import app  # noqa: E402

# お客さん役のセリフ(複数ターン=「2回目以降も送れるか」も確認)
SCRIPT = [
    "こんにちは!ガチャ引きたいねんけど、いくら?",
    "300は高いわ、200にして!",
]


def main() -> int:
    with TestClient(app) as client:
        # --- ステージ(大画面): ルーム作成 ---
        with client.websocket_connect("/ws?role=stage") as stage:
            room = None
            while room is None:
                m = stage.receive_json()
                if m["type"] == "room_created":
                    room = m["room"]
            print(f"🖥️  大画面: ルーム作成 → コード {room}\n")

            # --- コントローラ(スマホ): 参加 ---
            with client.websocket_connect(
                f"/ws?role=controller&room={room}"
            ) as ctrl:
                joined = ctrl.receive_json()
                assert joined["type"] == "joined", joined
                # 参加直後に届く初期状態スナップショットを1つ読み飛ばす(ターンとずれないように)
                init_state = ctrl.receive_json()
                assert init_state["type"] == "state", init_state
                print(f"📱 スマホ: ルーム {room} に参加")
                print("=" * 56)

                last_reply = None
                for line in SCRIPT:
                    print(f"\n📱 お客さん> {line}")
                    ctrl.send_json({"type": "user_text", "text": line})
                    # このターンは state が来たら締め
                    while True:
                        m = ctrl.receive_json()
                        if m["type"] == "agent_reply":
                            last_reply = m["text"]
                            print(f"🧑‍🦱 店長> {m['text']}")
                        elif m["type"] == "state":
                            tag = "お会計(確定)" if m["finalized"] else "言い値"
                            print(f"   💰 {tag}: {m['price']} トークン / クイズ正解 {m['quiz_correct']}")
                            break
                        elif m["type"] == "error":
                            print(f"   ⚠️ エラー: {m['message']}")
                            break

                # --- 2画面同期: 同じ返事が大画面にも届いていたか ---
                stage_replies = []
                while len(stage_replies) < len(SCRIPT):
                    m = stage.receive_json()
                    if m["type"] == "agent_reply":
                        stage_replies.append(m["text"])

    print("\n" + "=" * 56)
    synced = last_reply is not None and last_reply in stage_replies
    print(f"\n✅ 2画面同期: 店長の返事は大画面にも届いた → {synced}")
    print(f"✅ 複数ターン: {len(SCRIPT)} 回とも送信・返信できた")
    return 0 if synced else 1


if __name__ == "__main__":
    raise SystemExit(main())
