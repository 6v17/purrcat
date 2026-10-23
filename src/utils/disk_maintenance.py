"""
Docker 数据盘维护：只读观测 + 一键回收空洞

设计取舍（用户明确要求）：
  - 启动/轮询只做只读检测，不阻塞、不提权、不自动压缩；
  - 只在部署面板展示「vhdx 实际占盘 / 有效数据估算 / 空洞占比」；
  - 空洞占比超过阈值时提示，用户点按钮才执行压缩（一次 UAC 授权）；
  - 另有低频 `docker builder prune`，从源头降低 vhdx 增长速度。
"""

import ctypes
import datetime
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time

from src.utils.config import get_enriched_env, get_global_settings, save_global_setting

_WIN = sys.platform == "win32"
_SUBPROC_ENCODING = "gbk" if _WIN else "utf-8"

# 空洞占比提示阈值（0.30 = 30%）
DEAD_RATIO_THRESHOLD = 0.30
# 空洞绝对值低于 1GB 时不打扰用户（小盘占比再高也没回收价值）
DEAD_MIN_BYTES = 1 << 30
# docker system df 结果缓存秒数（前端 3s 轮询，避免频繁 spawn docker）
LIVE_CACHE_TTL = 60
# docker info 活性检查缓存秒数
RUN_CACHE_TTL = 15
# 构建缓存自动清理周期
PRUNE_INTERVAL = 7 * 24 * 3600
SANDBOX_CONTAINER = "agent_computer"

_task = {"state": "idle", "kind": None, "log": [], "finished_at": None}
_task_lock = threading.Lock()
_live_cache = {"at": 0.0, "value": None}
_run_cache = {"at": 0.0, "value": False}
_vhdx_cache = {"path": None}
_sandbox_cache = {"at": 0.0, "value": None}


# ══════════════ 只读观测 ══════════════


def _docker_cli() -> str | None:
    return shutil.which("docker", path=get_enriched_env().get("PATH")) or shutil.which(
        "docker"
    )


def _find_vhdx() -> str | None:
    """定位 Docker Desktop 的数据盘 vhdx（优先 settings.json 里手动指定的路径）"""
    if _vhdx_cache["path"] and os.path.isfile(_vhdx_cache["path"]):
        return _vhdx_cache["path"]

    override = str(get_global_settings().get("docker_vhdx_path") or "").strip()
    if override and os.path.isfile(override):
        _vhdx_cache["path"] = override
        return override

    local = os.environ.get("LOCALAPPDATA") or os.path.expanduser(
        r"~\AppData\Local"
    )
    candidates = []
    roots = [
        os.path.join(local, "Docker", "wsl"),
        os.path.join(local, "Docker", "wsl", "data"),
    ]
    for root in roots:
        if not os.path.isdir(root):
            continue
        for p in glob.glob(os.path.join(root, "**", "*.vhdx"), recursive=True):
            if p not in candidates:
                candidates.append(p)
    if not candidates:
        return None

    def _size(p):
        try:
            return os.path.getsize(p)
        except Exception:
            return 0

    best = max(candidates, key=_size)
    _vhdx_cache["path"] = best
    return best


def _allocated_size(path: str) -> int:
    """文件在磁盘上的实际占用（vhdx 是稀疏文件，逻辑大小 ≠ 实际占盘）"""
    if _WIN:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        get_size = kernel32.GetCompressedFileSizeW
        get_size.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_ulong)]
        get_size.restype = ctypes.c_ulong
        high = ctypes.c_ulong(0)
        low = get_size(str(path), ctypes.byref(high))
        if low == 0xFFFFFFFF and ctypes.get_last_error() != 0:
            raise OSError(ctypes.get_last_error(), "GetCompressedFileSizeW 失败")
        return (high.value << 32) + low
    st = os.stat(path)
    blocks = getattr(st, "st_blocks", 0)
    return blocks * 512 if blocks else st.st_size


