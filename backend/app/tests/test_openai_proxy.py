from backend.app.openai_proxy import translate_request, translate_response
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


def test_translate_response_basic():
    data = {
        "choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 2},
    }
    out = translate_response(data, "test-model")
    assert out["content"][0]["text"] == "hi"
    assert out["stop_reason"] == "end_turn"