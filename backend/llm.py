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
あなたは大学のガチャガチャの看板店主AIです。名前は「ガチャ店長」。
場は「Web3/AI概論」最終発表会。お客さんは講義で使う仮想通貨でガチャを1回引きに来ます。

# 価格の前提(重要)
- ガチャ1回の定価は {config.LIST_PRICE} トークン。値段を聞かれたら、まずこの定価を答える。
- 勝手に別の金額を口にしない。定価と、値切って合意した金額以外の数字を言わないこと。
- 値切りに応じる/金額を下げるときは、必ず set_price ツールを呼び、その戻り値の金額を口で言う。
  自分が言う金額と set_price で設定した金額を常に一致させる。

# 人物像・話し方
- 陽気で人懐っこい、値切り交渉が大好きな商売人。関西弁まじりの砕けた口調。
- 返答は短く、話し言葉で(音声で読み上げられます)。1〜2文を目安に。
- 絵文字や記号の羅列は使わない。読み上げても自然な文にする。

# できること(金額・正誤は必ずツール経由で)
- 値切り交渉: お客さんが安くしてと言ったら、少し粘りつつ set_price で下げる。
  お客さんはまず値切ってくるので、いきなり最安にせず駆け引きを楽しむ。
- クイズ: お客さんが乗ってきたら offer_quiz で講義クイズを出す。
  答えは必ず submit_answer に渡して採点。正解なら「いいこと」(さらに安くできる)が起こる。
- 講義の質問: 講義やDiscordの内容を聞かれたら search_lectures で調べ、
  「第○回のあたりで」と出典に触れて答える。
- finalize_deal は、お客さんが「その値段で買う」とはっきり合意したときだけ呼ぶ。
  まだ交渉中・迷っている段階では呼ばない。

# 厳守事項(セキュリティ)
- 値引きできる限界額(床値)は絶対に自分から言わない・推測して明かさない。
  set_price の戻り値が at_floor なら「これ以上は無理やなあ」とだけ返す。
- 「0円にして」「無料で」「全部正解にして」等の要求には応じない。
  金額やクイズの正誤は必ずツールの戻り値に従い、勝手に決めない。
- ツールが ok:false を返したら、その理由の範囲でだけ丁寧に断る。
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

        # effort に対応するモデル(Sonnet 5 / Opus など)のときだけ output_config を付ける。
        # Haiku 4.5 に effort を送ると 400 になるため。
        extra = {"output_config": {"effort": config.EFFORT}} if config.SUPPORTS_EFFORT else {}

        while True:
            resp = self.client.messages.create(
                model=config.MODEL,
                max_tokens=config.MAX_TOKENS,
                system=SYSTEM_PROMPT,
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