_UNIT_SCALE = {
    "B": 1,
    "KB": 1000,
    "MB": 1000**2,
    "GB": 1000**3,
    "TB": 1000**4,
    "PB": 1000**5,
    "KIB": 1024,
    "MIB": 1024**2,
    "GIB": 1024**3,
    "TIB": 1024**4,
}


def _parse_size(text: str) -> int:
    m = re.match(r"^\s*([\d.]+)\s*([KMGTP]?i?B)\s*$", text or "", re.I)
    if not m:
        return 0
    return int(float(m.group(1)) * _UNIT_SCALE.get(m.group(2).upper(), 1))


def _docker_running(docker: str | None) -> bool:
    if not docker:
        return False
    now = time.time()
    if now - _run_cache["at"] < RUN_CACHE_TTL:
        return _run_cache["value"]
    from src.utils.sandbox_setup import check_docker_running

    value = check_docker_running(docker)
    _run_cache["at"] = now
    _run_cache["value"] = value
    return value


def _live_estimate(docker: str | None) -> int | None:
    """容器内有效数据估算（docker system df 各行的 Size 合计）。

    注意：这是**估算**，Docker 自身统计会包含部分可回收开销，可能略高于真实值；
    死空间比例按 0 下限截断，不会因高估出现负值。
    """
    if not docker:
        return None
    now = time.time()
    if now - _live_cache["at"] < LIVE_CACHE_TTL:
        return _live_cache["value"]
    total = 0
    try:
        r = subprocess.run(
            [docker, "system", "df", "--format", "{{json .}}"],
            capture_output=True,
            text=True,
            timeout=20,
            encoding=_SUBPROC_ENCODING,
            errors="replace",
        )
        if r.returncode != 0:
            return None
        for line in (r.stdout or "").splitlines():
            try:
                row = json.loads(line)
            except Exception:
                continue
            total += _parse_size(str(row.get("Size") or ""))
    except Exception:
        return None
    _live_cache["at"] = now
    _live_cache["value"] = total
    return total


def _human(n: int | float) -> str:
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return f"{n:.1f} TB"


def get_task() -> dict:
    with _task_lock:
        return {
            "state": _task["state"],
            "kind": _task["kind"],
            "log": list(_task["log"]),
            "finished_at": _task["finished_at"],
        }


def _parse_rfc3339(text: str) -> float | None:
    """解析 docker 的 Created 时间（纳秒精度），失败返回 None"""
    m = re.match(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:\d{2})", text or "")
    if not m:
        return None
    frac = (m.group(2) or "")[:6].ljust(6, "0")
    tz = "+00:00" if m.group(3) == "Z" else m.group(3)
    try:
        dt = datetime.datetime.fromisoformat(f"{m.group(1)}.{frac}{tz}")
        return dt.timestamp()
    except Exception:
        return None


def _sandbox_info(docker: str | None) -> dict | None:
    """沙盒容器创建时间/镜像（缓存 2 分钟，避免每次轮询都 spawn docker）"""
    if not docker:
        return None
    now = time.time()
    if now - _sandbox_cache["at"] < 120:
        return _sandbox_cache["value"]
    value = None
    try:
        r = subprocess.run(
            [
                docker,
                "inspect",
                SANDBOX_CONTAINER,
                "--format",
                "{{.Created}}|{{.Config.Image}}",
            ],
            capture_output=True,
            text=True,
            timeout=12,
            encoding=_SUBPROC_ENCODING,
            errors="replace",
        )
        if r.returncode == 0:
            created, _, image = (r.stdout or "").strip().partition("|")
            ts = _parse_rfc3339(created)
            if ts:
                value = {
                    "image": image,
                    "created_at": ts,
                    "age_days": round((now - ts) / 86400, 1),
                }
    except Exception:
        value = None
    _sandbox_cache["at"] = now
    _sandbox_cache["value"] = value
    return value


