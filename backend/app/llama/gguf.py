"""GGUF 元数据流式解析（移植自 a4agent GgufParser.cs）。

只读 header + 元数据 + 张量目录，跳过大数组（tokenizer），
不做整文件映射；供模型库展示与显存估算使用。
"""
import math
import struct
from pathlib import Path

# general.file_type -> 展示用量化标签
FTYPE_MAP = {
    0: "F32", 1: "F16", 2: "Q4_0", 3: "Q4_1", 7: "Q8_0",
    8: "Q5_0", 9: "Q5_1", 10: "Q2_K", 11: "Q3_K_S", 12: "Q3_K_M",
    13: "Q3_K_L", 14: "Q4_K_S", 15: "Q4_K_M", 16: "Q5_K_S", 17: "Q5_K_M",
    18: "Q6_K", 19: "IQ2_XXS", 20: "IQ2_XS", 21: "Q2_K_S", 22: "IQ3_XS",
    23: "IQ3_XXS", 24: "IQ1_S", 25: "IQ4_NL", 26: "IQ3_S", 27: "IQ2_M",
    28: "IQ4_XS", 29: "IQ1_M", 30: "BF16",
    32: "TQ1_0", 33: "TQ2_0", 36: "MXFP4",
}

_SCALAR_FMT = {
    0: ("<B", 1),   # u8
    1: ("<b", 1),   # i8
    2: ("<H", 2),   # u16
    3: ("<h", 2),   # i16
    4: ("<I", 4),   # u32
    5: ("<i", 4),   # i32
    6: ("<f", 4),   # f32
    7: ("<?", 1),   # bool
    10: ("<Q", 8),  # u64
    11: ("<q", 8),  # i64
    12: ("<d", 8),  # f64
}

_MAX_SCAN_BYTES = 64 * 1024 * 1024  # 元数据阶段的安全扫描上限


class GgufError(Exception):
    pass


class GgufModelInfo:
    """单个 GGUF 文件的解析结果（字段语义与 C# 版一一对应）。"""

    def __init__(self, file_path: str = "", file_size: int = 0):
        self.file_path = file_path
        self.file_size = file_size
        self.ok = False
        self.error = ""
        self.arch = ""
        self.layers = 0            # block_count
        self.head_count = 0        # attention.head_count
        self.head_count_kv = 0     # attention.head_count_kv
        self.key_length = 0        # attention.key_length（缺省回退 embedding）
        self.value_length = 0      # attention.value_length
        self.embedding_length = 0
        self.native_context = 0    # context_length
        self.full_attn_interval = 0  # 0/缺省 = 全层注意力
        self.nextn_predict_layers = 0  # 文件内嵌的 MTP draft 层数
        self.has_nextn_tensors = False  # 存在 *.nextn.* 张量
        self.file_type_raw = -1    # general.file_type
        self.quant_label = "?"

    @property
    def effective_kv_layers(self) -> int:
        """真正携带 KV 缓存的层数。混合 SSM 架构每 N 层才付一次 KV。"""
        if self.full_attn_interval > 1:
            return math.ceil(self.layers / self.full_attn_interval)
        return self.layers

    @property
    def kv_bytes_per_token_f16(self) -> int:
        """f16 下每 token 的 KV 缓存字节数（由元数据推导）。"""
        if self.head_count_kv <= 0 or self.key_length <= 0 or self.value_length <= 0:
            return 0
        elems_per_layer = self.head_count_kv * self.key_length + \
            self.head_count_kv * self.value_length
        return self.effective_kv_layers * elems_per_layer * 2  # fp16 = 2 字节

    def estimate_vram_gb(self, ctx_tokens: int, kv_level: str) -> float:
        weights_overhead_gb = 0.9  # compute buffers + CUDA context（粗估）
        kv_gb = ctx_tokens * self.kv_bytes_per_token_f16 * kv_factor(kv_level) \
            / (1024 ** 3)
        return self.file_size / (1024 ** 3) + kv_gb + weights_overhead_gb

    def to_dict(self) -> dict:
        return {
            "file_path": self.file_path,
            "file_size": self.file_size,
            "ok": self.ok,
            "error": self.error,
            "arch": self.arch,
            "layers": self.layers,
            "head_count": self.head_count,
            "head_count_kv": self.head_count_kv,
            "embedding_length": self.embedding_length,
            "native_context": self.native_context,
            "full_attn_interval": self.full_attn_interval,
            "nextn_predict_layers": self.nextn_predict_layers,
            "has_nextn_tensors": self.has_nextn_tensors,
            "quant_label": self.quant_label,
        }


def kv_factor(level: str) -> float:
    """KV 缓存量化档位相对 f16 的字节系数。"""
    if level == "q8_0":
        return 1.0625 / 2.0
    if level == "q4_0":
        return 0.5625 / 2.0
    return 1.0  # f16


