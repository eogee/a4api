"""推理预设与显存风险评估（移植自 a4agent PresetEngine.cs）。

预设依据：Ornith 系列为混合架构（full_attention_interval=4），
仅约 1/4 层携带 KV 且每层只有 2 个 KV 头 —— q4_0 下每千 token 约 5.6KB，
上下文的显存代价极小，预设可以给得激进；权重才是大头。
"""
from dataclasses import dataclass

from .gguf import GgufModelInfo


@dataclass
class Preset:
    label: str
    context_tokens: int
    kv_level: str
    note: str

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "context_tokens": self.context_tokens,
            "kv_level": self.kv_level,
            "note": self.note,
        }


def recommend(vram_gb: float, has_discrete_gpu: bool) -> Preset:
    """按显存档位给出预定义推理配置。"""
    if not has_discrete_gpu or vram_gb < 2:
        return Preset("CPU 兜底", 8192, "q4_0",
                      "未检测到可用独显，将走 CPU 推理（速度受限），强烈建议搭配 Ornith-1.5-9B")
    if vram_gb < 6:
        return Preset("入门档 (<6GB)", 8192, "q4_0",
                      "该档位瓶颈是权重本身：仅够 9B 全量 offload，上下文没有加码空间；35B 请勿尝试")
    if vram_gb < 12:
        return Preset("主流档 (6–12GB)", 32768, "q4_0",
                      "9B 全量 offload + 32k 绰绰有余（KV 仅 ~0.2GB）；跑 35B 需换 Q3 量化并把上下文降回 16k")
    if vram_gb < 16:
        return Preset("进阶档 (12–16GB)", 32768, "q4_0",
                      "27B / 35B 小量化可跑 32k；9B 可手动上探 64k")
    if vram_gb < 24:
        return Preset("高端档 (16–24GB)", 65536, "q4_0",
                      "35B-IQ4_XS 全量 offload + 64k 有余量；实测 22GB 卡跑 128k 也只到 ~21.9GB，激进场景可手动拉满")
    return Preset("旗舰档 (≥24GB)", 131072, "q8_0",
                  "35B-IQ4_XS 128k 从容且 KV 可升 q8_0 提升长文召回；理论上限可试原生 256k")


def assess_risk(model: GgufModelInfo, context_tokens: int, kv_level: str,
                vram_gb: float, has_gpu: bool) -> str | None:
    """依据 GGUF 元数据估算显存需求 vs 实际显存，返回警告文案或 None。"""
    if not model.ok or vram_gb <= 0 or not has_gpu:
        return None
    need = model.estimate_vram_gb(context_tokens, kv_level)
    if need > vram_gb * 0.97:
        return (f"⚠ 预计需要 {need:.1f} GB / 显存 {vram_gb:.1f} GB "
                f"—— 大概率 OOM，请降低上下文长度或 KV 档位")
    if need > vram_gb * 0.88:
        return (f"⚡ 预计需要 {need:.1f} GB / 显存 {vram_gb:.1f} GB "
                f"—— 余量偏小，运行时请关闭占用显存的程序")
    return None