def rebuild_sandbox() -> tuple[bool, str]:
    """删除沙盒容器（可写层随容器销毁，bind mount 的工作目录不受影响）。

    下次工具调用时 DockerManager.start() 会自动基于镜像重建，
    这是清理容器内累积的 apt/pip 安装与缓存的唯一彻底办法。
    """
    docker = _docker_cli()
    if not docker:
        return False, "未检测到 docker 命令"
    if not _docker_running(docker):
        return False, "Docker 未运行，无法重建容器"
    try:
        r = subprocess.run(
            [docker, "rm", "-f", SANDBOX_CONTAINER],
            capture_output=True,
            text=True,
            timeout=120,
            encoding=_SUBPROC_ENCODING,
            errors="replace",
        )
    except Exception as e:
        return False, f"删除容器失败: {e}"
    _sandbox_cache["at"] = 0.0
    if r.returncode != 0:
        out = (r.stderr or r.stdout or "").strip()
        if "No such container" in out:
            return True, "沙盒容器不存在，无需重建"
        return False, out or "删除容器失败"
    return True, "沙盒容器已删除，下次工具调用会自动重建（工作目录文件不受影响）"


def get_disk_status() -> dict:
    """只读状态：vhdx 占盘 / 有效数据估算 / 空洞比例 + 最近维护记录"""
    result = {
        "supported": False,
        "vhdx_path": None,
        "allocated": 0,
        "logical": 0,
        "live_estimate": None,
        "dead_bytes": 0,
        "dead_ratio": None,
        "threshold": DEAD_RATIO_THRESHOLD,
        "needs_compact": False,
        "docker_running": False,
        "sandbox": None,
        "last_prune_at": None,
        "last_compact_at": None,
        "detail": "仅支持 Windows + Docker Desktop (WSL2)",
        "task": get_task(),
    }
    if not _WIN:
        return result

    settings = get_global_settings()
    result["last_prune_at"] = settings.get("docker_prune_at")
    result["last_compact_at"] = settings.get("docker_compact_at")

    vhdx = _find_vhdx()
    docker = _docker_cli()
    result["docker_running"] = _docker_running(docker)
    if result["docker_running"]:
        result["sandbox"] = _sandbox_info(docker)
    if not vhdx:
        result["detail"] = "未找到 Docker 数据盘 vhdx（可能未安装 Docker Desktop）"
        return result

    result["supported"] = True
    result["vhdx_path"] = vhdx
    try:
        result["allocated"] = _allocated_size(vhdx)
        result["logical"] = os.path.getsize(vhdx)
    except Exception as e:
        result["detail"] = f"读取 vhdx 大小时失败: {e}"
        return result

    live = _live_estimate(docker) if result["docker_running"] else None
    if live is None:
        result["detail"] = (
            f"数据盘实际占盘 {_human(result['allocated'])}，"
            "Docker 未运行，暂时无法估算有效数据"
        )
        return result

    live = min(live, result["allocated"])
    dead = max(0, result["allocated"] - live)
    ratio = (dead / result["allocated"]) if result["allocated"] else 0.0
    result["live_estimate"] = live
    result["dead_bytes"] = dead
    result["dead_ratio"] = round(ratio, 4)
    result["needs_compact"] = ratio >= DEAD_RATIO_THRESHOLD and dead >= DEAD_MIN_BYTES
    result["detail"] = (
        f"实际占盘 {_human(result['allocated'])} · "
        f"有效数据约 {_human(live)} · "
        f"空洞约 {_human(dead)}（{ratio * 100:.0f}%）"
    )
    return result


# ══════════════ 一键回收（压缩 vhdx） ══════════════


def _log(line: str) -> None:
    with _task_lock:
        _task["log"] = (_task["log"] + [line])[-200:]


def _docker_desktop_exe() -> str | None:
    candidates = [
        r"C:\Program Files\Docker\Docker\Docker Desktop.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Docker\Docker Desktop.exe"),
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    return None


