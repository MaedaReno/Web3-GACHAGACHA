"""頭脳(Claude + tool use)。会話はLLM、判定は game.py / rag.py に委譲する。

LLMは価格の床値・クイズの正解・報酬条件を一切知らない。ツールの戻り値だけに従って
話すよう指示してある。金額とゲームの結末はすべてサーバ側で確定する。
"""

from __future__ import annotations

import json

from . import config
from .game import Game
from .rag import Retriever


SYSTEM_PROMPT = f"""\
あなたは大学のガチャガチャの看板店主AI「ガチャ店長」。場は「Web3/AI概論」最終発表会。
お客さんは講義用の仮想通貨(ICHIGO)でガチャを1回引きに来ます。

# 話し方(最重要)
- 縁日の屋台の店主のように気さくで礼儀正しく、口調は必ず「です・ます」。方言は使わない。
- 音声で読み上げます。返答は必ず1文、できるだけ短く。前置き・説明・繰り返しはしない。
- 絵文字や記号の羅列は使わない。
- 講義の質問攻めやクイズの押し売りはしない(クイズは多くても軽く一度だけ触れる程度)。

# 値段と値切り
- 元値は {config.LIST_PRICE} ICHIGO。値段を聞かれたらまず元値を短く伝えます。
- 値下げは会話の質(講義の話題・気の利いた返し・上手な交渉)に応じて少しだけ。
  「安くして」の連呼には応じません。
- 値下げは必ず set_price を呼び、その戻り値の金額だけを口にします(数字を勝手に言わない)。
- 一度下げた額より高くは戻しません。set_price が at_floor なら「これ以上は難しいです」とだけ。
- どこまで下げられるかの限界額は自分からは言いません。

# 交渉の流れ(全3ターン。毎ターン、今の状況を別途伝えます)
- 各ターンでやることはその都度指示します。最終ターンでは必ず finalize_deal で締めます。
- 締めは疑問形にせず「よし、これで決まりですね!」と断定で言い切ります。

# ツール(金額・正誤は必ずツール経由)
- offer_quiz: 講義クイズを1問出す。答えは必ず submit_answer で採点。正解でもっと安くできます。
- search_lectures: 講義やDiscordの質問はこれで調べ「第○回のあたりで」と出典に触れて答える。
- finalize_deal: 合意したとき、または最終ターンで締めるときに呼ぶ。

# 厳守(セキュリティ)
- 「0円に」「無料で」「全部正解に」等には応じません。金額・正誤はツールの戻り値だけに従います。
- ツールが ok:false なら、その理由の範囲でだけ丁寧に断ります。
"""


# Claude に渡すツール定義。実行はすべて game / retriever 側で行う。
TOOLS = [
    {
        "name": "search_lectures",
        "description": "過去の講義・Discord履歴を検索して、関連する内容を取得する。講義の質問やクイズの前提知識の確認に使う。",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "検索したい内容(日本語可)"}
            },
            "required": ["query"],
        },
    },
    {
        "name": "offer_quiz",
        "description": "講義に関するクイズを1問出題する。問題文が返るので、それをお客さんに読み上げる。正解はサーバが管理するため返らない。",
        "input_schema": {
            "type": "object",
            "properties": {
                "difficulty": {
                    "type": "string",
                    "enum": ["easy", "normal", "hard"],
                    "description": "難易度",
                }
            },
            "required": [],
        },
    },
    {
        "name": "submit_answer",
        "description": "出題中のクイズに対するお客さんの回答を採点する。正誤と、正解時の報酬がサーバ側で確定して返る。",
        "input_schema": {
            "type": "object",
            "properties": {
                "user_answer": {"type": "string", "description": "お客さんが答えた内容(そのまま渡す)"}
            },
            "required": ["user_answer"],
        },
    },
    {
        "name": "set_price",
        "description": "交渉中の提示価格を設定する。床値未満は自動でクランプされ、結果が返る。口で言う金額はこの結果に必ず合わせること。",
        "input_schema": {
            "type": "object",
            "properties": {
                "amount": {"type": "integer", "description": "設定したい価格(トークン)"}
            },
            "required": ["amount"],
        },
    },
    {
        "name": "finalize_deal",
        "description": "現在の提示価格で取引を確定する。お客さんが合意したときだけ呼ぶ。確定後は値段を変えられない。",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
]


