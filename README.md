# ガチャ販売員AIエージェント

物理ガチャの購入前に対話できるAI店員。値切り交渉と講義クイズを通じて価格が動き、
合意額を既存のMetaMask決済へ渡す → 決済確認でESP32が解錠する、という流れを目指す。
(講義「Web3/AI概論」最終発表会向け)

設計の全体像・フェーズ計画は `~/.claude/plans/dazzling-mixing-lighthouse.md` を参照。

## 構成(抜粋)

```
backend/            頭脳・ゲームロジック・WebSocketサーバ
  config.py         価格/報酬/モデル等のパラメータ集中管理
  game.py           取引の状態と判定(価格クランプ・クイズ採点・報酬)★サーバが真実
  rag.py            講義/Discord 検索(今は暫定キーワード検索。Phase 0 で Qdrant 化)
  llm.py            Claude + tool use(会話はLLM、判定はツール経由でサーバへ)
  rooms.py          ルーム管理(1ルーム=1取引、コントローラ排他)★床値をクライアントに出さない
  server.py         FastAPI + WebSocket。ルーム作成・参加・ブロードキャスト
  cli.py            テキスト対話のテストハーネス(単体・APIのみ)
  test_*.py         オフライン検証(APIキー/SDK不要): game / agent_loop / rooms
web/                フロント(Next.js, Vercel)= 2画面 + QR連携
  app/stage/        ステージ画面(大画面): QR表示・字幕・価格。Phase 3で音声+口パク
  app/play/         コントローラ画面(スマホ): チャット・価格。Phase 3でマイク, Phase 4で決済
  lib/types.ts      サーバ↔クライアントのメッセージ契約
ingest/             データ(Phase 0 前処理の出力先)
  quiz_bank.json    クイズ(★サンプル。実講義から生成し人手検証したものへ差し替える)
  lectures_sample.json 暫定コーパス(★本来は講義文字起こし + Discord から作る)
```

## 動かす

### 1. 依存を入れる(この環境には pip が無いので各自で)
```sh
# 例: python3 -m venv .venv && . .venv/bin/activate
python3 -m pip install -r backend/requirements.txt
```

### 2. サーバ側ロジックの検証(APIキー不要)
```sh
python3 -m backend.test_game        # 価格・クイズ・報酬・確定ロック
python3 -m backend.test_agent_loop  # ツール実行ループ(フェイククライアント)
```

### 2.5 会話まで通しで確認(サーバ/ブラウザ不要・要 API 認証)
アプリを内部で直接起動し、お客さん↔店長の会話を2往復流して表示する。「今ちゃんと動くか」を一番手早く見られる。
```sh
python3 scripts/e2e_check.py       # 実際に Claude を呼ぶ(少額の利用料)
```

### 3. Claude と実際に対話(要 API 認証)
```sh
export ANTHROPIC_API_KEY=sk-ant-...   # または `ant auth login`
python3 -m backend.cli --debug        # --debug で内部状態(価格/床値/正解数)も表示
```
`--debug` は店長の発話が**床値を割っていないか・勝手に正解にしていないか**を確認するためのもの。

### 4. 2画面(ステージ + コントローラ)を動かす(Phase 2)
```sh
# 端末A: バックエンド(要 ANTHROPIC_API_KEY)
uvicorn backend.server:app --host 0.0.0.0 --port 8000

# 端末B: フロント
cd web
cp .env.local.example .env.local      # NEXT_PUBLIC_WS_URL を確認(既定 ws://localhost:8000/ws)
npm install
npm run dev                            # http://localhost:3000
```
- PCで `http://localhost:3000/stage` を開く → QRとルームコードが出る。
- スマホ(同一LAN)でQRを読む → `/play?room=XXXX` に参加して会話開始。
  - スマホから直に叩くなら `NEXT_PUBLIC_WS_URL` を PCのLAN IP(例 `ws://192.168.x.x:8000/ws`)に。
