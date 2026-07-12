"""決済のオンチェーン検証(Optimism / ICHIGO ERC-20)。

スマホがMetaMaskで送金 → その取引ハッシュ(tx hash)をバックエンドへ送る。
ここで Optimism を直接照会し、「受取先=GACHA_WALLET・送信元=接続ウォレット・
額≥確定額・成功・未使用のhash」を確認する。クライアントの自己申告を信じず、
サーバが独立に検証する(=server-authoritative を決済まで貫く)。

重い依存は使わず、生の JSON-RPC(urllib)で eth_getTransactionReceipt を叩く。
"""

from __future__ import annotations

import json
import urllib.request

from . import config

# ERC-20 Transfer(address,address,uint256) イベントの識別子(keccak256)
TRANSFER_SIG = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

# 使用済み tx hash(同じ送金で二重解錠させない)
_used: set[str] = set()


def _rpc(method: str, params: list, timeout: float = 15.0):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(
        config.OPTIMISM_RPC, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())
    if "error" in data:
        raise RuntimeError(data["error"])
    return data.get("result")


def get_receipt(tx_hash: str):
    """取引の受領書(receipt)を取得。未マイン/不明なら None。テストではここを差し替える。"""
    return _rpc("eth_getTransactionReceipt", [tx_hash])


def _topic_addr(topic: str) -> str:
    """32バイトの topic から下位20バイト(アドレス)を取り出す。"""
    return "0x" + topic[-40:]


def verify_payment(tx_hash: str, from_address: str, min_tokens: int) -> dict:
    """送金を検証。戻り: {ok, reason, amount_tokens?}。"""
    if not tx_hash or not isinstance(tx_hash, str):
        return {"ok": False, "reason": "取引ハッシュがありません。"}
    tx_hash = tx_hash.lower()
    if tx_hash in _used:
        return {"ok": False, "reason": "この支払いは既に使用済みです。"}

    try:
        receipt = get_receipt(tx_hash)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": f"チェーン照会に失敗しました: {e}"}
    if not receipt:
        return {"ok": False, "reason": "取引がまだ確認できません(未確定かハッシュ誤り)。"}
    if str(receipt.get("status", "")).lower() not in ("0x1", "1"):
        return {"ok": False, "reason": "取引が失敗しています。"}

    token = config.ICHIGO_TOKEN_ADDR.lower()
    wallet = config.GACHA_WALLET.lower()
    want = int(min_tokens) * (10 ** config.TOKEN_DECIMALS)
    from_address = (from_address or "").lower()

    for log in receipt.get("logs", []):
        if (log.get("address", "").lower() != token):
            continue
        topics = log.get("topics", [])
        if len(topics) < 3 or topics[0].lower() != TRANSFER_SIG:
            continue
        src = _topic_addr(topics[1]).lower()
        dst = _topic_addr(topics[2]).lower()
        amount = int(log.get("data", "0x0"), 16)
        if dst != wallet:
            continue
        if from_address and src != from_address:
            return {"ok": False, "reason": "送金元が接続ウォレットと一致しません。"}
        if amount < want:
            human = amount / (10 ** config.TOKEN_DECIMALS)
            return {"ok": False, "reason": f"支払額が不足しています(必要 {min_tokens}、受領 {human})。"}
        _used.add(tx_hash)
        return {"ok": True, "reason": "入金を確認しました。", "amount_tokens": amount / (10 ** config.TOKEN_DECIMALS)}

    return {"ok": False, "reason": "この取引に、受取先への ICHIGO 送金が見つかりません。"}
