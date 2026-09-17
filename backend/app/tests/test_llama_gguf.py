"""GGUF 解析器测试：内存合成 GGUF 二进制，验证元数据提取与显存估算。"""
import io
import struct

import pytest

from backend.app.llama.gguf import kv_factor, parse


def _w_string(buf, s: bytes):
    buf.write(struct.pack("<Q", len(s)))
    buf.write(s)


def _w_scalar(buf, vtype: int, value: int):
    fmt = {0: "<B", 1: "<b", 2: "<H", 3: "<h", 4: "<I", 5: "<i",
           6: "<f", 7: "<?", 10: "<Q", 11: "<q", 12: "<d"}[vtype]
    buf.write(struct.pack("<I", vtype))
    buf.write(struct.pack(fmt, value))


def _build_gguf(kv_pairs: list, tensor_names: list) -> bytes:
    """按 GGUF v3 布局合成最小文件。kv_pairs: [(key, type, value)]。"""
    buf = io.BytesIO()
    buf.write(b"GGUF")
    buf.write(struct.pack("<I", 3))                       # version
    buf.write(struct.pack("<Q", len(tensor_names)))       # tensor_count
    buf.write(struct.pack("<Q", len(kv_pairs)))           # kv_count
    for key, vtype, value in kv_pairs:
        _w_string(buf, key.encode())
        if vtype == 8:
            buf.write(struct.pack("<I", 8))
            _w_string(buf, value.encode())
        else:
            _w_scalar(buf, vtype, value)
    # 张量目录：n_dims=1 + 一个 dim + type + offset
    for name in tensor_names:
        _w_string(buf, name.encode())
        buf.write(struct.pack("<I", 1))       # n_dims
        buf.write(struct.pack("<Q", 4))       # dim0
        buf.write(struct.pack("<I", 0))       # ggml type F32
        buf.write(struct.pack("<Q", 0))       # offset
    return buf.getvalue()


def _write_tmp(tmp_path, data: bytes):
    p = tmp_path / "model.gguf"
    p.write_bytes(data)
    return str(p)


def test_rejects_non_gguf(tmp_path):
    p = _write_tmp(tmp_path, b"NOPE" + b"\x00" * 64)
    info = parse(p)
    assert not info.ok
    assert "不是有效的 GGUF" in info.error


def test_rejects_bad_version(tmp_path):
    buf = io.BytesIO()
    buf.write(b"GGUF")
    buf.write(struct.pack("<I", 9))
    info = parse(_write_tmp(tmp_path, buf.getvalue()))
    assert not info.ok
    assert "版本" in info.error


def test_parses_core_metadata(tmp_path):
    data = _build_gguf(
        [
            ("llama.context_length", 10, 32768),
            ("llama.embedding_length", 10, 4096),
            ("llama.attention.head_count", 10, 32),
            ("llama.attention.head_count_kv", 10, 8),
            ("llama.attention.key_length", 10, 128),
            ("llama.block_count", 10, 36),
            ("general.architecture", 8, "llama"),
            ("general.file_type", 10, 15),  # Q4_K_M
        ],
        ["token_embd.weight"],
    )
    info = parse(_write_tmp(tmp_path, data))
    assert info.ok
    assert info.arch == "llama"
    assert info.layers == 36
    assert info.head_count == 32
    assert info.head_count_kv == 8
    assert info.key_length == 128
    assert info.native_context == 32768
    assert info.quant_label == "Q4_K_M"
    assert not info.has_nextn_tensors


def test_suffix_matching_is_order_independent(tmp_path):
    """arch 键晚于架构相关键出现时仍应正确解析（后缀匹配）。"""
    data = _build_gguf(
        [
            ("llama.block_count", 10, 12),
            ("general.architecture", 8, "llama"),
        ],
        [],
    )
    info = parse(_write_tmp(tmp_path, data))
    assert info.ok
    assert info.arch == "llama"
    assert info.layers == 12


def test_nextn_tensor_detection(tmp_path):
    data = _build_gguf(
        [("llama.nextn_predict_layers", 10, 1)],
        ["token_embd.weight", "blk0.nextn.ffn_down.weight"],
    )
    info = parse(_write_tmp(tmp_path, data))
    assert info.ok
    assert info.has_nextn_tensors
    assert info.nextn_predict_layers == 1


def test_tokenizer_string_array_skipped(tmp_path):
    """tokenizer 大字符串数组（词表）必须能被跳过而不是解析失败。"""
    buf = io.BytesIO()
    buf.write(b"GGUF")
    buf.write(struct.pack("<I", 3))
    buf.write(struct.pack("<Q", 0))  # tensor_count
    buf.write(struct.pack("<Q", 2))  # kv_count

    # kv1: tokenizer.ggml.tokens = array<string>，1024 个词
    _w_string(buf, b"tokenizer.ggml.tokens")
    buf.write(struct.pack("<I", 9))   # array
    buf.write(struct.pack("<I", 8))   # elem type string
    buf.write(struct.pack("<Q", 1024))
    for i in range(1024):
        _w_string(buf, f"tok{i}€中文".encode())

    # kv2: block_count
    _w_string(buf, b"llama.block_count")
    buf.write(struct.pack("<I", 10))
    buf.write(struct.pack("<Q", 20))

    info = parse(_write_tmp(tmp_path, buf.getvalue()))
    assert info.ok
    assert info.layers == 20


def test_kv_cache_estimation_math():
    """KV 每字节估算手算对齐：2 KV 头 × (128+128) × 2 字节 × 层数。"""
    from backend.app.llama.gguf import GgufModelInfo

    m = GgufModelInfo("x", 0)
    m.layers = 36
    m.head_count_kv = 8
    m.key_length = 128
    m.value_length = 128
    # f16: 36 层 × 8 头 × 256 elem × 2 字节 = 147456 B/token
    assert m.kv_bytes_per_token_f16 == 36 * 8 * 256 * 2

    m2 = GgufModelInfo("x", 0)
    m2.layers = 48
    m2.full_attn_interval = 4
    m2.head_count_kv = 2
    m2.key_length = 128
    m2.value_length = 128
    # 混合架构：仅 1/4 层携带 KV
    assert m2.effective_kv_layers == 12


def test_kv_factor():
    assert kv_factor("f16") == 1.0
    assert kv_factor("q8_0") == pytest.approx(0.53125)
    assert kv_factor("q4_0") == pytest.approx(0.28125)


def test_estimate_vram_gb():
    from backend.app.llama.gguf import GgufModelInfo

    m = GgufModelInfo("x", int(4.5 * 1024 ** 3))
    m.head_count_kv = 8
    m.key_length = 128
    m.value_length = 128
    m.layers = 36
    need = m.estimate_vram_gb(32768, "f16")
    # 权重 4.5 + KV 32768*147456/2^30 ≈ 4.5 + 4.5 + 0.9
    assert need == pytest.approx(4.5 + 4.5 + 0.9, abs=0.05)