- 本番はブラウザのマイク(Phase 3)と wss が **HTTPS 必須**。Cloudflare Tunnel 等でバックエンドをTLS公開する。

### 5. モニターで音声を鳴らす(Phase 3・任意)
店長の返事を VOICEVOX で音声化し、ステージ画面(`/stage`)でアバターの口パク付きで再生する。
1. **VOICEVOX を起動**(無料。https://voicevox.hiroshiba.jp/ か Docker)。既定で `http://127.0.0.1:50021`。
   - キャラ(話者)を変えるなら `VOICEVOX_SPEAKER=<番号>` で。一覧は `python3 -c "from backend import tts,json;print(json.dumps(tts.speakers(),ensure_ascii=False))"`。
2. バックエンドを起動(`uvicorn ...`)。VOICEVOX が動いていれば自動で音声も配信される。
3. `/stage` を開いたら、初回だけ **「🔊 音声を有効にする」ボタンを1回クリック**(ブラウザの自動再生制限のため)。
- VOICEVOX を起動していなければ **自動で字幕のみ**にフォールバック(エラーにはならない)。
- 音声を切りたいときは `GACHA_TTS=0`。

### 6. マイクで話す(Phase 3 入力側・任意)
`/play` の「🎤 押して話す」を押している間だけ録音 → 離すと送信 → サーバの faster-whisper が
文字起こし → 店長が返事。
1. **faster-whisper を入れる**(重い): `python3 -m pip install faster-whisper`。
   初回はモデルを自動DL。開発は `GACHA_WHISPER_MODEL=small`(既定)+ CPU で可。
   研究室GPUなら `GACHA_WHISPER_DEVICE=cuda GACHA_WHISPER_COMPUTE=float16 GACHA_WHISPER_MODEL=large-v3`。
2. **マイクは HTTPS か localhost でのみ使える**(ブラウザ制約)。
   - PCの `localhost:3000/play?room=...` ならそのまま使える。
   - スマホ(LANのIP/httpアクセス)ではマイク不可 → 本番は Cloudflare Tunnel 等で HTTPS 化が必要。
   - 未導入・失敗時は「うまく聞き取れませんでした」と出るだけで、文字入力は常に使える。
- 音声認識を切りたいときは `GACHA_STT=0`。

### 7. 決済とガチャ解錠(Phase 4)
流れ:店長が価格を確定 → スマホで **MetaMask から ICHIGO を送金**(Optimism)→ バックエンドが
**tx をオンチェーン検証**(受取先・送金元・額・成功・未使用)→ OKで **解錠待ちON** → ESP32 が解錠。
- フロントは `ethers` を使うので `cd web && npm install`(package.json 済み)。
- **本物の Optimism メインネット**。**テストは受取先=自分のアドレス**にすればトークンが戻りガス代だけ:
  - バックエンド: `GACHA_WALLET=0xあなたのアドレス`
  - フロント: `web/.env.local` に `NEXT_PUBLIC_GACHA_WALLET=0xあなたのアドレス`(両方合わせる)
- 検証は `backend/payment.py`(生JSON-RPCでOptimismを照会。重い依存なし)。二重送金・受取先違い・不足は弾く。

#### ESP32 の受け口(契約)— ポーリング方式
ESP32 は会場WiFiから**外向きに**バックエンドへ聞きに行く(壁を越えやすい)。
- `GET /gacha/poll?token=<合言葉>` → `{"unlock": true|false}`(true は解錠待ちが1回あるとき)
- `POST /gacha/ack?token=<合言葉>` →(任意)解錠完了の報告
- 合言葉は `GACHA_UNLOCK_TOKEN`(★本番で必ず変更)。
- ESP32ファーム側:1秒ごとに poll → true ならモーター解錠 → 回転検知で再ロック。
  この契約は**部品(モーター/センサ)が変わっても不変**なので、ハード確定後にファームだけ作ればよい。

## 公開する(発表・多人数プレイ向け)
フロントは公開、バックエンドはローカル(や研究室GPUサーバ)のまま、という構成。

1. **バックエンドを wss で公開**(ルーター設定不要。無料の Cloudflare Tunnel):
   ```sh
   # cloudflared を入れて、起動中のバックエンド(:8000)にトンネルを張る
   cloudflared tunnel --url http://localhost:8000
   # → https://xxxx.trycloudflare.com のような公開URLが出る(このプロセスは開いたまま)
   ```
   ※ trycloudflare の URL は再起動ごとに変わる。発表前に一度張って、当日は開いたままにする。
2. **フロントを Vercel で公開**:`web/` を GitHub にプッシュ → Vercel でインポート。
   - Vercel の **Root Directory を `web`** に設定(リポジトリ直下ではなくサブフォルダのため)。
   - 環境変数 **`NEXT_PUBLIC_WS_URL`** を `wss://xxxx.trycloudflare.com/ws` に設定(httpsサイトなので **wss**)。
3. 運営は公開サイトの `/stage` をモニターで開く → QRは自動で公開ドメインの `/play` を指すので、
   利用者はスマホで読むだけで参加できる。マイクも公開サイト(HTTPS)なら使える。
4. **バックエンドはどのPCでもよい**:リポジトリをコピー → venv → `pip install -r backend/requirements.txt`
   → `ANTHROPIC_API_KEY` 設定 → `uvicorn` 起動。研究室GPUサーバなら Whisper が高速。
   フロントは `NEXT_PUBLIC_WS_URL` をそのバックエンドのトンネルURLに向けるだけ。
5. **多人数**:1ルームを順番に使う。お客さんが替わるときはモニターの
   「▶ 次のお客さんへ(リセット)」で会話・価格を新品に戻す(前のお客さんは自動で切断)。

## 設計の要点(効かせている安全策)
- **お金とゲームはサーバが決める**: 床値・クイズ正誤・報酬は `game.py` が判定。LLMは会話のみ。
  「0円にして」「全部正解にして」等の揺さぶりに対して、コード側でクランプ/採点するので破れない。
- **床値はLLMに渡さない**: `set_price` は結果(受諾/クランプ)だけ返す。数値の下限は明かさない。
- **クイズは事前生成+人手検証**: 実行時にLLMに問題を作らせない(誤出題・誤判定を防ぐ)。
  現在の `quiz_bank.json` はサンプルなので、講義内容から作った検証済みデータに差し替える。

## 現状 / 次にやること
- [x] **Phase 1**: 頭脳(テキスト)— Claude + tool use + 交渉/クイズ/報酬 + RAG。検証済み。
- [ ] **Phase 0**: データ前処理 — 講義動画の文字起こし・Discord エクスポート・Qdrant 投入・
      クイズバンク生成と人手検証。(実データ待ち。並行で最優先に着手したい)
- [x] **Phase 2**: Next.js 2画面 + WebSocketルーム + QR連携。テキスト会話がスマホ↔大画面で流れる。
      ルーム排他・床値秘匿を検証済み(音声/決済は次段階)。
- [x] **Phase 3**: 音声化。出力側=VOICEVOX音声+アバター口パク+字幕。
      入力側=スマホの「押して話す」→ faster-whisper 文字起こし → 会話。
      (音声認識/合成は外部の起動が要る。未起動でも文字入力・字幕で動く)
- [~] **Phase 4**: 決済 — スマホでMetaMask送金 → バックエンドがオンチェーン検証 → 解錠待ちON →
      ESP32が `/gacha/poll` で解錠。ソフト側は実装・検証済み(決済検証7/7)。
      残り=ESP32ファーム(ハード部品確定後に作成)。Dockerfile も用意済み(研究室GPU向け)。
- [ ] **Phase 5**: ペルソナ調整・当日の保険(手動解錠・フォールバック・ウォームアップ)・通しリハーサル。
