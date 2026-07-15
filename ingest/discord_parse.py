"""Discord 履歴の整形(Phase 0)。

DiscordChatExporter が JSON 形式で吐いたエクスポートを読み、RAG に入れやすい形へ整える。
複数チャンネル(複数ファイル)をまとめて 1 つの `ingest/data/discord.json` に書き出す。

エクスポート手順(DiscordChatExporter):
    DiscordChatExporter.Cli export -t <TOKEN> -c <CHANNEL_ID> -f Json -o out.json
  出力した JSON を `ingest/data/discord/` に置いて、このスクリプトを実行する。

出力フォーマット(build_index.py が講義と同じ経路でインデックス化できる形):
    [{"id", "lecture", "timestamp", "text", "author"}, ...]
  ("lecture" にはチャンネル名を "Discord #general" のように入れ、出典表示に流用する)

使い方:
    python ingest/discord_parse.py                      # data/discord/*.json を処理
    python ingest/discord_parse.py export1.json export2.json
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend import config  # noqa: E402


def _channel_label(data: dict) -> str:
    ch = (data.get("channel") or {}).get("name") or "unknown"
    return f"Discord #{ch}"


def _date_only(ts: str) -> str:
    """ISO タイムスタンプ → YYYY-MM-DD(出典表示用に日付だけ)。"""
    return (ts or "")[:10]


def parse_file(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    label = _channel_label(data)
    rows = []
    for msg in data.get("messages", []):
        content = (msg.get("content") or "").strip()
        if not content:
            continue  # 添付のみ・スタンプのみ等は捨てる
        author = msg.get("author") or {}
        name = author.get("nickname") or author.get("name") or "?"
        if author.get("isBot"):
            continue  # Bot の発言は知識源にしない
        rows.append({
            "id": f"discord-{msg.get('id')}",
            "lecture": label,
            "timestamp": _date_only(msg.get("timestamp", "")),
            "text": content,
            "author": name,
        })
    return rows


def main() -> None:
    default_dir = os.path.join(config.INGEST_DATA_DIR, "discord")
    ap = argparse.ArgumentParser(description="DiscordChatExporter の JSON を整形する")
    ap.add_argument(
        "files",
        nargs="*",
        help=f"エクスポート JSON。省略時は {default_dir}/*.json を処理",
    )
    ap.add_argument(
        "--out",
        default=os.path.join(config.INGEST_DATA_DIR, "discord.json"),
        help="出力ファイル",
    )
    args = ap.parse_args()

    files = args.files or sorted(glob.glob(os.path.join(default_dir, "*.json")))
    if not files:
        sys.exit(
            f"入力が見つかりません。エクスポート JSON を {default_dir}/ に置くか、"
            "引数でファイルを指定してください。"
        )

    all_rows: list[dict] = []
    for path in files:
        rows = parse_file(path)
        print(f"[{os.path.basename(path)}] {len(rows)} 件")
        all_rows.extend(rows)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(all_rows, f, ensure_ascii=False, indent=2)
    print(f"→ {args.out}(合計 {len(all_rows)} 件)")
    print("\n次は `python ingest/build_index.py` でインデックスを構築してください。")


if __name__ == "__main__":
    main()
