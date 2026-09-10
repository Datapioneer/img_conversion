#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""固定直连远程服务的通用客户端库（纯 stdlib，无第三方依赖）。

背景：会话内的 MCP 客户端约 2 分钟超时，而整份病历 docx 的 OCR 需要 5~8 分钟，
无法承载。为此提炼本库：长超时（默认 1800s）直连远程服务，供 skill 各脚本复用。

部署变迁（2026-09 移机）：
- 旧：本机 Docker 容器 mineru-mcp(8010) / llm-mcp(8011)，MCP streamableHttp，
  docx 走容器路径映射（E:\\shiny_wd -> /ws）。
- 新：MinerU 官方 FastAPI 服务部署在 WSL 机器 http://10.20.79.38:8888
  （/file_parse 上传解析、/tasks 异步任务、/health 健康检查）；
  脱敏 LLM 为同机 Ollama http://10.20.79.38:11434（qwen3:32b，/api/chat）。
  文件以 multipart 上传，不再需要任何路径映射。

用法：
    from mcp_client import mineru_file_parse, ollama_chat

    md = mineru_file_parse([("img1.png", b"..."), ("img2.jpg", b"...")],
                            backend="pipeline")
    answer = ollama_chat("识别敏感词的提示词...", model="qwen3:32b")

环境变量可覆盖默认端点：
    MINERU_API_URL（默认 http://10.20.79.38:8888）
    OLLAMA_URL   （默认 http://10.20.79.38:11434）
    MCP_TIMEOUT  （默认 1800 秒）
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid

# ---- 默认服务端点（可在环境变量中覆盖） ----
MINERU_API_URL = os.environ.get("MINERU_API_URL", "http://10.20.79.38:8888").rstrip("/")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://10.20.79.38:11434").rstrip("/")

DEFAULT_TIMEOUT = int(os.environ.get("MCP_TIMEOUT", "1800"))

# MinerU 可接受的图片/文件扩展名（docx 内嵌的其他格式如 wmf/emf 会被跳过）
RASTER_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".gif", ".webp", ".jfif"}


# ---------------------------------------------------------------- MinerU ----

def _build_multipart(files, fields=None):
    """构造 multipart/form-data 请求体。

    files:  [(filename, bytes), ...]
    fields: {name: str_value, ...}
    返回 (body_bytes, content_type)
    """
    boundary = "----workbuddy" + uuid.uuid4().hex
    lines = []
    for name, value in (fields or {}).items():
        lines.append(f"--{boundary}\r\n"
                     f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                     f"{value}\r\n".encode("utf-8"))
    for filename, data in files:
        lines.append((f"--{boundary}\r\n"
                      f'Content-Disposition: form-data; name="files"; '
                      f'filename="{filename}"\r\n'
                      f"Content-Type: application/octet-stream\r\n\r\n").encode("utf-8"))
        lines.append(data)
        lines.append(b"\r\n")
    lines.append(f"--{boundary}--\r\n".encode("utf-8"))
    body = b"".join(lines)
    return body, f"multipart/form-data; boundary={boundary}"


