"use client";

import { useEffect, useRef, useState } from "react";
import { QRCodeSVG } from "qrcode.react";
import { WS_URL, type ServerMessage } from "@/lib/types";
import { metamaskDeepLink } from "@/lib/ichigo";

// メインキャラ(黒人の店主 renoa)を背景透過PNGで表示。口閉じ↔口開きを音量で
// 差し替えて口パク。表情差分の単体素材が用意できたら EXPRESSIONS に追加する。
const EXPRESSIONS: Record<string, { closed: string; open?: string }> = {
  neutral: { closed: "/renoa.png", open: "/renoa-kuti.png" },
};
const ALL_IMAGES = ["/renoa.png", "/renoa-kuti.png", "/oti.png"];

type Msg = { who: "me" | "shop"; text: string };

// ステージ画面(会場の大画面)。左=キャラ(れのあ+浮遊するオチエク)、
// 右=QR(接続前) → 接続後は LINE 風チャット。1画面に収める。
export default function StagePage() {
  const [code, setCode] = useState<string>("");
  const [controllerUrl, setControllerUrl] = useState<string>("");
  const [connected, setConnected] = useState(false);   // コントローラ(スマホ)が参加中か
  const [messages, setMessages] = useState<Msg[]>([]);
  const [price, setPrice] = useState<number | null>(null);
  const [finalized, setFinalized] = useState(false);
  const [unlocked, setUnlocked] = useState(false);
  const [audioReady, setAudioReady] = useState(false);
  const [mouthOpen, setMouthOpen] = useState(false);
  const [expression] = useState<string>("neutral");

  const wsRef = useRef<WebSocket | null>(null);
  const ctxRef = useRef<AudioContext | null>(null);
  const srcRef = useRef<AudioBufferSourceNode | null>(null);
  const rafRef = useRef<number | null>(null);
  const logRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const ws = new WebSocket(`${WS_URL}?role=stage`);
    wsRef.current = ws;
    ws.onmessage = (ev) => {
      const msg: ServerMessage = JSON.parse(ev.data);
      switch (msg.type) {
        case "room_created":
          setCode(msg.room);
          // QRは MetaMask アプリ内ブラウザで開くディープリンク(決済に window.ethereum が要るため)。
          setControllerUrl(metamaskDeepLink(`${window.location.origin}/play?room=${msg.room}`));
          break;
        case "peer_joined":
          // スマホ(コントローラ)が参加 → QRを消してチャットに切り替える
          if (msg.role === "controller") setConnected(true);
          break;
        case "user_text":
          setMessages((m) => [...m, { who: "me", text: msg.text }]);
          break;
        case "agent_reply":
          setMessages((m) => [...m, { who: "shop", text: msg.text }]);
          break;
        case "speech":
          playSpeech(msg.audio_b64);
          break;
        case "state":
          setPrice(msg.price);
          setFinalized(msg.finalized);
          break;
        case "unlocked":
          setUnlocked(true);
          setFinalized(true);
          setMessages((m) => [...m, { who: "shop", text: "🎉 開錠!まいど、ありがとう!ガチャ回してや!" }]);
          break;
        case "reset_done":
          // 次のお客さんへ:初期状態に戻す(QRが再表示される)
          setConnected(false);
          setMessages([]);
          setPrice(null);
          setFinalized(false);
          setUnlocked(false);
          break;
      }
    };
    return () => ws.close();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // チャットを最下部へ自動スクロール
  useEffect(() => {
    logRef.current?.scrollTo(0, logRef.current.scrollHeight);
  }, [messages]);

  // 画像を事前読み込みして口パク切替時のちらつきを防ぐ
  useEffect(() => {
    ALL_IMAGES.forEach((s) => {
      const im = new window.Image();
      im.src = s;
    });
  }, []);

  // 次のお客さんへ:会話・価格をリセット(前のお客さんは切断される)
  const nextCustomer = () => {
    if (confirm("次のお客さんへ切り替えますか?(今の会話・値段はリセットされます)")) {
      wsRef.current?.send(JSON.stringify({ type: "reset" }));
    }
  };

  // ブラウザの自動再生制限のため、最初に一度クリックして音声を有効化する。
  const enableAudio = async () => {
    const ctx = new (window.AudioContext || (window as any).webkitAudioContext)();
    await ctx.resume();
    ctxRef.current = ctx;
    setAudioReady(true);
  };

  const playSpeech = async (b64: string) => {
    const ctx = ctxRef.current;
    if (!ctx) return; // 未有効化なら音声はスキップ(チャットは出る)
    try {
      srcRef.current?.stop();
    } catch {}
    if (rafRef.current) cancelAnimationFrame(rafRef.current);

    const bin = atob(b64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    const audioBuf = await ctx.decodeAudioData(bytes.buffer);

    const src = ctx.createBufferSource();
    src.buffer = audioBuf;
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 256;
    src.connect(analyser);
    analyser.connect(ctx.destination);
    srcRef.current = src;

    const data = new Uint8Array(analyser.frequencyBinCount);
    const tick = () => {
      analyser.getByteTimeDomainData(data);
      let sum = 0;
      for (let i = 0; i < data.length; i++) {
        const v = (data[i] - 128) / 128;
        sum += v * v;
      }
      const volume = Math.sqrt(sum / data.length);
      setMouthOpen(volume > 0.06); // 音量で口の開閉(れのあだけ)
      rafRef.current = requestAnimationFrame(tick);
    };
    src.onended = () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      setMouthOpen(false);
    };
    src.start();
    tick();
  };

  const expr = EXPRESSIONS[expression] ?? EXPRESSIONS.neutral;

  return (
    <main className="stage">
      <div className="stage-grid">
        {/* 左: キャラ(れのあ=喋る / オチエク=浮遊・喋らない) */}
        <section className="chars">
          <div className={`character-wrap${unlocked ? " unlocked" : ""}`}>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img className="character base" src={expr.closed} alt="店主れのあ" />
            {expr.open && (
              /* eslint-disable-next-line @next/next/no-img-element */
              <img
                className={`character overlay${mouthOpen ? " show" : ""}`}
                src={expr.open}
                alt=""
                aria-hidden="true"
              />
            )}
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img className="oti" src="/oti.png" alt="オチエク" />
          </div>
        </section>

        {/* 右: QR(接続前) → チャット(接続後) */}
        <section className="panel">
          <div className="panel-head">
            <span>🎰 ガチャ店長</span>
            {price !== null && (
              <span className="price">
                {finalized ? "お会計 " : "言い値 "}
                {price} トークン{finalized ? " で決定!" : ""}
              </span>
            )}
          </div>

          {!connected ? (
            <div className="join">
              {controllerUrl && <QRCodeSVG value={controllerUrl} size={260} />}
              <div style={{ textAlign: "center" }}>
                <div style={{ fontSize: "1.2rem", fontWeight: 700 }}>スマホのカメラで読み取ってね</div>
                <div className="sub">(MetaMaskアプリが開きます)</div>
                <div className="code">{code}</div>
              </div>
            </div>
          ) : (
            <div className="chatlog" ref={logRef}>
              {messages.length === 0 && <div className="hint">接続しました!話しかけてね</div>}
              {messages.map((m, i) => (
                <div key={i} className={`cbubble ${m.who}`}>
                  {m.text}
                </div>
              ))}
            </div>
          )}
        </section>
      </div>

      {/* 隅のコントロール(運営用) */}
      <div className="stage-controls">
        {!audioReady && <button onClick={enableAudio}>🔊 音声を有効にする</button>}
        {connected && <button onClick={nextCustomer}>▶ 次のお客さんへ</button>}
      </div>
    </main>
  );
}
