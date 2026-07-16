// ICHIGO(Optimism 上の ERC-20)を MetaMask で送金する。
// 既存決済サイト(ICHIGO_game / ichigo-pay.js)と同じ設定・同じ流れを踏襲。
// ★テスト時は受取先を自分のアドレスにするとトークンが戻る(NEXT_PUBLIC_GACHA_WALLET で上書き)。
import { BrowserProvider, Contract, parseUnits } from "ethers";

const TOKEN_ADDR =
  process.env.NEXT_PUBLIC_ICHIGO_TOKEN || "0x836700463Dce76D9Cc3CDf6F6EDF946312c01869";
const GAME_WALLET =
  process.env.NEXT_PUBLIC_GACHA_WALLET || "0x0d9Ff88703b8bcB42ca7e526246C2dcf9A4aEdb9";

// 通常ブラウザ(Chrome等)には window.ethereum が無い。MetaMask アプリ内ブラウザで
// 開き直すためのディープリンク。metamask.app.link/dapp/ は「スキーム無し」のURLを取る。
//   例) https://app.vercel.app/play?room=ABCD
//       → https://metamask.app.link/dapp/app.vercel.app/play?room=ABCD
export function metamaskDeepLink(url: string): string {
  const stripped = url.replace(/^https?:\/\//, "");
  return `https://metamask.app.link/dapp/${stripped}`;
}

const OPTIMISM = {
  chainId: "0xa", // 10 = Optimism
  chainName: "OP Mainnet",
  nativeCurrency: { name: "Ether", symbol: "ETH", decimals: 18 },
  rpcUrls: ["https://mainnet.optimism.io"],
  blockExplorerUrls: ["https://optimistic.etherscan.io"],
};

const ERC20_ABI = [
  "function decimals() view returns (uint8)",
  "function balanceOf(address) view returns (uint256)",
  "function transfer(address to, uint256 amount) returns (bool)",
];

async function switchToOptimism(eth: any) {
  try {
    await eth.request({ method: "wallet_switchEthereumChain", params: [{ chainId: OPTIMISM.chainId }] });
  } catch (e: any) {
    if (e?.code === 4902) {
      await eth.request({ method: "wallet_addEthereumChain", params: [OPTIMISM] });
    } else {
      throw e;
    }
  }
}

// amount ICHIGO を受取先へ送金し、確定を待って {hash, address} を返す。
export async function payIchigo(
  amount: number,
  onStatus?: (msg: string) => void,
): Promise<{ hash: string; address: string }> {
  const eth = (window as any).ethereum;
  if (!eth) throw new Error("MetaMask が見つかりません。");

  const provider = new BrowserProvider(eth);
  await provider.send("eth_requestAccounts", []);
  await switchToOptimism(eth);

  const signer = await provider.getSigner();
  const address = await signer.getAddress();
  const token = new Contract(TOKEN_ADDR, ERC20_ABI, signer);

  let decimals = 18;
  try {
    decimals = Number(await token.decimals());
  } catch {}

  const value = parseUnits(String(amount), decimals);
  const bal: bigint = await token.balanceOf(address);
  if (bal < value) throw new Error(`ICHIGO が足りません(必要 ${amount})。`);

  onStatus?.("MetaMask で送金を承認してください…");
  const tx = await token.transfer(GAME_WALLET, value);
  onStatus?.("送金を確認中…(数秒)");
  await tx.wait();
  return { hash: tx.hash, address };
}