def _read_string(br) -> str:
    (length,) = struct.unpack("<Q", br.read(8))
    if length > 64 * 1024 * 1024:
        raise GgufError("字符串长度异常")
    return str(br.read(length).decode("utf-8", errors="replace"))


def _read_scalar(br, vtype: int) -> int:
    if vtype not in _SCALAR_FMT:
        raise GgufError(f"未知标量类型 {vtype}")
    fmt, size = _SCALAR_FMT[vtype]
    (v,) = struct.unpack(fmt, br.read(size))
    return int(v)


def _skip_array_fast(br, elem_type: int, count: int, fp) -> None:
    if elem_type == 8:  # 字符串数组：必须逐个读（长度前缀变长）
        for _ in range(count):
            _read_string(br)
        return
    if elem_type == 9:  # 嵌套数组（罕见）：必须走一遍
        for _ in range(count):
            (et2,) = struct.unpack("<I", br.read(4))
            (c2,) = struct.unpack("<Q", br.read(8))
            _skip_array_fast(br, et2, c2, fp)
        return
    if elem_type not in _SCALAR_FMT:
        raise GgufError(f"未知数组元素类型 {elem_type}")
    size = _SCALAR_FMT[elem_type][1]
    fp.seek(count * size, 1)  # seek 跳过：tokenizer 大块瞬间掠过


def parse(path: str) -> GgufModelInfo:
    """解析 GGUF 元数据；失败时返回 ok=False + error，不抛出。"""
    try:
        size = Path(path).stat().st_size
    except OSError:
        size = 0
    info = GgufModelInfo(path, size)
    try:
        with open(path, "rb") as fp:
            magic = fp.read(4)
            if magic != b"GGUF":
                info.error = "不是有效的 GGUF 文件"
                return info
            (version,) = struct.unpack("<I", fp.read(4))
            if version < 2 or version > 3:
                info.error = f"不支持的 GGUF 版本 {version}"
                return info
            br = fp
            (tensor_count,) = struct.unpack("<Q", br.read(8))
            (kv_count,) = struct.unpack("<Q", br.read(8))

            for _ in range(kv_count):
                key = _read_string(br)
                (vtype,) = struct.unpack("<I", br.read(4))

                if vtype == 8:  # string
                    s = _read_string(br)
                    if key == "general.architecture":
                        info.arch = s
                elif vtype == 9:  # array：小数值数组慢读，大数组快跳
                    (et,) = struct.unpack("<I", br.read(4))
                    (cnt,) = struct.unpack("<Q", br.read(8))
                    if et <= 7 and cnt <= 8:
                        for _ in range(cnt):
                            _read_scalar(br, et)
                    else:
                        _skip_array_fast(br, et, cnt, fp)
                else:
                    v = _read_scalar(br, vtype)
                    # 键以架构名为前缀，而 arch 可能晚于这些键出现，
                    # 因此统一按后缀匹配（与顺序无关）
                    if key.endswith(".block_count"):
                        info.layers = int(v)
                    elif key.endswith(".attention.head_count"):
                        info.head_count = int(v)
                    elif key.endswith(".attention.head_count_kv"):
                        info.head_count_kv = int(v)
                    elif key.endswith(".attention.key_length"):
                        info.key_length = int(v)
                    elif key.endswith(".attention.value_length"):
                        info.value_length = int(v)
                    elif key.endswith(".embedding_length"):
                        info.embedding_length = int(v)
                    elif key.endswith(".context_length"):
                        info.native_context = int(v)
                    elif key.endswith(".full_attention_interval"):
                        info.full_attn_interval = int(v)
                    elif key.endswith(".nextn_predict_layers"):
                        info.nextn_predict_layers = int(v)
                    elif key == "general.file_type":
                        info.file_type_raw = int(v)

                if fp.tell() > _MAX_SCAN_BYTES and key.startswith("tokenizer."):
                    break  # paranoid stop

            # 张量目录扫描：探测 nextn（MTP）张量
            for _ in range(tensor_count):
                name = _read_string(br)
                (n_dims,) = struct.unpack("<I", br.read(4))
                if n_dims > 8:  # 损坏；中止张量扫描
                    break
                fp.seek(8 * n_dims, 1)  # dims u64[]
                fp.read(4)              # ggml type
                fp.read(8)              # offset
                if ".nextn." in name:
                    info.has_nextn_tensors = True
                    break

            info.key_length = info.key_length or info.embedding_length
            info.value_length = info.value_length or info.embedding_length
            info.quant_label = FTYPE_MAP.get(info.file_type_raw, "?") \
                if info.file_type_raw >= 0 else "?"
            info.ok = True
            return info
    except (OSError, struct.error, GgufError) as e:
        info.error = "解析失败: " + str(e)
        return info
    except Exception as e:  # 防御：任何异常都按解析失败处理
        info.error = "解析失败: " + str(e)
        return info
