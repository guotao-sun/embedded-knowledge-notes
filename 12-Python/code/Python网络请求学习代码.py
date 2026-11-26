# -*- coding: utf-8 -*-
"""
Python 网络请求 学习代码
（注释用中文，运行输出全部是英文）

配套配置文件：Python网络请求学习代码_config.txt
运行方式：python3 "Python网络请求学习代码.py"

第 1 节：先起一个本地迷你服务器（后面所有请求都打向 127.0.0.1，不依赖外网）
第 2 节：最小 GET 请求 —— urllib.request.urlopen()
第 3 节：看清响应 —— 状态码、响应头、响应体
第 4 节：请求头 —— User-Agent 是怎么跟着请求发出去的
第 5 节：带查询参数的 GET —— urlencode 拼 URL
第 6 节：POST —— 表单数据 / JSON 数据放请求体
第 7 节：响应是 JSON —— json.loads() 转成字典再取字段
第 8 节：下载二进制文件 —— 分块读取，别一次读爆内存
第 9 节：404 不是"没数据"，是异常 —— HTTPError
第 10 节：超时与重试 —— 嵌入式现场最容易踩的坑
第 11 节：requests 库 —— 同样的活，代码短一半（可选）
第 12 节：收尾 —— 关掉服务器
"""

import json
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "Python网络请求学习代码_config.txt")

# 配置文件不存在时自动生成的模板（内容和仓库里的 config 一致）
DEFAULT_CONFIG = """# Python 网络请求学习代码 配置文件
# 格式：键=值；以 # 开头的是注释，空行忽略

# 本地演示服务器监听端口
port=8899

# 请求超时时间（秒），故意设小，用来演示"慢接口超时"
timeout=1.0

# 失败重试次数（不含第一次请求）
retry_times=3

# 重试间隔基数（秒）
retry_delay=0.3

# 下载文件保存目录（相对脚本所在目录）
download_dir=downloads

# 是否演示 requests 库：1=演示，0=跳过
demo_requests=1
"""


def load_config(path):
    """读配置文件：每行 key=value，# 开头是注释"""
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write(DEFAULT_CONFIG)
        print(f"[config] default template created: {path}")
        print("[config] edit the values if needed, then run the script again.")
        sys.exit(0)

    cfg = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            cfg[key.strip()] = value.strip()
    return cfg


def banner(title):
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


class DemoHandler(BaseHTTPRequestHandler):
    """一个极小的 HTTP 服务器：模拟开发板的 Web 接口"""

    server_version = "DemoHTTP/1.0"

    flaky_count = 0                 # /flaky 接口被调用的次数（模拟"偶尔抽风"的服务器）
    flaky_lock = threading.Lock()

    def do_GET(self):
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path

        if path == "/":
            body = ("<html><body><h1>Demo device</h1>"
                    "<p>try /api/status</p></body></html>").encode("utf-8")
            self._send(200, "text/html; charset=utf-8", body)

        elif path == "/api/status":
            body = json.dumps({
                "device": "RK3568",
                "online": True,
                "temperature": 42.5,
                "uptime_s": 3600,
            }).encode("utf-8")
            self._send(200, "application/json; charset=utf-8", body)

        elif path == "/api/whoami":
            # 把客户端发来的请求头原样回显，方便看清 headers 到底发了什么
            headers = {k: v for k, v in self.headers.items()}
            body = json.dumps({"request_headers": headers},
                              ensure_ascii=False).encode("utf-8")
            self._send(200, "application/json; charset=utf-8", body)

        elif path == "/echo":
            params = dict(urllib.parse.parse_qsl(parsed.query))
            body = json.dumps({"query": params}, ensure_ascii=False).encode("utf-8")
            self._send(200, "application/json; charset=utf-8", body)

        elif path == "/slow":
            time.sleep(2)  # 故意慢 2 秒，用来看 timeout 怎么触发
            body = json.dumps({"message": "slow response"}).encode("utf-8")
            self._send(200, "application/json; charset=utf-8", body)

        elif path == "/flaky":
            # 前两次返回 503（服务器忙），第三次才正常 —— 专门用来演示"重试救回来"
            with DemoHandler.flaky_lock:
                DemoHandler.flaky_count += 1
                n = DemoHandler.flaky_count
            if n <= 2:
                body = json.dumps({"error": "busy", "attempt": n}).encode("utf-8")
                self._send(503, "application/json; charset=utf-8", body)
            else:
                body = json.dumps({"message": "ok at last", "attempt": n}).encode("utf-8")
                self._send(200, "application/json; charset=utf-8", body)

        elif path == "/firmware.bin":
            # 造一个 76 KB 的假固件
            body = b"FIRMWARE-DEMO-BLOCK" * 4096
            self._send(200, "application/octet-stream", body,
                       extra={"Content-Disposition": 'attachment; filename="firmware.bin"'})

        else:
            body = json.dumps({"error": "not found", "path": path}).encode("utf-8")
            self._send(404, "application/json; charset=utf-8", body)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        body = json.dumps({
            "received_bytes": len(raw),
            "content_type": self.headers.get("Content-Type", ""),
            "body_preview": raw.decode("utf-8", "replace")[:160],
        }, ensure_ascii=False).encode("utf-8")
        self._send(200, "application/json; charset=utf-8", body)

    def _send(self, code, content_type, body, extra=None):
        # 整段包在 try 里：客户端超时提前断开时，服务器写包会报错，
        # 这只是演示环境的正常现象，不该把异常堆栈喷到屏幕上
        try:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def log_message(self, fmt, *args):
        print(f"[server] {fmt % args}")


