from backend.app.openai_proxy import translate_request, translate_response
from backend.app.responses_translator import build_payload


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


def test_translate_response_basic():
    data = {
        "choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 2},
    }
    out = translate_response(data, "test-model")
    assert out["content"][0]["text"] == "hi"
    assert out["stop_reason"] == "end_turn"