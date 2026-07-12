"""payment.verify_payment の検証(チェーン非接続・無料)。

get_receipt を差し替えて、受領書(receipt)の各パターンを与える。

    python -m backend.test_payment
"""

from . import config, payment

DEC = config.TOKEN_DECIMALS
WALLET = config.GACHA_WALLET
USER = "0x1111111111111111111111111111111111111111"


def _topic(addr: str) -> str:
    return "0x" + "0" * 24 + addr[2:].lower()


def _receipt(to_addr, from_addr, tokens, status="0x1", token=None):
    return {
        "status": status,
        "logs": [{
            "address": token or config.ICHIGO_TOKEN_ADDR,
            "topics": [payment.TRANSFER_SIG, _topic(from_addr), _topic(to_addr)],
            "data": hex(int(tokens * (10 ** DEC))),
        }],
    }


def _patch(receipt):
    payment.get_receipt = lambda tx_hash: receipt  # noqa: E731


def test_valid_payment():
    _patch(_receipt(WALLET, USER, 250))
    r = payment.verify_payment("0xaaa1", USER, 250)
    assert r["ok"] is True, r


def test_wrong_recipient():
    _patch(_receipt("0x2222222222222222222222222222222222222222", USER, 250))
    r = payment.verify_payment("0xaaa2", USER, 250)
    assert r["ok"] is False


def test_underpaid():
    _patch(_receipt(WALLET, USER, 100))
    r = payment.verify_payment("0xaaa3", USER, 250)
    assert r["ok"] is False and "不足" in r["reason"]


def test_failed_tx():
    _patch(_receipt(WALLET, USER, 250, status="0x0"))
    r = payment.verify_payment("0xaaa4", USER, 250)
    assert r["ok"] is False


def test_wrong_sender():
    _patch(_receipt(WALLET, "0x9999999999999999999999999999999999999999", 250))
    r = payment.verify_payment("0xaaa5", USER, 250)
    assert r["ok"] is False


def test_replay_rejected():
    _patch(_receipt(WALLET, USER, 250))
    assert payment.verify_payment("0xdup", USER, 250)["ok"] is True
    # 同じ hash の二度目は拒否(二重解錠防止)
    assert payment.verify_payment("0xdup", USER, 250)["ok"] is False


def test_overpay_ok():
    _patch(_receipt(WALLET, USER, 300))
    assert payment.verify_payment("0xaaa6", USER, 250)["ok"] is True


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"  ok: {fn.__name__}")
    print(f"\n{len(fns)}/{len(fns)} passed")


if __name__ == "__main__":
    _run_all()
