from backend.app.openai_proxy import (
    _retry_after_headers,
    _upstream_status,
    translate_request,
    translate_response,
)
from backend.app.responses_translator import build_payload, _sanitize_tool_messages


def test_translate_request_with_tools():
    body = {
        "model": "claude-3-5-sonnet-20241022",
        "max_tokens": 1024,
        "tools": [
            {
                "name": "search",
                "description": "Search the web",
                "input_schema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                },
            }
        ],
        "messages": [{"role": "user", "content": "Search for something"}],
    }
    out = translate_request(body)
    assert out["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "search",
                "description": "Search the web",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                },
            },
        }
    ]
    assert out["messages"][0]["role"] == "user"


def test_translate_request_keeps_description_property_schema():
    """名为 description 的工具参数应保留为 schema 字典，而非被误转成字符串。

    回归：Claude Code 的 Bash 工具含 command/description/timeout 三个参数，
    _clean_schema_descriptions 曾把名为 description 的属性定义整体转成字符串，
    生成非法 schema，被 Novita 等严格校验的上游以 400 拒绝。
    """
    body = {
        "model": "test-model",
        "tools": [
            {
                "name": "Bash",
                "description": "Run a bash command",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "The command"},
                        "description": {
                            "type": "string",
                            "description": "What this command does",
                        },
                    },
                    "required": ["command"],
                },
            }
        ],
        "messages": [{"role": "user", "content": "hi"}],
    }
    out = translate_request(body)
    prop = out["tools"][0]["function"]["parameters"]["properties"]["description"]
    assert isinstance(prop, dict)
    assert prop["type"] == "string"
    assert prop["description"] == "What this command does"


def test_build_payload_maps_developer_role_to_system():
    """回归：Codex 以 developer 角色发送系统指令时，应映射为 system 再转发上游，
    否则 DeepSeek/智谱等只认 Chat Completions 的服务商会报 role 不合法。"""
    body = {
        "model": "test-model",
        "instructions": "top-level instructions",
        "input": [
            {"type": "message", "role": "developer", "content": "codex dev instruction"},
            {"type": "message", "role": "user", "content": "hi"},
        ],
    }
    out = build_payload(body)
    roles = [m["role"] for m in out["messages"]]
    assert "developer" not in roles
    assert roles == ["system", "system", "user"]
    assert out["messages"][1]["content"] == "codex dev instruction"


def test_sanitize_tool_messages_keeps_valid_dialogs():
    """回归：配对完整的对话应原样保留（no-op），不得误删正常工具调用。"""
    messages = [
        {"role": "user", "content": "run it"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "shell_command:1",
                    "type": "function",
                    "function": {"name": "shell_command", "arguments": "{}"},
                },
                {
                    "id": "shell_command:2",
                    "type": "function",
                    "function": {"name": "shell_command", "arguments": "{}"},
                },
            ],
        },
        {"role": "tool", "tool_call_id": "shell_command:1", "content": "ok1"},
        {"role": "tool", "tool_call_id": "shell_command:2", "content": "ok2"},
        {"role": "assistant", "content": "done"},
    ]
    out = _sanitize_tool_messages(messages)
    assert out == messages


def test_sanitize_tool_messages_drops_orphan_tool_call():
    """回归：Codex 沙箱故障/中断时发来只有 function_call 没有 function_call_output
    的残缺对话，应剔除悬空调用，避免上游以「tool_call 无响应」整轮 400。"""
    messages = [
        {"role": "user", "content": "run it"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "shell_command:1",
                    "type": "function",
                    "function": {"name": "shell_command", "arguments": "{}"},
                }
            ],
        },
    ]
    out = _sanitize_tool_messages(messages)
    assert [m["role"] for m in out] == ["user"]


def test_sanitize_tool_messages_drops_orphan_tool_response():
    """回归：有 function_call_output 但缺来源 function_call 的孤立结果应剔除。"""
    messages = [
        {"role": "user", "content": "run it"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "shell_command:1",
                    "type": "function",
                    "function": {"name": "shell_command", "arguments": "{}"},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "shell_command:1", "content": "ok1"},
        {"role": "tool", "tool_call_id": "shell_command:2", "content": "orphan"},
    ]
    out = _sanitize_tool_messages(messages)
    tool_ids = [m["tool_call_id"] for m in out if m["role"] == "tool"]
    assert tool_ids == ["shell_command:1"]


