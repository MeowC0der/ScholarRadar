# -*- coding: utf-8 -*-
"""知网访问的统一浏览器启动器：默认后台（无头）运行，并做基础反自动化伪装。

背景
----
原先各脚本用 `p.chromium.launch(channel="msedge", headless=False)` 拉起**有头**窗口，
会在用户工作时弹出并抢占焦点。这里改为：

- `headless=False` + `args=["--headless=new"]`：由浏览器自己进入新无头模式，
  playwright 不注入 old headless 参数，因此 **navigator.userAgent 不含 "Headless" 字样**
  （知网对含 Headless 的 UA 直接 403）。
- 显式覆盖 UA 为正常 Edge UA，双重保险。
- `--disable-blink-features=AutomationControlled` + init script 抹掉 `navigator.webdriver`
  等自动化痕迹。

外部可用环境变量覆盖：
    CNKI_HEADLESS=0|1   0 表示退回有头（调试时方便肉眼看页面）
"""
import os

# 与本机 Edge 主版本对齐的常规 UA（不含 Headless 字样）
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0")

# 抹除常见自动化检测痕迹
STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh', 'en']});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
window.chrome = window.chrome || {runtime: {}};
try {
  Object.defineProperty(navigator, 'permissions', {
    get: () => ({query: async () => ({state: 'granted'})})
  });
} catch (e) {}
"""

_BASE_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-dev-shm-usage",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-extensions",
    "--disable-features=Translate,OptimizationHints",
    "--lang=zh-CN",
]


def headless_enabled():
    return os.environ.get("CNKI_HEADLESS", "1").strip() not in ("0", "false", "False", "no")


def launch(p, headless=None):
    """启动 Edge。默认无头；返回 browser 对象。"""
    if headless is None:
        headless = headless_enabled()
    args = list(_BASE_ARGS)
    if headless:
        # 关键：交给浏览器自身的 new headless，保证 UA 与有头一致
        args.append("--headless=new")
    try:
        return p.chromium.launch(channel="msedge", headless=False, args=args)
    except Exception:
        # 没有 msedge channel 时退回落地的 chromium
        return p.chromium.launch(headless=headless, args=args)


def new_context(browser, cookies=None, viewport=None, **kwargs):
    """建立上下文：固定 UA、注入 stealth、可选注入 WebVPN cookies。

    额外关键字（如 accept_downloads=True）原样透传给 browser.new_context()。
    """
    opts = {
        "user_agent": UA,
        "viewport": viewport or {"width": 1440, "height": 900},
        "locale": "zh-CN",
        "timezone_id": "Asia/Shanghai",
        "ignore_https_errors": True,
    }
    opts.update(kwargs)
    ctx = browser.new_context(**opts)
    ctx.add_init_script(STEALTH_JS)
    if cookies:
        try:
            ctx.add_cookies(cookies)
        except Exception as e:
            print("[warn] add_cookies 失败: %s" % e, flush=True)
    return ctx


def open_entry(p, entry, cookies=None, wait_ms=5000, timeout=60000):
    """便捷函数：打开页面，返回 (ua, url, title, body_text)。用完自动关闭。"""
    browser = launch(p)
    try:
        ctx = new_context(browser, cookies=cookies)
        page = ctx.new_page()
        page.goto(entry, timeout=timeout, wait_until="domcontentloaded")
        page.wait_for_timeout(wait_ms)
        ua = page.evaluate("navigator.userAgent")
        url, title = page.url, page.title()
        text = page.inner_text("body")[:1500] if page.query_selector("body") else ""
        return ua, url, title, text
    finally:
        try:
            browser.close()
        except Exception:
            pass
