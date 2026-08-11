"""Codex Responses API 翻译层。

Codex CLI（0.138+）强制使用 OpenAI Responses 协议（wire_api = "responses"），
但智谱 BigModel 等国内服务商只提供 OpenAI Chat Completions 接口。本模块把
Responses 请求体翻译成 chat/completions 请求体，并把上游的非流式 / 流式响应
翻译回 Responses 格式（含 SSE 事件序列），使 Codex 可以经由本地代理使用
GLM 等仅支持 Chat Completions 的模型。
"""

import json
import time
import uuid


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _input_to_items(inp) -> list:
    """把 Responses input（字符串或 item 列表）规范化为 item 列表。"""
    if isinstance(inp, str):
        return [
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": inp}],
            }
        ]
    if isinstance(inp, list):
        return inp
    return []


def _part_text(part) -> str:
    """取 content part 中的文本；兼容 input_text / output_text / text。"""
    if not isinstance(part, dict):
        return ""
    ptype = part.get("type")
    if ptype in ("input_text", "output_text", "text"):
        return str(part.get("text") or "")
    return ""


def build_payload(body: dict) -> dict:
    """Responses 请求体 -> OpenAI chat.completions 请求体。"""
    model = body.get("model") or ""
    messages: list = []

    instructions = body.get("instructions")
    if instructions:
        messages.append({"role": "system", "content": instructions})

    for item in _input_to_items(body.get("input")):
        if not isinstance(item, dict):
            continue
        itype = item.get("type") or "message"
        if itype == "message":
            role = item.get("role") or "user"
            content = item.get("content")
            if isinstance(content, str):
                text = content
            else:
                text = "".join(_part_text(p) for p in (content or []) if isinstance(p, dict))
            if role == "assistant":
                messages.append({"role": "assistant", "content": text or ""})
            elif role in ("system", "developer"):
                # Codex 会以 developer 角色发送系统指令，但多数 OpenAI 兼容上游
                # 只认 system，统一映射为 system，避免上游报 role 不合法。
                messages.append({"role": "system", "content": text})
            else:
                messages.append({"role": role, "content": text})
        elif itype == "function_call":
            messages.append(
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": item.get("call_id") or f"call_{uuid.uuid4().hex[:24]}",
                            "type": "function",
                            "function": {
                                "name": item.get("name", ""),
                                "arguments": item.get("arguments") or "{}",
                            },
                        }
                    ],
                }
            )
        elif itype == "function_call_output":
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": item.get("call_id", ""),
                    "content": str(item.get("output") or ""),
                }
            )
        # reasoning 等其它 item 类型直接忽略

    # 去掉空消息，避免部分上游报错
    messages = [
        m
        for m in messages
        if m.get("content") is not None or m.get("tool_calls")
    ]
    if not messages:
        messages.append({"role": "user", "content": ""})

    payload: dict = {
        "model": model,
        "messages": messages,
        "stream": bool(body.get("stream")),
    }

    if body.get("max_output_tokens"):
        payload["max_tokens"] = int(body["max_output_tokens"])
    if body.get("temperature") is not None:
        payload["temperature"] = body["temperature"]
    if body.get("top_p") is not None:
        payload["top_p"] = body["top_p"]

    tools = []
    for t in body.get("tools") or []:
        if not isinstance(t, dict):
            continue
        if t.get("type") == "function":
            fn = t.get("function") or {}
            tools.append(
                {
                    "type": "function",
                    "function": {
                        # Responses 协议里 name/description/parameters 在顶层；
                        # 同时兼容 chat.completions 的嵌套 function 结构。
                        "name": t.get("name") or fn.get("name", ""),
                        "description": t.get("description") or fn.get("description", ""),
                        "parameters": t.get("parameters")
                        or fn.get("parameters")
                        or {"type": "object", "properties": {}},
                    },
                }
            )
        elif t.get("type") == "custom" and t.get("name"):
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": t.get("name"),
                        "description": t.get("description", ""),
                        "parameters": t.get("parameters")
                        or {"type": "object", "properties": {}},
                    },
                }
            )
    if tools:
        payload["tools"] = tools

    tool_choice = body.get("tool_choice")
    if tool_choice == "none":
        payload["tool_choice"] = "none"
    elif isinstance(tool_choice, dict):
        tc_type = tool_choice.get("type")
        if tc_type == "function":
            payload["tool_choice"] = {
                "type": "function",
                "function": {"name": tool_choice.get("name", "")},
            }
        elif tc_type in ("auto", "required"):
            payload["tool_choice"] = tc_type
    elif tool_choice:
        payload["tool_choice"] = tool_choice

    if payload["stream"]:
        payload["stream_options"] = {"include_usage": True}
    return payload