def _run_cmd(cmd: list, timeout: float = 120) -> int:
    try:
        r = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
            encoding=_SUBPROC_ENCODING,
            errors="replace",
            env=get_enriched_env(),
        )
        out = (r.stdout or "").strip()
        if out:
            for line in out.splitlines()[-20:]:
                _log("    " + line)
        return r.returncode
    except subprocess.TimeoutExpired:
        _log(f"[!] 命令超时（{int(timeout)}s）: {' '.join(cmd[:3])}")
        return -1
    except Exception as e:
        _log(f"[!] 命令执行失败: {cmd[0]}: {e}")
        return -1


def _stop_docker() -> None:
    """停掉沙盒容器与 Docker Desktop，并关停 WSL 以释放 vhdx 文件句柄"""
    docker = _docker_cli()
    if docker:
        _log("[*] 休眠沙盒容器 ...")
        _run_cmd([docker, "stop", SANDBOX_CONTAINER], timeout=60)

        _log("[*] 停止 Docker Desktop ...")
        if _run_cmd([docker, "desktop", "stop"], timeout=180) != 0:
            _log("[*] 当前 Docker 版本不支持 desktop stop，改用进程退出")
            _run_cmd(["taskkill", "/IM", "Docker Desktop.exe", "/F"], timeout=30)

    _log("[*] 关闭 WSL 虚拟机 ...")
    _run_cmd(["wsl", "--shutdown"], timeout=120)

    deadline = time.time() + 60
    while time.time() < deadline:
        if not _docker_running(docker):
            break
        time.sleep(3)
    _run_cache["at"] = 0.0
    time.sleep(3)  # 等文件句柄真正释放


def _compact_vhdx(vhdx: str) -> tuple[bool, str]:
    """提权执行 diskpart compact（一次 UAC 授权），返回 (成功, 说明)"""
    script = "\r\n".join(
        [
            f'select vdisk file="{vhdx}"',
            "attach vdisk readonly",
            "compact vdisk",
            "detach vdisk",
            "exit",
        ]
    )
    fd, script_path = tempfile.mkstemp(prefix="purrcat_compact_", suffix=".txt")
    try:
        # diskpart 按系统 ANSI 代码页读取脚本（中文系统 = GBK），用 UTF-8 会乱码
        try:
            data = script.encode("mbcs")
        except Exception:
            data = script.encode("utf-8")
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        esc_path = script_path.replace("'", "''")
        ps = (
            "$ErrorActionPreference='Stop'; "
            "$p = Start-Process -FilePath diskpart.exe "
            f"-ArgumentList '/s','{esc_path}' "
            "-Verb RunAs -Wait -PassThru; exit $p.ExitCode"
        )
        r = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                ps,
            ],
            capture_output=True,
            text=True,
            timeout=1800,
            encoding=_SUBPROC_ENCODING,
            errors="replace",
        )
        err = (r.stderr or "").strip()
        if r.returncode != 0:
            if "canceled" in err.lower() or "取消" in err:
                return False, "已取消管理员授权（UAC），未执行压缩"
            return False, err or f"diskpart 退出码 {r.returncode}"
        return True, "diskpart 压缩完成"
    except subprocess.TimeoutExpired:
        return False, "diskpart 压缩超时"
    except Exception as e:
        return False, f"压缩失败: {e}"
    finally:
        try:
            os.remove(script_path)
        except Exception:
            pass


def _start_docker() -> None:
    exe = _docker_desktop_exe()
    if not exe:
        _log("[!] 未找到 Docker Desktop，压缩完成后请手动启动 Docker")
        return
    _log("[*] 重新启动 Docker Desktop ...")
    try:
        subprocess.Popen([exe], close_fds=True)
    except Exception as e:
        _log(f"[!] 启动 Docker Desktop 失败: {e}")
        return
    docker = _docker_cli()
    deadline = time.time() + 180
    while time.time() < deadline:
        if _docker_running(docker):
            _log("[+] Docker 已恢复运行")
            return
        time.sleep(5)
    _log("[!] Docker 启动等待超时，请手动检查（容器会在下次工具调用时自动拉起）")


