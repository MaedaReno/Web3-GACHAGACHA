"use client";

import { useEffect, useRef, useState } from "react";
import { WS_URL, type ServerMessage } from "@/lib/types";
import { payIchigo, metamaskDeepLink } from "@/lib/ichigo";

type Line = { who: "me" | "shop" | "sys"; text: string };

// ArrayBuffer → base64(短い録音向け。長い場合に備えて分割して変換)
function bufToB64(buf: ArrayBuffer): string {
  const bytes = new Uint8Array(buf);
  let binary = "";
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunk));
  }
  return btoa(binary);
}

// コントローラ画面(お客さんのスマホ)。QR経由で ?room=CODE 付きで開かれる。
// 入力は「文字」または「押して話す(マイク→サーバでWhisper文字起こし)」。
export default function PlayPage() {
  const [lines, setLines] = useState<Line[]>([]);
  const [price, setPrice] = useState<number | null>(null);
  const [finalized, setFinalized] = useState(false);
  const [finalPrice, setFinalPrice] = useState<number | null>(null);
  const [connected, setConnected] = useState(false);
  const [input, setInput] = useState("");
  const [recording, setRecording] = useState(false);
  const [paying, setPaying] = useState(false);
  const [paid, setPaid] = useState(false);
  const [hasWallet, setHasWallet] = useState(true); // MetaMask(window.ethereum)が使えるか

  const wsRef = useRef<WebSocket | null>(null);
  const logRef = useRef<HTMLDivElement | null>(null);
  const recRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);

  useEffect(() => {
    const room = new URLSearchParams(window.location.search).get("room");
    if (!room) {
      setLines([{ who: "sys", text: "ルームコードがありません。ステージのQRから開いてください。" }]);
      return;
    }
    const ws = new WebSocket(`${WS_URL}?role=controller&room=${room}`);
    wsRef.current = ws;
    ws.onopen = () => setConnected(true);
    ws.onclose = () => setConnected(false);
    ws.onmessage = (ev) => {
      const msg: ServerMessage = JSON.parse(ev.data);
      switch (msg.type) {
        case "joined":
          setLines((l) => [...l, { who: "sys", text: "接続しました。話しかけてみよう!" }]);
          break;
        case "user_text":
          setLines((l) => [...l, { who: "me", text: msg.text }]);
          break;
        case "agent_reply":
          setLines((l) => [...l, { who: "shop", text: msg.text }]);
          break;
        case "state":
          setPrice(msg.price);
          setFinalized(msg.finalized);
          setFinalPrice(msg.final_price);
          break;
        case "unlocked":
          setPaid(true);
          setLines((l) => [
            ...l,
            { who: "sys", text: `🎉 開錠されました!(${msg.price} ICHIGO)ガチャを回してね!` },
          ]);
          break;
        case "payment_error":
          setLines((l) => [...l, { who: "sys", text: "支払いが確認できませんでした: " + msg.message }]);
          break;
        case "session_ended":
          setLines((l) => [...l, { who: "sys", text: "接客が終了しました。ありがとうございました!" }]);
          break;
        case "error":
          setLines((l) => [...l, { who: "sys", text: msg.message }]);
          break;
      }
    };
    return () => ws.close();
  }, []);

  useEffect(() => {
    logRef.current?.scrollTo(0, logRef.current.scrollHeight);
  }, [lines]);

  // MetaMask(window.ethereum)の有無を判定。通常ブラウザには無いので、その場合は
  // 「MetaMaskで開く」ボタンで MetaMask アプリ内ブラウザへ誘導する。
  useEffect(() => {
    setHasWallet(!!(window as any).ethereum);
  }, []);

  const openInMetaMask = () => {
    window.location.href = metamaskDeepLink(window.location.href);
  };

  const sendText = (e: React.FormEvent) => {
    e.preventDefault();
    const text = input.trim();
    if (!text || wsRef.current?.readyState !== WebSocket.OPEN) return;
    wsRef.current.send(JSON.stringify({ type: "user_text", text }));
    setInput("");
  };

  // --- 押して話す(マイク) ---
  const startRec = async () => {
    if (recording) return;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mr = new MediaRecorder(stream);
      chunksRef.current = [];
      mr.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };
      mr.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(chunksRef.current, { type: mr.mimeType });
        const b64 = bufToB64(await blob.arrayBuffer());
        if (wsRef.current?.readyState === WebSocket.OPEN) {
          wsRef.current.send(JSON.stringify({ type: "audio", audio_b64: b64, mime: blob.type }));
          setLines((l) => [...l, { who: "sys", text: "🎤 送信中…(聞き取り待ち)" }]);
        }
      };
      mr.start();
      recRef.current = mr;
      setRecording(true);
    } catch (err) {
      setLines((l) => [
        ...l,
        { who: "sys", text: "マイクを使えません。ブラウザの許可、またはHTTPS/ localhost が必要です。" },
      ]);
    }
  };

  const stopRec = () => {
    if (!recording) return;
    recRef.current?.stop();
    setRecording(false);
  };

  // --- MetaMask で支払う(確定額を送金 → tx hash をサーバへ) ---
  const pay = async () => {
    if (finalPrice == null || paying) return;
    // 通常ブラウザ(window.ethereum 無し)なら MetaMask アプリ内ブラウザで開き直す。
    if (!(window as any).ethereum) {
      setLines((l) => [...l, { who: "sys", text: "MetaMaskアプリで開き直します…" }]);
      openInMetaMask();
      return;
    }
    setPaying(true);
    try {
      const { hash, address } = await payIchigo(finalPrice, (m) =>
        setLines((l) => [...l, { who: "sys", text: m }]),
      );
      wsRef.current?.send(JSON.stringify({ type: "pay", tx_hash: hash, address }));
      setLines((l) => [...l, { who: "sys", text: "送金完了。入金を確認しています…" }]);
    } catch (e: any) {
      setLines((l) => [...l, { who: "sys", text: "支払い失敗: " + (e?.message || String(e)) }]);
    } finally {
      setPaying(false);
    }
  };

  return (
    <main className="play">
      <h1>🎰 ガチャ店長 {connected ? "" : "(接続待ち…)"}</h1>

      <div className="log" ref={logRef}>
        {lines.map((l, i) => (
          <div key={i} className={`bubble ${l.who}`}>
            {l.text}
          </div>
        ))}
      </div>

      {price !== null && (
        <div className="priceBar">
          {finalized ? `お会計: ${finalPrice} トークン` : `ただいまの言い値: ${price} トークン`}
        </div>
      )}

      {finalized && !paid && hasWallet && (
        <button
          onClick={pay}
          disabled={paying || !connected}
          style={{ padding: "0.9rem", fontSize: "1.05rem", background: "#f0a500", color: "#12100e" }}
        >
          {paying ? "処理中…" : `MetaMaskで支払う(${finalPrice} ICHIGO)`}
        </button>
      )}
      {finalized && !paid && !hasWallet && (
        <button
          onClick={openInMetaMask}
          style={{ padding: "0.9rem", fontSize: "1.05rem", background: "#f0a500", color: "#12100e" }}
        >
          🦊 MetaMaskアプリで開いて支払う({finalPrice} ICHIGO)
        </button>
      )}
      {paid && <div className="priceBar">✅ 支払い完了・開錠済み。ありがとう!</div>}

      {/* 押して話す(押している間だけ録音 → 離すと送信) */}
      <button
        onPointerDown={startRec}
        onPointerUp={stopRec}
        onPointerLeave={stopRec}
        disabled={!connected}
        style={{
          padding: "0.9rem",
          fontSize: "1.05rem",
          background: recording ? "#e2413b" : "#444",
          userSelect: "none",
          touchAction: "none",
        }}
      >
        {recording ? "🔴 録音中…(離すと送信)" : "🎤 押して話す"}
      </button>

      <form onSubmit={sendText}>
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="文字で値切ったりクイズに挑戦したり…"
        />
        <button type="submit" disabled={!connected}>
          送信
        </button>
      </form>
    </main>
  );
}