def _map_usage(usage: dict) -> dict:
    return {
        "input_tokens": usage.get("prompt_tokens", 0) or 0,
        "output_tokens": usage.get("completion_tokens", 0) or 0,
        "total_tokens": usage.get("total_tokens", 0) or 0,
    }


def _message_item(item_id: str, text: str) -> dict:
    return {
        "id": item_id,
        "type": "message",
        "status": "completed",
        "role": "assistant",
        "content": [{"type": "output_text", "text": text, "annotations": []}],
    }


def _function_call_item(item_id: str, name: str, arguments: str, call_id: str) -> dict:
    return {
        "id": item_id,
        "type": "function_call",
        "status": "completed",
        "name": name,
        "arguments": arguments,
        "call_id": call_id,
    }


def translate_response(data: dict, model: str) -> dict:
    """OpenAI 非流式 chat.completions 响应 -> Responses 响应体。"""
    choices = data.get("choices") or []
    usage = _map_usage(data.get("usage") or {})
    if not choices:
        raise ValueError("上游响应缺少 choices")
    msg = choices[0].get("message") or {}

    output = []
    if msg.get("content"):
        output.append(_message_item(f"msg_{uuid.uuid4().hex}", msg["content"]))
    for tc in msg.get("tool_calls") or []:
        fn = tc.get("function") or {}
        output.append(
            _function_call_item(
                f"fc_{uuid.uuid4().hex}",
                fn.get("name", ""),
                fn.get("arguments") or "{}",
                tc.get("id") or f"call_{uuid.uuid4().hex}",
            )
        )

    finish = choices[0].get("finish_reason")
    return {
        "id": f"resp_{uuid.uuid4().hex}",
        "object": "response",
        "created_at": int(time.time()),
        "status": "incomplete" if finish == "length" else "completed",
        "model": model,
        "output": output,
        "parallel_tool_calls": True,
        "usage": usage,
    }