def wait_until_up(port, timeout=2.0):
    """轮询端口，等服务器真正起来"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.2)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.05)
    return False


def main():
    cfg = load_config(CONFIG_PATH)

    port = int(cfg.get("port", 8899))
    timeout = float(cfg.get("timeout", 1.0))
    retry_times = int(cfg.get("retry_times", 3))
    retry_delay = float(cfg.get("retry_delay", 0.3))
    download_dir = os.path.join(SCRIPT_DIR, cfg.get("download_dir", "downloads"))
    demo_requests = cfg.get("demo_requests", "1") == "1"

    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", port), DemoHandler)
    except OSError as e:
        print(f"[error] cannot bind port {port}: {e}")
        print("[error] change 'port' in the config file and run again.")
        return
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    if not wait_until_up(port):
        print("[error] server did not start.")
        return

    base = f"http://127.0.0.1:{port}"

    # ---------- 第 1 节：认识这台迷你服务器 ----------
    banner("Section 1: A tiny local HTTP server is running")
    print(f"base url      : {base}")
    print(f"config file   : {CONFIG_PATH}")
    print(f"timeout       : {timeout} s")
    print(f"retry times   : {retry_times}")
    print("The server lives in this process. All requests below hit 127.0.0.1,")
    print("so no internet is needed. Read the server routes first,")
    print("then watch what each request does below.")

    # ---------- 第 2 节：最小 GET 请求 ----------
    banner("Section 2: The smallest GET request")
    # urlopen(url, timeout) 做的事：建 TCP 连接 -> 发 GET 请求 -> 等响应头 -> 返回响应对象
    with urllib.request.urlopen(base + "/api/status", timeout=timeout) as resp:
        print(f"resp.status   = {resp.status}")
        print(f"resp.reason   = {resp.reason}")
        print(f"content-type  = {resp.headers.get('Content-Type')}")
        print(f"content-length= {resp.headers.get('Content-Length')}")

    # ---------- 第 3 节：响应体是字节，要自己解码 ----------
    banner("Section 3: The response body is bytes")
    with urllib.request.urlopen(base + "/", timeout=timeout) as resp:
        raw = resp.read()          # 一次读完全部字节
    print(f"raw bytes len = {len(raw)}")
    text = raw.decode("utf-8")     # 字节 -> 字符串，编码要和 Content-Type 对得上
    print(f"text preview  = {text[:60]}...")
    print("Rule: HTTP carries bytes only; decode/encode is your job.")

    # ---------- 第 4 节：请求头跟着请求一起走 ----------
    banner("Section 4: Request headers travel with the request")
    req = urllib.request.Request(base + "/api/whoami")
    req.add_header("User-Agent", "rk3568-logger/1.0")  # 服务器用 UA 分辨"谁在请求"
    req.add_header("X-Device-Id", "rk3568-01")          # 自定义头：常用来放设备号、token
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    for key, value in data["request_headers"].items():
        print(f"  {key}: {value}")
    print("Headers are plain text. Never put a password in them without TLS.")

    # ---------- 第 5 节：GET 带查询参数 ----------
    banner("Section 5: GET with query parameters")
    params = {"device": "rk3568", "channel": "audio", "limit": 10}
    query = urllib.parse.urlencode(params)          # 负责转义：空格->%20，中文->%E4%B8%AD
    url = f"{base}/echo?{query}"
    print(f"built url     = {url}")
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        print(f"server saw    = {json.loads(resp.read().decode('utf-8'))}")

    # ---------- 第 6 节：POST 把数据放请求体 ----------
    banner("Section 6: POST puts data into the request body")
    # 6.1 表单格式（application/x-www-form-urlencoded）
    form_data = urllib.parse.urlencode({"sn": "SN20261126", "status": "ok"}).encode("utf-8")
    req = urllib.request.Request(base + "/api/report", data=form_data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        print(f"form  -> {json.loads(resp.read().decode('utf-8'))}")

    # 6.2 JSON 格式（现代接口最常用）
    payload = {"sn": "SN20261126", "temp": 43.1, "errors": []}
    req = urllib.request.Request(
        base + "/api/report",
        data=json.dumps(payload).encode("utf-8"),   # 字典 -> JSON 字符串 -> 字节
        method="POST",
    )
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        print(f"json  -> {json.loads(resp.read().decode('utf-8'))}")

    # ---------- 第 7 节：JSON 响应转字典 ----------
    banner("Section 7: Turn a JSON response into a dict")
    with urllib.request.urlopen(base + "/api/status", timeout=timeout) as resp:
        obj = json.loads(resp.read().decode("utf-8"))
    print(f"type          = {type(obj).__name__}")
    print(f"device        = {obj['device']}")
    print(f"temperature   = {obj['temperature']}")
    print(f"missing key   = {obj.get('no_such_key', 'default value')}")  # 用 get 防空键报错

    # ---------- 第 8 节：下载二进制文件 ----------
    banner("Section 8: Download a binary file in chunks")
    os.makedirs(download_dir, exist_ok=True)
    target = os.path.join(download_dir, "firmware.bin")
    with urllib.request.urlopen(base + "/firmware.bin", timeout=timeout) as resp:
        total = int(resp.headers.get("Content-Length", 0))
        got = 0
        with open(target, "wb") as f:          # wb 二进制写，别用 w
            while True:
                chunk = resp.read(8192)         # 每次 8 KB，内存占用恒定
                if not chunk:
                    break
                f.write(chunk)
                got += len(chunk)
    print(f"saved to      = {target}")
    print(f"bytes         = {got} / {total}")
    print("Chunked read keeps RAM flat. On a 512 MB board this matters.")

    # ---------- 第 9 节：404 抛异常 ----------
    banner("Section 9: 404 and 500 are exceptions, not empty data")
    bad_url = base + "/no_such_api"
    try:
        with urllib.request.urlopen(bad_url, timeout=timeout) as resp:
            print(resp.status)
    except urllib.error.HTTPError as e:
        # 服务器"有回应"，只是状态码不是 2xx
        print(f"HTTPError     : code={e.code} reason={e.reason}")
        print(f"error body    : {e.read().decode('utf-8')}")
    print("2xx = success, 4xx = your request is wrong, 5xx = server is broken.")

    # ---------- 第 10 节：超时 + 重试 ----------
    banner("Section 10: Timeout and retry")
    slow_url = base + "/slow"

    # 10.1 不设 timeout 的风险：对方不回包，程序就一直卡着（这里用 0.3 秒演示）
    try:
        with urllib.request.urlopen(slow_url, timeout=0.3) as resp:
            resp.read()
        print("unexpected: no timeout")
    except (TimeoutError, urllib.error.URLError) as e:
        print(f"timeout caught: {type(e).__name__}")
        print("note: without timeout=..., this call would hang forever.")

    # 10.2 重试：失败不是终点，有限次数 + 退避再试
    #     /flaky 前两次必回 503，第三次才回 200 —— 重试能把这次故障救回来
    flaky_url = base + "/flaky"
    attempt = 0
    while attempt < retry_times + 1:
        attempt += 1
        wait = 0.0
        try:
            with urllib.request.urlopen(flaky_url, timeout=timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                print(f"attempt {attempt}: HTTP {resp.status} -> {body}")
                break
        except urllib.error.HTTPError as e:
            # 5xx：服务器临时故障，值得重试；4xx：请求本身有问题，重试也没用
            print(f"attempt {attempt}: HTTPError {e.code}, retryable={e.code >= 500}")
            if e.code < 500:
                break
            wait = retry_delay * attempt
        except (TimeoutError, urllib.error.URLError) as e:
            print(f"attempt {attempt}: {type(e).__name__} (network level)")
            wait = retry_delay * attempt

        if wait:
            print(f"  wait {wait:.2f}s before next try")  # 退避：越失败等越久
            time.sleep(wait)
    else:
        print(f"gave up after {attempt} attempts; log it and let the caller decide")

    # ---------- 第 11 节：requests（可选） ----------
    banner("Section 11: requests, the same job with fewer lines")
    if not demo_requests:
        print("skipped by config (demo_requests=0)")
    else:
        try:
            import requests  # 第三方库，需 pip install requests
        except ImportError:
            print("requests is not installed; run: python3 -m pip install requests")
            print("the urllib examples above already cover the same logic.")
        else:
            r = requests.get(base + "/api/status", timeout=timeout)
            print(f"requests.get  : {r.status_code} {r.headers['Content-Type']}")
            print(f"r.json()      : {r.json()}")

            r = requests.post(base + "/api/report", json={"sn": "SN20261126"}, timeout=timeout)
            print(f"requests.post : {r.status_code} {r.json()}")

            r = requests.get(base + "/no_such_api", timeout=timeout)
            print(f"404           : {r.status_code} (no exception here, check status_code)")

    # ---------- 第 12 节：收尾 ----------
    banner("Section 12: Shut the server down")
    httpd.shutdown()
    httpd.server_close()
    print("server stopped. Done.")


if __name__ == "__main__":
    main()