def mineru_health(timeout=10):
    """GET /health，返回 (ok, info_dict)。"""
    try:
        with urllib.request.urlopen(f"{MINERU_API_URL}/health", timeout=timeout) as resp:
            return True, json.loads(resp.read().decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        return False, {"error": str(e)}


def mineru_file_parse(files, backend="pipeline", parse_method="auto",
                      lang_list=("ch",), timeout=None, poll_interval=5.0,
                      service=None):
    """上传文件到远程 MinerU 解析，返回 {文件名(去扩展名): md_content}。

    files:   [(filename, bytes), ...] —— 同名文件会互相覆盖结果键，调用方应保证唯一
    backend: pipeline（无幻觉，OCR 图片首选）/ hybrid-auto-engine（默认，数字文档）
    service: MinerU API 根地址（默认取 MINERU_API_URL）
    长任务内部自动轮询 /tasks/{task_id} 直至完成，规避长连接被掐断。

    返回 dict；任务失败抛 RuntimeError（含服务端 error 信息）。
    """
    timeout = timeout or DEFAULT_TIMEOUT
    base = (service or MINERU_API_URL).rstrip("/")
    if not files:
        raise ValueError("files 不能为空")
    fields = {
        "return_md": "true",
        "backend": backend,
        "parse_method": parse_method,
        "lang_list": "ch" if not lang_list else ",".join(lang_list),
    }
    body, ctype = _build_multipart(files, fields)
    req = urllib.request.Request(
        f"{base}/file_parse", data=body,
        headers={"Content-Type": ctype}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"MinerU HTTP {e.code}: {detail}") from e

    status = data.get("status")
    # 同步端点正常直接返回 completed；若仍在排队/处理，转异步轮询
    if status not in ("completed", "done", "finished"):
        task_id = data.get("task_id")
        if not task_id:
            raise RuntimeError(f"MinerU 返回异常状态 {status!r}: {str(data)[:500]}")
        data = _wait_task(task_id, base=base, timeout=timeout, poll_interval=poll_interval)

    if data.get("status") != "completed":
        raise RuntimeError(f"MinerU 任务失败: {data.get('error') or data.get('status')}")

    results = data.get("results") or {}
    out = {}
    for key, val in results.items():
        if isinstance(val, dict):
            md = val.get("md_content")
            if md is None and val.get("md"):
                md = val["md"]
            out[key] = md or ""
        else:
            out[key] = str(val)
    return out


def _wait_task(task_id, base=None, timeout=1800, poll_interval=5.0):
    """轮询异步任务直至完成（GET /tasks/{task_id} -> /tasks/{task_id}/result）。"""
    base = (base or MINERU_API_URL).rstrip("/")
    deadline = time.time() + timeout
    while time.time() < deadline:
        with urllib.request.urlopen(f"{base}/tasks/{task_id}", timeout=60) as resp:
            st = json.loads(resp.read().decode("utf-8"))
        status = st.get("status")
        if status in ("completed", "failed", "error"):
            break
        print(f"[mineru] 任务 {task_id[:8]}... 状态 {status}，等待 {poll_interval:.0f}s ...",
              file=sys.stderr)
        time.sleep(poll_interval)
    else:
        raise RuntimeError(f"MinerU 任务 {task_id} 超时（>{timeout}s）")
    if status != "completed":
        raise RuntimeError(f"MinerU 任务失败: {st.get('error') or status}")
    with urllib.request.urlopen(f"{base}/tasks/{task_id}/result", timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ---------------------------------------------------------------- Ollama ----

def ollama_chat(prompt, model="qwen3:32b", system=None, temperature=0.2,
                timeout=None, num_ctx=None, service=None):
    """调用 Ollama /api/chat，返回去噪后的文本。

    service: Ollama API 根地址（默认取 OLLAMA_URL）
    qwen3 系列会返回独立 thinking 字段；若内容里
    也会被剥离。返回空串表示模型没有产出内容。
    """
    timeout = timeout or DEFAULT_TIMEOUT
    base = (service or OLLAMA_URL).rstrip("/")
    payload = {
        "model": model,
        "messages": ([{"role": "system", "content": system}] if system else [])
        + [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {"temperature": temperature},
    }
    if num_ctx:
        payload["options"]["num_ctx"] = num_ctx
    req = urllib.request.Request(
        f"{base}/api/chat", data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"Ollama HTTP {e.code}: {detail}") from e

    msg = data.get("message") or {}
    content = (msg.get("content") or "").strip()
    if "<think>" in content:  # 兼容旧版 Ollama 把思考混在 content 里的情况
        if "</think>" in content:
            content = content.split("</think>", 1)[1].strip()
        else:
            content = content.split("<think>", 1)[1].strip()
    return content


def ollama_list_models(timeout=10):
    """GET /api/tags，返回模型名列表。"""
    with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return [m.get("name") for m in data.get("models", [])]


# ------------------------------------------------- 兼容保留：MCP 通用会话 ----
# 旧版直连 mineru-mcp / llm-mcp 的 JSON-RPC 客户端。当前部署已不再使用，
# 保留以备将来仍有 MCP 服务需要长超时直连时复用。

class McpSession:
    """极简 MCP streamableHttp 客户端（JSON-RPC over HTTP）。"""

    def __init__(self, url, timeout=DEFAULT_TIMEOUT):
        self.url = url
        self.timeout = timeout
        self.session_id = None
        self.req_id = 0

    def _next_id(self):
        self.req_id += 1
        return self.req_id

    def call(self, method, params=None, is_notification=False):
        payload = {"jsonrpc": "2.0", "method": method}
        if not is_notification:
            payload["id"] = self._next_id()
        if params is not None:
            payload["params"] = params

        data = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id

        req = urllib.request.Request(self.url, data=data, headers=headers, method="POST")
        try:
            resp = urllib.request.urlopen(req, timeout=self.timeout)
            sid = resp.headers.get("Mcp-Session-Id")
            if sid:
                self.session_id = sid
            raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            print(f"[mcp_client] HTTP {e.code}: {body[:500]}", file=sys.stderr)
            raise
        return self._parse_response(raw)

    def _parse_response(self, raw):
        if not raw.strip():
            return None
        if "data:" in raw:
            for line in raw.split("\n"):
                line = line.strip()
                if line.startswith("data:"):
                    data_str = line[5:].strip()
                    if data_str:
                        return json.loads(data_str)
            return None
        return json.loads(raw)

    def initialize(self):
        params = {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "workbuddy-mcp-client", "version": "1.2.0"},
        }
        resp = self.call("initialize", params)
        self.call("notifications/initialized", is_notification=True)
        return resp

    def list_tools(self):
        return self.call("tools/list")

    def call_tool(self, name, arguments=None):
        return self.call("tools/call", {"name": name, "arguments": arguments or {}})


def extract_text(result):
    """从 tools/call 的响应里取出 text 内容（兼容 list / dict / str）。"""
    if isinstance(result, dict):
        inner = result.get("result", result)
        if isinstance(inner, dict):
            content_list = inner.get("content", [])
            if isinstance(content_list, list):
                texts = []
                for item in content_list:
                    if isinstance(item, dict) and item.get("type") == "text":
                        texts.append(item.get("text", ""))
                return "\n".join(texts)
            if isinstance(inner.get("content"), str):
                return inner["content"]
    elif isinstance(result, str):
        return result
    return json.dumps(result, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    # 自检：打印端点并做连通性验证
    print(f"MINERU_API_URL = {MINERU_API_URL}")
    print(f"OLLAMA_URL     = {OLLAMA_URL}")
    print(f"DEFAULT_TIMEOUT= {DEFAULT_TIMEOUT}s")
    ok, info = mineru_health()
    print(f"MinerU /health : {'OK' if ok else '不可达'} {info.get('version', '') or info}")
    try:
        models = ollama_list_models()
        print(f"Ollama /api/tags: OK, 模型数 {len(models)}，含 qwen3:32b: {'qwen3:32b' in models}")
    except Exception as e:  # noqa: BLE001
        print(f"Ollama /api/tags: 不可达 ({e})")
    print("可用 CLI：")
    print("  python mineru_call.py <docx> <输出.md>")
    print("  python llm_sensitive.py <图转文md> <输出敏感词txt> [手动词文件]")
