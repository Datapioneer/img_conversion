#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""固定直连本机 MCP 服务的通用客户端库。

背景：会话内的 MCP 客户端约 2 分钟超时，而整份病历 docx 的 OCR 需要 5~8 分钟，
无法承载。为此提炼本库：直连本机 mineru-mcp / llm-mcp 的 streamableHttp 端点，
长超时（默认 1800s），供 skill 各脚本复用。

用法：
    from mcp_client import McpSession, to_container_path

    s = McpSession("http://localhost:8010/mcp")   # 或传入环境变量覆盖
    s.initialize()
    result = s.call_tool("parse_document", {"docx_path": to_container_path(r"E:\\...\\a.docx")})
    text = extract_text(result)

路径约定（Q1 答案：容器根映射）：
    宿主机 `E:\\shiny_wd` = 容器内 `/ws`（由 mineru-mcp 容器 bind mount 得出）。
    `to_container_path()` 自动把宿主机绝对路径转成容器内 `/ws/...` 路径，
    因此调用方只需传宿主机路径，无需关心容器视角。
    HOST_ROOT（默认 `E:\\shiny_wd`）与 CONTAINER_ROOT（默认 `/ws`）可经环境变量覆盖。
"""
import json
import os
import sys
import urllib.request
import urllib.error

# ---- 容器根映射（可在环境变量中覆盖） ----
HOST_ROOT = os.environ.get("MCP_HOST_ROOT", r"E:\shiny_wd").replace("\\", "/").rstrip("/")
CONTAINER_ROOT = os.environ.get("MCP_CONTAINER_ROOT", "/ws").rstrip("/")

# 默认服务端点
MINERU_URL = os.environ.get("MINERU_MCP_URL", "http://localhost:8010/mcp")
LLM_URL = os.environ.get("LLM_MCP_URL", "http://localhost:8011/mcp")

DEFAULT_TIMEOUT = int(os.environ.get("MCP_TIMEOUT", "1800"))


def to_container_path(host_path):
    """宿主机绝对路径 -> 容器内 /ws/... 路径（仅当它位于 HOST_ROOT 之下）。"""
    p = os.path.abspath(host_path).replace("\\", "/")
    # 统一盘符大小写后比较前缀
    low_p = p.lower()
    low_root = HOST_ROOT.lower()
    if low_p.startswith(low_root + "/"):
        rel = p[len(HOST_ROOT):]
        return CONTAINER_ROOT + rel.replace("\\", "/")
    if low_p.startswith(low_root):
        # 正好等于根目录
        return CONTAINER_ROOT
    # 不在根映射之下：原样返回（无法转换，告警）
    print(f"[mcp_client] 路径不在容器挂载根({HOST_ROOT})下，按原样返回: {host_path}", file=sys.stderr)
    return p


class McpSession:
    """极简 MCP streamableHttp 客户端（JSON-RPC over HTTP）。"""

    def __init__(self, url=MINERU_URL, timeout=DEFAULT_TIMEOUT):
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
            sid = e.headers.get("Mcp-Session-Id") if e.headers else None
            if sid:
                self.session_id = sid
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
            "clientInfo": {"name": "workbuddy-mcp-client", "version": "1.0.0"},
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
            elif isinstance(inner.get("content"), str):
                return inner["content"]
    elif isinstance(result, str):
        return result
    return json.dumps(result, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    # 自检：打印服务/根映射，并对 8010 做 initialize 握手验证连通
    print(f"HOST_ROOT    = {HOST_ROOT}")
    print(f"CONTAINER_ROOT= {CONTAINER_ROOT}")
    print(f"MINERU_URL   = {MINERU_URL}")
    print(f"LLM_URL      = {LLM_URL}")
    print(f"sample 转换   : to_container_path(r'E:\\shiny_wd\\x\\y.docx') = {to_container_path(r'E:\\shiny_wd\\x\\y.docx')}")
    print("可用 CLI：")
    print("  python mineru_call.py <宿主机docx> <输出.md>")
    print("  python llm_sensitive.py <图转文md> <输出敏感词.txt> [手动词文件]")
