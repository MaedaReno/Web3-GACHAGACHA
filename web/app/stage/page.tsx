"use client";

import { useEffect, useRef, useState } from "react";
import { QRCodeSVG } from "qrcode.react";
import { WS_URL, type ServerMessage } from "@/lib/types";
import { metamaskDeepLink } from "@/lib/ichigo";

// メインキャラ(黒人の店主 renoa)を背景透過PNGで表示。口閉じ↔口開きを音量で
// 差し替えて口パク。表情差分(喜び等)の単体素材が用意できたら EXPRESSIONS に追加する。
const EXPRESSIONS: Record<string, { closed: string; open?: string }> = {
  neutral: { closed: "/renoa.png", open: "/renoa-kuti.png" },
};
const ALL_IMAGES = ["/renoa.png", "/renoa-kuti.png"];

// ステージ画面(会場の大画面)。
// ルーム作成 → QR表示 → 接客中は 字幕 + 価格 + キャラの口パク + VOICEVOX音声。
export default function StagePage() {
  const [code, setCode] = useState<string>("");
  const [subtitle, setSubtitle] = useState<string>("いらっしゃい!QRを読み取ってな");
  const [customer, setCustomer] = useState<string>("");
  const [price, setPrice] = useState<number | null>(null);
  const [finalized, setFinalized] = useState(false);
  const [unlocked, setUnlocked] = useState(false);
  const [controllerUrl, setControllerUrl] = useState<string>("");
  const [audioReady, setAudioReady] = useState(false);
  const [mouthOpen, setMouthOpen] = useState(false);
  const [expression, setExpression] = useState<string>("neutral");

  const wsRef = useRef<WebSocket | null>(null);
  const ctxRef = useRef<AudioContext | null>(null);
  const srcRef = useRef<AudioBufferSourceNode | null>(null);
  const rafRef = useRef<number | null>(null);

  useEffect(() => {
    const ws = new WebSocket(`${WS_URL}?role=stage`);
    wsRef.current = ws;
    ws.onmessage = (ev) => {
      const msg: ServerMessage = JSON.parse(ev.data);
      switch (msg.type) {
        case "room_created":
          setCode(msg.room);
          // QRは MetaMask アプリ内ブラウザで開くディープリンクにする(決済に window.ethereum が要るため)。
          setControllerUrl(
            metamaskDeepLink(`${window.location.origin}/play?room=${msg.room}`),
          );
          break;
        case "user_text":
          setCustomer(`お客さん: ${msg.text}`);
          break;
        case "agent_reply":
          setSubtitle(msg.text);
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
          setSubtitle("開錠!まいど、ありがとう!ガチャ回してや!");
          break;
        case "reset_done":
          // 次のお客さんへ:表示を初期状態に戻す(QRが再表示される)
          setCustomer("");
          setSubtitle("いらっしゃい!QRを読み取ってな");
          setPrice(null);
          setFinalized(false);
          setUnlocked(false);
          setExpression("neutral");
          break;
      }
    };
    ws.onclose = () => setSubtitle((s) => s + "(接続が切れました。再読み込みしてね)");
    return () => ws.close();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 画像を事前読み込みして、口パク切替時のちらつきを防ぐ
  useEffect(() => {
    ALL_IMAGES.forEach((s) => {
      const im = new window.Image();
      im.src = s;
    });
  }, []);

  // ブラウザの自動再生制限のため、最初に一度クリックして音声を有効化する。
  // 次のお客さんへ:サーバに会話・価格のリセットを依頼(前のお客さんは切断される)
  const nextCustomer = () => {
    if (confirm("次のお客さんへ切り替えますか?(今の会話・値段はリセットされます)")) {
      wsRef.current?.send(JSON.stringify({ type: "reset" }));
    }
  };

  const enableAudio = async () => {
    const ctx = new (window.AudioContext || (window as any).webkitAudioContext)();
    await ctx.resume();
    ctxRef.current = ctx;
    setAudioReady(true);
  };

  const playSpeech = async (b64: string) => {
    const ctx = ctxRef.current;
    if (!ctx) return; // 未有効化なら音声はスキップ(字幕は出る)
    // 前の音声が鳴っていたら止める
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
      // 波形の振幅(音量)で口の開閉を決める簡易リップシンク
      let sum = 0;
      for (let i = 0; i < data.length; i++) {
        const v = (data[i] - 128) / 128;
        sum += v * v;
      }
      const volume = Math.sqrt(sum / data.length);
      setMouthOpen(volume > 0.06);
      rafRef.current = requestAnimationFrame(tick);
    };

    src.onended = () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      setMouthOpen(false);
    };
    src.start();
    tick();
  };

  // 口パク: ベース(口閉じ)の上に口開きを重ね、mouthOpen で切り替える(全身差し替え)。
  const expr = EXPRESSIONS[expression] ?? EXPRESSIONS.neutral;

  return (
    <main className="stage">
      {/* メインキャラ(透過PNG)。しゃべる間だけ口開きを重ねて口パク。 */}
      <div className={`character-wrap${unlocked ? " unlocked" : ""}`}>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img className="character base" src={expr.closed} alt="ガチャ店主" />
        {expr.open && (
          /* eslint-disable-next-line @next/next/no-img-element */
          <img
            className={`character overlay${mouthOpen ? " show" : ""}`}
            src={expr.open}
            alt=""
            aria-hidden="true"
          />
        )}
      </div>
      {unlocked && <div style={{ fontSize: "clamp(3rem, 10vh, 8rem)" }}>🎉</div>}
      <div className="customer">{customer}</div>
      <div className="subtitle">{subtitle}</div>
      {price !== null && (
        <div className="price">
          {finalized ? "お会計: " : "ただいまの言い値: "}
          {price} トークン{finalized ? " で決定!" : ""}
        </div>
      )}

      {controllerUrl && !customer && (
        <div className="join">
          <QRCodeSVG value={controllerUrl} size={200} />
          <div>
            <div style={{ fontSize: "1.2rem" }}>スマホのカメラで読み取ってね</div>
            <div style={{ fontSize: "0.9rem", opacity: 0.8 }}>(MetaMaskアプリが開きます)</div>
            <div className="code">{code}</div>
          </div>
        </div>
      )}

      {/* 運営用: 接客が始まったら「次のお客さんへ」でリセットできる */}
      {customer && (
        <button
          onClick={nextCustomer}
          style={{ padding: "0.7rem 1.4rem", fontSize: "1rem", borderRadius: "0.6rem", border: 0, cursor: "pointer" }}
        >
          ▶ 次のお客さんへ(リセット)
        </button>
      )}

      {/* 音声を鳴らすには最初に一度クリックが必要(ブラウザの自動再生制限) */}
      {!audioReady && (
        <button
          onClick={enableAudio}
          style={{ padding: "1rem 2rem", fontSize: "1.2rem", borderRadius: "0.6rem", border: 0, cursor: "pointer" }}
        >
          🔊 音声を有効にする(最初に1回押す)
        </button>
      )}
    </main>
  );
}
