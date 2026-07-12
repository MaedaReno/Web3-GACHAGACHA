import Link from "next/link";

export default function Home() {
  return (
    <main style={{ maxWidth: 560, margin: "0 auto", padding: "2rem 1rem", lineHeight: 1.8 }}>
      <h1>ガチャ店長 デモ</h1>
      <p>大画面で「ステージ」を開き、表示されたQRをスマホで読み取ると接客が始まります。</p>
      <ul>
        <li>
          <Link href="/stage">▶ ステージ画面を開く(大画面用)</Link>
        </li>
        <li>
          <Link href="/play">▶ コントローラ画面(通常はQRから開く)</Link>
        </li>
      </ul>
    </main>
  );
}
