// サーバ↔クライアントのメッセージ契約(backend/server.py と対応)。

export type ServerMessage =
  | { type: "room_created"; room: string }
  | { type: "joined"; room: string; role: string }
  | { type: "peer_joined"; role: string }
  | { type: "user_text"; text: string }
  | { type: "agent_reply"; text: string }
  | { type: "speech"; audio_b64: string }
  | { type: "state"; price: number; list_price: number; quiz_correct: number; finalized: boolean; final_price: number | null; rewards: string[] }
  | { type: "error"; message: string }
  | { type: "payment_error"; message: string }
  | { type: "unlocked"; price: number; tx: string }
  | { type: "reset_done" }
  | { type: "session_ended" }
  | { type: "pong" };

export type ClientMessage =
  | { type: "user_text"; text: string }
  | { type: "audio"; audio_b64: string; mime?: string }
  | { type: "pay"; tx_hash: string; address: string }
  | { type: "reset" }
  | { type: "ping" };

export const WS_URL =
  process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000/ws";
