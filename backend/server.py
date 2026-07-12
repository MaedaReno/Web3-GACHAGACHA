"""FastAPI + WebSocket サーバ(Phase 2)。ルーム管理とブロードキャストを担う。

接続:
  ステージ(大画面):   ws://HOST/ws?role=stage                 → 新規ルーム作成、code を返す
  コントローラ(スマホ): ws://HOST/ws?role=controller&room=CODE  → 既存ルームへ参加

メッセージ契約は docs 参照。床値などの秘密はクライアントに送らない(rooms.state_snapshot)。

起動:
    uvicorn backend.server:app --host 0.0.0.0 --port 8000
本番はブラウザのマイク/wss が HTTPS 必須なので、Cloudflare Tunnel 等で TLS 公開する。
"""

from __future__ import annotations

import asyncio
import base64

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from . import config, payment, stt, tts
from .rooms import RoomManager
from .unlock import unlocker

app = FastAPI(title="Gacha Agent Server")

# フロント(Vercel)から直接つなぐので CORS を許可。デモ用に緩め。運用時は絞る。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

manager = RoomManager()


@app.get("/health")
async def health():
    return {"ok": True, "rooms": len(manager.rooms)}


# --- ESP32 の受け口(ポーリング方式) ---
@app.get("/gacha/poll")
async def gacha_poll(token: str = ""):
    """ESP32 が1秒ごとに叩く。合言葉が正しく、解錠待ちがあれば unlock=true を1回返す。"""
    if token != config.UNLOCK_TOKEN:
        return {"unlock": False}
    return {"unlock": unlocker.poll()}


@app.post("/gacha/ack")
async def gacha_ack(token: str = ""):
    """(任意)ESP32 が解錠完了を報告。"""
    return {"ok": token == config.UNLOCK_TOKEN}


async def _broadcast(room, payload: dict) -> None:
    """ルームの全メンバーへ送信。切断済みは無視。"""
    dead = []
    for ws in manager.members(room):
        try:
            await ws.send_json(payload)
        except Exception:  # noqa: BLE001
            dead.append(ws)
    for ws in dead:
        manager.leave(ws)


async def _send_stages(room, payload: dict) -> None:
    """ステージ(大画面)だけに送る。音声はモニターのスピーカーで鳴らすため。"""
    for ws in list(room.stages):
        try:
            await ws.send_json(payload)
        except Exception:  # noqa: BLE001
            manager.leave(ws)


async def _process_utterance(room, text: str) -> None:
    """お客さんの1発話(文字でも音声認識結果でも)を処理して全員へ配信する。"""
    # 1) お客さんの発話を全員へ(ステージにも吹き出しを出せる)
    await _broadcast(room, {"type": "user_text", "text": text})
    # 2) 店長の応答(LLMは同期クライアントなので別スレッドで実行)
    try:
        reply = await asyncio.to_thread(room.agent.send, text)
    except Exception as e:  # noqa: BLE001
        await _broadcast(room, {"type": "error", "message": f"応答生成に失敗: {e}"})
        return
    reply = tts.clean_text(reply)  # 絵文字・Markdown を除去(字幕・音声用)
    await _broadcast(room, {"type": "agent_reply", "text": reply})
    # 3) 状態を更新配信(価格・正解数・確定など。床値は含めない)
    await _broadcast(room, room.state_snapshot())
    # 4) モニターで音声再生(VOICEVOX。未起動なら None → 字幕のみ)
    audio = await asyncio.to_thread(tts.synthesize, reply)
    if audio:
        await _send_stages(
            room, {"type": "speech", "audio_b64": base64.b64encode(audio).decode()}
        )


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    role = ws.query_params.get("role", "controller")
    code = ws.query_params.get("room")
    await ws.accept()

    # --- 参加処理 ---
    if role == "stage" and not code:
        room = manager.create_room()
        room.stages.add(ws)
        await ws.send_json({"type": "room_created", "room": room.code})
        await ws.send_json(room.state_snapshot())
    else:
        room, err = manager.join(code, ws, role)
        if err:
            await ws.send_json({"type": "error", "message": err})
            await ws.close()
            return
        await ws.send_json({"type": "joined", "room": room.code, "role": role})
        await ws.send_json(room.state_snapshot())
        # 参加を全員に通知(ステージに「接客開始」表示など)
        await _broadcast(room, {"type": "peer_joined", "role": role})

    # --- メッセージループ ---
    try:
        while True:
            msg = await ws.receive_json()
            mtype = msg.get("type")

            if mtype == "user_text":
                text = (msg.get("text") or "").strip()
                if text:
                    await _process_utterance(room, text)

            elif mtype == "audio":
                # スマホで録音した音声 → faster-whisper で文字起こし → 文字入力と同じ処理へ
                b64 = msg.get("audio_b64")
                if not b64:
                    continue
                try:
                    audio_in = base64.b64decode(b64)
                except Exception:  # noqa: BLE001
                    continue
                text = await asyncio.to_thread(stt.transcribe, audio_in)
                if not text:
                    await ws.send_json(
                        {"type": "error", "message": "うまく聞き取れませんでした。もう一度どうぞ。"}
                    )
                    continue
                await _process_utterance(room, text)

            elif mtype == "pay":
                # スマホがMetaMaskで送金 → tx hash を検証 → OKなら解錠待ちON + 演出配信
                if not room.agent.game.state.deal_finalized:
                    await ws.send_json({"type": "error", "message": "まだ金額が確定していません。"})
                    continue
                price = room.agent.game.state.final_price
                result = await asyncio.to_thread(
                    payment.verify_payment, msg.get("tx_hash", ""), msg.get("address", ""), price
                )
                if result["ok"]:
                    unlocker.request()  # ESP32 の次のポーリングで解錠される
                    await _broadcast(
                        room, {"type": "unlocked", "price": price, "tx": msg.get("tx_hash", "")}
                    )
                else:
                    await ws.send_json({"type": "payment_error", "message": result["reason"]})

            elif mtype == "reset" and role == "stage":
                # 次のお客さんへ:会話・価格を新品に戻し、前のお客さん(コントローラ)は切断する
                manager.reset_room(room)
                for cws in list(room.controllers):
                    try:
                        await cws.send_json({"type": "session_ended"})
                        await cws.close()
                    except Exception:  # noqa: BLE001
                        pass
                    room.controllers.discard(cws)
                await _send_stages(room, {"type": "reset_done"})
                await _send_stages(room, room.state_snapshot())

            elif mtype == "ping":
                await ws.send_json({"type": "pong"})

            # 将来: type=="wallet"(MetaMask アドレス登録, Phase 4)など
    except WebSocketDisconnect:
        pass
    finally:
        manager.leave(ws)
