from backend.app.openai_proxy import translate_request, translate_response


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


def test_translate_response_basic():
    data = {
        "choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 2},
    }
    out = translate_response(data, "test-model")
    assert out["content"][0]["text"] == "hi"
    assert out["stop_reason"] == "end_turn"