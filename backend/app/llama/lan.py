"""局域网可用 IPv4 选取（移植自 a4agent LanAddress.cs 的目标语义）。

简单取「第一个非回环 IPv4」会拿到 WSL/Hyper-V/VPN 虚拟网卡地址，
其他设备根本连不上。这里按可用性排序：默认路由接口 > 其余；
私网地址 > 其他；169.254 自动专有地址直接丢弃。
（标准库拿不到网关/虚拟网卡元数据，用默认路由探测近似替代。）
"""
import socket


def _default_route_ip() -> str | None:
    """通过 UDP connect 探测默认路由出口接口的本地 IP（不真正发包）。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return str(s.getsockname()[0])
    except OSError:
        return None
    finally:
        s.close()


def _all_local_ipv4() -> list:
    ips = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in ips:
                ips.append(ip)
    except OSError:
        pass
    return ips


def _is_api_pa(ip: str) -> bool:
    return ip.startswith("169.254.")


def _is_private(ip: str) -> bool:
    o = ip.split(".")
    if len(o) != 4:
        return False
    try:
        a, b = int(o[0]), int(o[1])
    except ValueError:
        return False
    return a == 10 or (a == 172 and 16 <= b <= 31) or (a == 192 and b == 168)


def candidate_addresses() -> list:
    """全部候选 IPv4，按可用性从高到低。"""
    primary = _default_route_ip()
    scored = []
    if primary and not _is_api_pa(primary) and primary != "127.0.0.1":
        scored.append((primary, 7 if _is_private(primary) else 6))
    for ip in _all_local_ipv4():
        if ip in ("127.0.0.1", primary) or _is_api_pa(ip):
            continue
        score = 3 if _is_private(ip) else 2
        if ip not in [x[0] for x in scored]:
            scored.append((ip, score))
    scored.sort(key=lambda x: x[1], reverse=True)
    return [ip for ip, _ in scored]


def get_best_ipv4() -> str | None:
    try:
        cands = candidate_addresses()
        return cands[0] if cands else None
    except Exception:
        return None