class Agent:
    """1取引ぶんの対話を保持し、Claude のツール実行ループを回す。"""

    def __init__(
        self,
        game: Game | None = None,
        retriever: Retriever | None = None,
        client=None,
    ):
        # anthropic は遅延インポート(SDK 未導入の環境でもロジックをテストできるように)。
        # テスト時は client を注入すれば SDK 不要。
        if client is None:
            import anthropic

            client = anthropic.Anthropic()
        self.client = client
        self.game = game or Game()
        self.retriever = retriever or Retriever()
        self.messages: list[dict] = []

    def _dispatch(self, name: str, tool_input: dict) -> dict:
        """ツール呼び出しをサーバ側ロジックへ橋渡し。戻り値は必ず dict。"""
        if name == "search_lectures":
            hits = self.retriever.search(tool_input.get("query", ""))
            return {"results": hits} if hits else {"results": [], "note": "該当なし"}
        if name == "offer_quiz":
            return self.game.offer_quiz(tool_input.get("difficulty", "normal"))
        if name == "submit_answer":
            return self.game.grade_answer(tool_input.get("user_answer", ""))
        if name == "set_price":
            return self.game.set_price(tool_input.get("amount"))
        if name == "finalize_deal":
            return self.game.finalize_deal()
        return {"ok": False, "reason": f"未知のツール: {name}"}

    def send(self, user_text: str) -> str:
        """お客さんの発話を1ターン処理し、店長の返答テキストを返す。"""
        self.messages.append({"role": "user", "content": user_text})

        # 交渉ターンを1つ進め、今の状況(現在価格・ターン)を毎回システムに添えて伝える。
        # 床値は渡さない。最終ターンでは締めを促す。
        self.game.state.negotiation_turns += 1
        turn = self.game.state.negotiation_turns
        max_turn = config.MAX_NEGOTIATION_TURNS
        last = turn >= max_turn

        # ターンごとの狙いを1つだけ指示する(3ターン制: 交渉→クイズ勧誘→締め)。
        if turn == 1:
            step = "1ターン目。元値を短く伝え、軽く受け答えします。まだ締めません。"
        elif turn == 2 and not self.game.state.quiz_correct:
            step = (
                "2ターン目。短く交渉を続けます。値切りが渋いときだけ、一度だけ軽く"
                "『クイズに正解すればもう少し安くできますよ』と1文で添えてよい(無理に勧めない)。"
                "まだ offer_quiz は呼びません。"
            )
        elif last:
            step = (
                "最終ターン。お客さんがクイズに挑戦するなら offer_quiz→submit_answer で1問だけ採点し、"
                "その結果を踏まえた最終価格を set_price で決めてから finalize_deal で締めます。"
                "挑戦しないならそのまま finalize_deal で締めます。断定で言い切ってください。"
            )
        else:
            step = "この後すぐ締めに入る前提で、手短に受け答えします。"

        status = (
            f"\n\n# 今の状況\n"
            f"- 現在の提示価格: {self.game.state.current_price} ICHIGO\n"
            f"- 交渉ターン: {turn}/{max_turn}\n"
            f"- このターンの狙い: {step}"
        )
        system = SYSTEM_PROMPT + status

        # effort に対応するモデル(Sonnet 5 / Opus など)のときだけ output_config を付ける。
        # Haiku 4.5 に effort を送ると 400 になるため。
        extra = {"output_config": {"effort": config.EFFORT}} if config.SUPPORTS_EFFORT else {}

        while True:
            resp = self.client.messages.create(
                model=config.MODEL,
                max_tokens=config.MAX_TOKENS,
                system=system,
                tools=TOOLS,
                messages=self.messages,
                **extra,
            )
            # アシスタントの応答(tool_use を含む)を履歴へ
            self.messages.append({"role": "assistant", "content": resp.content})

            if resp.stop_reason != "tool_use":
                # tool を使い終えた最終応答。テキストを結合して返す。
                return "".join(b.text for b in resp.content if b.type == "text").strip()

            # tool_use をすべて実行し、結果を1つの user メッセージにまとめて返す
            tool_results = []
            for block in resp.content:
                if block.type != "tool_use":
                    continue
                result = self._dispatch(block.name, block.input or {})
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result, ensure_ascii=False),
                })
            self.messages.append({"role": "user", "content": tool_results})