def _compact_worker() -> None:
    was_running = False
    try:
        vhdx = _find_vhdx()
        if not vhdx:
            _log("[!] 未找到 Docker 数据盘 vhdx")
            raise RuntimeError("未找到 vhdx")
        was_running = _docker_running(_docker_cli())
        before = _allocated_size(vhdx)
        _log(f"[*] 当前占盘 {_human(before)}: {vhdx}")

        _stop_docker()
        ok, message = _compact_vhdx(vhdx)
        if not ok:
            _log(f"[!] {message}")
            if was_running:
                _start_docker()
            with _task_lock:
                _task["state"] = "failed"
                _task["finished_at"] = time.time()
            return

        after = _allocated_size(vhdx)
        freed = max(0, before - after)
        _log(f"[+] 压缩完成: {_human(before)} → {_human(after)}，释放 {_human(freed)}")
        save_global_setting("docker_compact_at", time.time())
        _live_cache["at"] = 0.0
        if was_running:
            _start_docker()
        with _task_lock:
            _task["state"] = "success"
            _task["finished_at"] = time.time()
        return
    except Exception as e:
        with _task_lock:
            _task["state"] = "failed"
            _task["finished_at"] = time.time()
        _log(f"[!] 压缩失败: {e}")
        try:
            if was_running and not _docker_running(_docker_cli()):
                _start_docker()
        except Exception:
            pass
        return


def start_compact() -> tuple[bool, str]:
    """用户点击「一键回收」后启动后台压缩；正在执行时拒绝重复触发"""
    if not _WIN:
        return False, "仅支持 Windows 下的 Docker Desktop"
    with _task_lock:
        if _task["state"] == "running":
            return False, "磁盘维护任务正在执行中，请稍候"
        _task.update(
            state="running",
            kind="compact",
            log=[f"[{time.strftime('%H:%M:%S')}] 开始压缩 Docker 数据盘"],
            finished_at=None,
        )
    threading.Thread(target=_compact_worker, daemon=True).start()
    return True, "压缩已开始，Docker 会短暂停止"


# ══════════════ 构建缓存清理（预防膨胀） ══════════════


def _prune_worker() -> bool:
    docker = _docker_cli()
    if not docker or not _docker_running(docker):
        _log("[!] Docker 未运行，跳过构建缓存清理")
        return False
    _log("[*] 清理构建缓存: docker builder prune -af ...")
    code = _run_cmd([docker, "builder", "prune", "-af"], timeout=600)
    if code != 0:
        _log(f"[!] 构建缓存清理失败（退出码 {code}）")
        return False
    save_global_setting("docker_prune_at", time.time())
    _live_cache["at"] = 0.0
    _log("[+] 构建缓存已清理")
    return True


def start_prune() -> tuple[bool, str]:
    """手动触发一次构建缓存清理（后台线程）"""
    with _task_lock:
        if _task["state"] == "running":
            return False, "磁盘维护任务正在执行中，请稍候"
        _task.update(
            state="running",
            kind="prune",
            log=[f"[{time.strftime('%H:%M:%S')}] 开始清理构建缓存"],
            finished_at=None,
        )

    def _worker():
        ok = False
        try:
            ok = _prune_worker()
        except Exception as e:
            _log(f"[!] 清理异常: {e}")
        with _task_lock:
            _task["state"] = "success" if ok else "failed"
            _task["finished_at"] = time.time()

    threading.Thread(target=_worker, daemon=True).start()
    return True, "已开始清理构建缓存"


def maybe_weekly_prune() -> None:
    """启动后台调用：距离上次清理超过 7 天才执行一次，失败不更新时间戳"""
    try:
        last = get_global_settings().get("docker_prune_at") or 0
        if time.time() - float(last) < PRUNE_INTERVAL:
            return
        docker = _docker_cli()
        if not docker or not _docker_running(docker):
            return
        with _task_lock:
            if _task["state"] == "running":
                return
        _prune_worker()
    except Exception as e:
        print(f"[DiskMaintenance] 定期清理构建缓存失败(忽略): {e}")