def translate_stream(chunks, model: str, response_id: str | None = None):
    """OpenAI 流式分片（dict 迭代器）-> Responses SSE 事件 (event, data) 序列。"""
    rid = response_id or _new_id("resp")
    created = int(time.time())

    def _stub() -> dict:
        return {
            "id": rid,
            "object": "response",
            "created_at": created,
            "status": "in_progress",
            "model": model,
            "output": [],
            "parallel_tool_calls": True,
        }

    yield ("response.created", {"type": "response.created", "response": _stub()})
    yield ("response.in_progress", {"type": "response.in_progress", "response": _stub()})

    text_item_id = None
    text_out_idx = None
    text_buf = ""
    tool_items = {}
    tool_order = []
    output_counter = 0
    usage = {}
    finish = None

    for chunk in chunks:
        if not isinstance(chunk, dict):
            continue
        if chunk.get("usage"):
            usage = chunk["usage"]
        for ch in chunk.get("choices") or []:
            if ch.get("finish_reason"):
                finish = ch["finish_reason"]
            delta = ch.get("delta") or {}

            content = delta.get("content")
            if content:
                if text_item_id is None:
                    text_item_id = _new_id("msg")
                    text_out_idx = output_counter
                    output_counter += 1
                    yield (
                        "response.output_item.added",
                        {
                            "type": "response.output_item.added",
                            "output_index": text_out_idx,
                            "item": {
                                "id": text_item_id,
                                "type": "message",
                                "status": "in_progress",
                                "role": "assistant",
                                "content": [],
                            },
                        },
                    )
                    yield (
                        "response.content_part.added",
                        {
                            "type": "response.content_part.added",
                            "item_id": text_item_id,
                            "output_index": text_out_idx,
                            "content_index": 0,
                            "part": {"type": "output_text", "text": "", "annotations": []},
                        },
                    )
                text_buf += content
                yield (
                    "response.output_text.delta",
                    {
                        "type": "response.output_text.delta",
                        "item_id": text_item_id,
                        "output_index": text_out_idx,
                        "content_index": 0,
                        "delta": content,
                    },
                )

            for tc in delta.get("tool_calls") or []:
                idx = tc.get("index", 0)
                fn = tc.get("function") or {}
                if idx not in tool_items:
                    item_id = _new_id("fc")
                    tool_items[idx] = {
                        "id": item_id,
                        "name": fn.get("name", ""),
                        "call_id": tc.get("id") or f"call_{uuid.uuid4().hex}",
                        "args": "",
                        "out_idx": output_counter,
                    }
                    output_counter += 1
                    tool_order.append(idx)
                    yield (
                        "response.output_item.added",
                        {
                            "type": "response.output_item.added",
                            "output_index": tool_items[idx]["out_idx"],
                            "item": {
                                "id": item_id,
                                "type": "function_call",
                                "status": "in_progress",
                                "call_id": tool_items[idx]["call_id"],
                                "name": tool_items[idx]["name"],
                                "arguments": "",
                            },
                        },
                    )
                if fn.get("name"):
                    tool_items[idx]["name"] = fn["name"]
                if tc.get("id"):
                    tool_items[idx]["call_id"] = tc["id"]
                frag = fn.get("arguments")
                if frag:
                    tool_items[idx]["args"] += frag
                    yield (
                        "response.function_call_arguments.delta",
                        {
                            "type": "response.function_call_arguments.delta",
                            "item_id": tool_items[idx]["id"],
                            "output_index": tool_items[idx]["out_idx"],
                            "delta": frag,
                        },
                    )

    if text_item_id is not None:
        yield (
            "response.output_text.done",
            {
                "type": "response.output_text.done",
                "item_id": text_item_id,
                "output_index": text_out_idx,
                "content_index": 0,
                "text": text_buf,
                "annotations": [],
            },
        )
        yield (
            "response.content_part.done",
            {
                "type": "response.content_part.done",
                "item_id": text_item_id,
                "output_index": text_out_idx,
                "content_index": 0,
                "part": {"type": "output_text", "text": text_buf, "annotations": []},
            },
        )
        yield (
            "response.output_item.done",
            {
                "type": "response.output_item.done",
                "output_index": text_out_idx,
                "item": _message_item(text_item_id, text_buf),
            },
        )

    for idx in tool_order:
        it = tool_items[idx]
        yield (
            "response.function_call_arguments.done",
            {
                "type": "response.function_call_arguments.done",
                "item_id": it["id"],
                "output_index": it["out_idx"],
                "arguments": it["args"],
            },
        )
        yield (
            "response.output_item.done",
            {
                "type": "response.output_item.done",
                "output_index": it["out_idx"],
                "item": _function_call_item(it["id"], it["name"], it["args"], it["call_id"]),
            },
        )

    output = []
    if text_item_id is not None:
        output.append(_message_item(text_item_id, text_buf))
    for idx in tool_order:
        it = tool_items[idx]
        output.append(_function_call_item(it["id"], it["name"], it["args"], it["call_id"]))

    final = {
        "id": rid,
        "object": "response",
        "created_at": created,
        "status": "incomplete" if finish == "length" else "completed",
        "model": model,
        "output": output,
        "parallel_tool_calls": True,
        "usage": _map_usage(usage),
    }
    yield ("response.completed", {"type": "response.completed", "response": final})
