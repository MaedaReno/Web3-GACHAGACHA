"""クイズ下書き生成(Phase 0)。

講義の文字起こしを根拠に、Claude でクイズ候補を生成する。生成物は **下書き** であり、
必ず人手で検証してから本番のクイズバンクに採用する(誤答判定を防ぐための方針)。

  入力: {INGEST_DATA}/lectures/*.json(transcribe.py の出力)
  出力: ingest/quiz_candidates.json(needs_review=true 付き)

検証フロー:
  1) このスクリプトで候補を生成
  2) quiz_candidates.json を人が読み、問題・答え・難易度を修正/取捨
  3) 良いものを ingest/quiz_bank.json に移し、needs_review / source_text を削る
     (game.py が読むのは id / difficulty / question / answers。余分なキーは無害)

使い方:
    python ingest/gen_quiz.py                  # 全講義から生成
    python ingest/gen_quiz.py --per-lecture 5  # 1講義あたり5問

課金: Claude API を使う(既定は config の GACHA_MODEL=haiku で激安)。
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend import config  # noqa: E402

PROMPT = """\
あなたは大学「Web3/AI概論」の講義から、口頭で出題できる短答クイズを作る出題者です。
以下の講義書き起こし(抜粋)だけを根拠に、事実が明確に確認できる問題を作ってください。

# 要件
- {n} 問。難易度 easy / normal / hard をなるべく散らす。
- 質問は 1 文、口で読み上げて自然な日本語。
- 答えは短い語句(単語〜数語)。表記ゆれを許すため answers に別表記も入れる
  (例: ["スマートコントラクト", "smart contract", "スマコン"])。
- 書き起こしから答えが一意に定まるものだけ。曖昧・主観・複数正解になり得るものは避ける。
- source_text に、根拠となった書き起こしの該当部分を短く引用する。

# 出力(厳密な JSON。前後に説明文を付けない)
{{"quizzes": [
  {{"difficulty": "easy|normal|hard",
    "question": "…?",
    "answers": ["…", "…"],
    "source_text": "根拠の引用"}}
]}}

# 講義: {lecture}
# 書き起こし:
{body}
"""


def _lecture_bodies() -> dict[str, str]:
    """講義名 → 結合した本文。"""
    lec_dir = os.path.join(config.INGEST_DATA_DIR, "lectures")
    bodies: dict[str, list[str]] = {}
    for path in sorted(glob.glob(os.path.join(lec_dir, "*.json"))):
        with open(path, encoding="utf-8") as f:
            segs = json.load(f)
        for s in segs:
            bodies.setdefault(s["lecture"], []).append(s["text"])
    # 長すぎる講義は先頭を中心に上限文字数で切る(コスト抑制)
    limit = 6000
    return {k: "".join(v)[:limit] for k, v in bodies.items()}


def _extract_json(text: str) -> dict:
    """応答から JSON オブジェクトを取り出す(コードフェンス等に強く)。"""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise ValueError("JSON が見つかりません")
    return json.loads(m.group(0))


def generate(per_lecture: int) -> list[dict]:
    import anthropic

    client = anthropic.Anthropic()
    bodies = _lecture_bodies()
    if not bodies:
        sys.exit("講義データがありません。先に transcribe.py を実行してください。")

    extra = {"output_config": {"effort": config.EFFORT}} if config.SUPPORTS_EFFORT else {}
    out: list[dict] = []
    seq = 0
    for lecture, body in bodies.items():
        print(f"[{lecture}] 生成中 …")
        resp = client.messages.create(
            model=config.MODEL,
            max_tokens=2048,
            messages=[{
                "role": "user",
                "content": PROMPT.format(n=per_lecture, lecture=lecture, body=body),
            }],
            **extra,
        )
        text = "".join(b.text for b in resp.content if b.type == "text")
        try:
            data = _extract_json(text)
        except Exception as e:  # noqa: BLE001
            print(f"  ⚠ パース失敗({e})。この講義はスキップします。")
            continue
        for q in data.get("quizzes", []):
            seq += 1
            out.append({
                "id": f"q-{seq:03d}",
                "difficulty": q.get("difficulty", "normal"),
                "question": q.get("question", "").strip(),
                "answers": [a.strip() for a in q.get("answers", []) if a.strip()],
                "source": lecture,
                "source_text": q.get("source_text", "").strip(),
                "needs_review": True,
            })
        print(f"  → {len(data.get('quizzes', []))} 問")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="講義からクイズ候補を生成(要人手検証)")
    ap.add_argument("--per-lecture", type=int, default=5, help="1講義あたりの問題数")
    ap.add_argument(
        "--out",
        default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "quiz_candidates.json"),
        help="出力ファイル",
    )
    args = ap.parse_args()

    quizzes = generate(args.per_lecture)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(quizzes, f, ensure_ascii=False, indent=2)
    print(f"\n→ {args.out}({len(quizzes)} 問の下書き)")
    print(
        "⚠ これは下書きです。人が検証し、良問だけ needs_review/source_text を外して "
        "ingest/quiz_bank.json に移してください。"
    )


if __name__ == "__main__":
    main()
