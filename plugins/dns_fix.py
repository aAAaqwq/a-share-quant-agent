"""
DNS + 代理 修复补丁 — 东方财富域名 DNS 污染 + 代理拦截绕过

问题：
1. 本机 DNS 被 Clash/Surge 劫持 → push2.eastmoney.com 解析到 198.18.0.233
2. 即使 DNS 修复后，系统代理（TUN/SOCKS）仍然拦截到 Eastmoney 的请求

修复：
1. 硬编码正确 IP（DNS-over-HTTPS 三源交叉验证）
2. 清除代理环境变量（让 requests 直连）

使用方法：在任何 akshare 调用之前 import dns_fix
"""
import socket
import os

# ── 1. 清除代理环境变量 ──
# Eastmoney 域名需要直连，不能走 Clash/Surge 代理
for key in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy',
            'ALL_PROXY', 'all_proxy']:
    os.environ.pop(key, None)

# 设置 no_proxy 覆盖所有域
os.environ['NO_PROXY'] = '*'
os.environ['no_proxy'] = '*'

# ── 2. DNS 修复 ──
# DNS-over-HTTPS 查到的真实 IP（Google/Cloudflare/AliDNS 三源交叉验证）
_OVERRIDES = {
    "push2.eastmoney.com": "120.79.191.232",
    "push2ex.eastmoney.com": "119.3.232.150",
    "82.push2.eastmoney.com": "120.79.191.232",
    "push2his.eastmoney.com": "120.76.218.228",
    "datacenter-web.eastmoney.com": "120.79.191.232",
    "data.eastmoney.com": "120.76.218.228",
    "pcpz.eastmoney.com": "120.76.218.228",
    "fundf10.eastmoney.com": "120.79.191.232",
    "pdf.dfcfw.com": "120.76.218.228",
    "emweb.securities.eastmoney.com": "120.79.191.232",
}

_original_getaddrinfo = socket.getaddrinfo


def _patched_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    if host in _OVERRIDES:
        host = _OVERRIDES[host]
    return _original_getaddrinfo(host, port, family, type, proto, flags)


socket.getaddrinfo = _patched_getaddrinfo

# ── 3. Monkey-patch requests Session 禁用代理 ──
try:
    import requests
    _original_session_init = requests.Session.__init__

    def _patched_session_init(self, *args, **kwargs):
        _original_session_init(self, *args, **kwargs)
        self.trust_env = False  # 忽略系统代理设置
        self.proxies = {}       # 清空代理

    requests.Session.__init__ = _patched_session_init
except ImportError:
    pass

# ── 验证 ──
if __name__ == "__main__":
    ip = socket.getaddrinfo("push2.eastmoney.com", 443)[0][4][0]
    print(f"push2.eastmoney.com → {ip}")
    assert ip == "120.79.191.232", f"DNS fix failed: {ip}"
    print("✅ DNS + 代理 修复补丁生效")
