/**
 * 币安 fapi 反代 — Cloudflare Worker
 *
 * 用途：GitHub Actions runner 出口在美国，币安 fapi.binance.com 对其返回
 * 451 Restricted Location；Cloudflare Worker 出口不受币安地区限制。
 *
 * 部署步骤（约 5 分钟）：
 *   1. https://dash.cloudflare.com 登录（可用 GitHub 账号）
 *   2. Workers & Pages → Create application → Create Worker
 *   3. 命名（如 ict-fvg-binance）→ Deploy → Edit code
 *   4. 把下方 SCAN_KEY 改成随机字符串（如 openssl rand -hex 16 生成）
 *   5. 粘贴本文件全部代码 → Deploy
 *   6. 复制地址（https://<名字>.<子域>.workers.dev）→ 配置到仓库
 *      Secret: BINANCE_BASE_URL；SCAN_KEY 配置到 Secret: BINANCE_PROXY_KEY
 *
 * 设计：
 *   - 仅放行 GET（币安公开行情全部是 GET），拒绝其他方法
 *   ?key= 校验防滥用（校验后剥离，不透传到币安）
 *   - 透传上游状态码（451/429 等）供客户端退避逻辑使用
 */

const SCAN_KEY = "请改成随机密钥";
const UPSTREAM = "https://fapi.binance.com";

export default {
  async fetch(request) {
    if (request.method !== "GET") {
      return new Response("Method Not Allowed", { status: 405 });
    }
    const url = new URL(request.url);
    if (url.searchParams.get("key") !== SCAN_KEY) {
      return new Response("Forbidden", { status: 403 });
    }
    url.searchParams.delete("key");
    const target = UPSTREAM + url.pathname + url.search;

    const resp = await fetch(target, {
      method: "GET",
      headers: { Accept: "application/json" },
    });
    return new Response(resp.body, {
      status: resp.status,
      headers: {
        "Content-Type": resp.headers.get("Content-Type") || "application/json",
      },
    });
  },
};