def test_sanitize_tool_messages_demotes_assistant_to_text():
    """回归：无响应的 tool_call 被剔除后，若 assistant 有正文则降级为纯文本消息。"""
    messages = [
        {
            "role": "assistant",
            "content": "I will run it",
            "tool_calls": [
                {
                    "id": "shell_command:1",
                    "type": "function",
                    "function": {"name": "shell_command", "arguments": "{}"},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "shell_command:2", "content": "other"},
    ]
    out = _sanitize_tool_messages(messages)
    assert out == [{"role": "assistant", "content": "I will run it"}]


def test_build_payload_sanitizes_broken_dialog():
    """端到端：build_payload 对残缺 Responses input 产出可被上游接受的 chat.completions。"""
    body = {
        "model": "test-model",
        "stream": False,
        "input": [
            {"type": "message", "role": "user", "content": "run it"},
            {
                "type": "function_call",
                "call_id": "shell_command:1",
                "name": "shell_command",
                "arguments": "{}",
            },
            {
                "type": "function_call_output",
                "call_id": "shell_command:2",
                "output": "orphan-result",
            },
        ],
    }
    out = build_payload(body)
    roles = [m["role"] for m in out["messages"]]
    assert roles == ["user"]
    # 确保无悬空 tool_call 残留，上游不会拒绝
    assert all(m.get("role") != "assistant" or not m.get("tool_calls") for m in out["messages"])


def test_sanitize_tool_messages_reorders_output_before_call():
    """回归：function_call_output 出现在 function_call 之前（会话中断/重连时可能
    发生）时，应把 tool 响应重排到 assistant tool_calls 之后。多数上游校验
    「assistant 的 tool_calls 必须紧跟 tool 响应」，顺序颠倒会整轮 400。"""
    messages = [
        {"role": "tool", "tool_call_id": "shell_command:1", "content": "ok"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "shell_command:1",
                    "type": "function",
                    "function": {"name": "shell_command", "arguments": "{}"},
                }
            ],
        },
    ]
    out = _sanitize_tool_messages(messages)
    assert [m["role"] for m in out] == ["assistant", "tool"]
    assert out[1]["tool_call_id"] == "shell_command:1"


def test_build_payload_reorders_output_before_call():
    """端到端：残缺 Responses input 中 function_call_output 在 function_call 之前
    时，翻译出的 chat.completions 顺序正确（assistant 在前、tool 在后）。"""
    body = {
        "model": "test-model",
        "stream": False,
        "input": [
            {"type": "function_call_output", "call_id": "shell_command:1", "output": "ok"},
            {
                "type": "function_call",
                "call_id": "shell_command:1",
                "name": "shell_command",
                "arguments": "{}",
            },
        ],
    }
    out = build_payload(body)
    roles = [m["role"] for m in out["messages"]]
    assert roles == ["assistant", "tool"]
    assert out["messages"][0]["tool_calls"][0]["id"] == "shell_command:1"
    assert out["messages"][1]["tool_call_id"] == "shell_command:1"


def test_upstream_status_preserves_4xx():
    """回归：上游 429/408 等可退避状态应原样透传，而不是被统一包装成 502，
    否则客户端没有 Retry-After 参考、会在 502 下无间隔重连进一步撞限流。"""
    assert _upstream_status(429) == 429
    assert _upstream_status(408) == 408
    assert _upstream_status(400) == 400
    assert _upstream_status(500) == 502
    assert _upstream_status(503) == 502


def test_retry_after_headers_passthrough():
    """回归：上游返回 Retry-After 时透传给客户端，供其按建议时间退避。"""

    class _Resp:
        def getheader(self, name):
            if name == "Retry-After":
                return "1"

    assert _retry_after_headers(_Resp()) == {"Retry-After": "1"}

    class _NoRa:
        def getheader(self, name):
            return None

    assert _retry_after_headers(_NoRa()) == {}


def test_normalize_tool_call_nulls_keeps_first_chunk_fields():
    """回归：opencode zen 等上游在后续流式分片里把 tool_calls 的 id/name 置为 null，
    归一化后应删除这些 null 键（等价于省略），让 dsh-llm-deepseek 的
    `!== void 0` 检查不会把首个分片解析出的工具名/ID 覆盖为空。"""
    from backend.app.openai_proxy import _normalize_tool_call_nulls

    # 首个分片：id/name 有效
    first = {"choices": [{"delta": {"tool_calls": [
        {"index": 0, "id": "call_1", "type": "function",
         "function": {"name": "get_weather", "arguments": ""}}]}}]}
    _normalize_tool_call_nulls(first)
    assert first["choices"][0]["delta"]["tool_calls"][0]["id"] == "call_1"
    assert first["choices"][0]["delta"]["tool_calls"][0]["function"]["name"] == "get_weather"

    # 后续分片：id/name 为 null，应被删除而不是保留 null
    later = {"choices": [{"delta": {"tool_calls": [
        {"index": 0, "id": None, "type": "function",
         "function": {"name": None, "arguments": "{\"city\": \"北京\"}"}}]}}]}
    _normalize_tool_call_nulls(later)
    tc = later["choices"][0]["delta"]["tool_calls"][0]
    assert "id" not in tc
    assert "name" not in tc["function"]
    assert tc["index"] == 0
    assert tc["function"]["arguments"] == '{"city": "北京"}'

    # arguments 等其它字段不受影响
    assert tc["function"].get("arguments") is not None


def test_translate_response_basic():
    data = {
        "choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 2},
    }
    out = translate_response(data, "test-model")
    assert out["content"][0]["text"] == "hi"
    assert out["stop_reason"] == "end_turn"