import io
import os
import re
import shutil
import threading
import urllib.request
import zipfile
import traceback
import json

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

# 引入底层工具操作
from src.tool.callmcp.schema_manager import load_cached_schemas, refresh_schemas
from src.tool.search.mcp_search import MCPSearcher, rebuild_vectors_async
from src.tool.search.skill_search import SkillSearcher, rebuild_skill_vectors_async
from src.tool.cron.cron_operations import list_crons, add_cron, delete_cron

# 🌟 新增：引入读取与保存 MCP 配置文件需要的依赖
from src.utils.config import (
    get_mcp_config,
    MCP_CONFIG_PATH,
    SKILL_DIR,
    MCP_SOURCE_DIR,
    AGENT_CORE_DIR,
    GOAL_MD_PATH,
    HEARTBEAT_FILE,
    SENSOR_CONFIG_PATH,
    SENSOR_EXTENSION_DIR,
    GRAPHS_DIR,
    PARADIGMS_DIR,
    get_sensor_config,
    _save_json_file,
)
from src.utils.graph_api import list_graphs
from src.utils.skill_helper import _find_skill_md_file

# 极简宿主的插件依赖类型白名单与用户插件根：与 webmin.py 共用同一份定义，
# 避免两处各写一份常量后逐渐漂移。（webmin.py 不 import 本文件，无循环依赖）
from src.server.api import plugin_runtime
from src.server.api.webmin import (
    DEP_TYPES,
    ROOT_TO_DIR,
    SANDBOX_PLUGIN_ROOT,
    USER_PLUGIN_ROOT,
)

router = APIRouter(prefix="/api/tools", tags=["Tools Management"])


# ==========================================
# 1. MCP 服务器名称和工具名称 API
# ==========================================
@router.get("/mcp")
def get_mcp_tools_api():
    """获取内存/缓存里的 MCP 服务器及其包含的工具名称和描述"""
    try:
        schemas = load_cached_schemas()

        # 按照 server 名称进行分组组织
        result = {}
        for s in schemas:
            srv = s.get("server", "unknown")
            func = s.get("function", {})

            if srv not in result:
                result[srv] = []

            result[srv].append(
                {
                    "name": func.get("name", ""),
                    "description": func.get("description", ""),
                }
            )

        return result
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"获取 MCP 列表失败: {str(e)}")


# ==========================================
# 2. Skill 名称和技能描述 API
# ==========================================
@router.get("/skills")
def get_skills_api():
    """获取内存里的 Skill 名称和描述"""
    try:
        searcher = SkillSearcher()
        # searcher.skills 是一个列表，格式如 [{"name": "...", "description": "...", "dir_name": "..."}]
        return searcher.skills
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"获取 Skill 列表失败: {str(e)}")


# ==========================================
# Skill 在线安装 API
# ==========================================
class InstallSkillReq(BaseModel):
    url: str


class InstallSkillsBatchReq(BaseModel):
    urls: list


def _parse_skill_github_url(url: str):
    """解析 GitHub skill URL，返回 (owner, repo, branch, path)；不匹配则抛 400"""
    match = re.match(
        r"https?://github\.com/([^/]+)/([^/]+)/tree/([^/]+)(?:/(.*))?", url
    )
    if not match:
        raise HTTPException(
            status_code=400,
            detail="URL格式错误！正确格式示例: https://github.com/owner/repo/tree/branch/path/to/skill",
        )
    owner, repo, branch, path = match.groups()
    return owner, repo, branch, (path or "").strip("/")


def _extract_skill_from_zip(zip_data: bytes, repo: str, path: str) -> str:
    """从仓库 zip 字节流中解压单个 skill 子目录到 SKILL_DIR，返回 skill 名"""
    # 仓库根目录即 skill 时，用仓库名作为 skill 名
    skill_name = os.path.basename(path) if path else repo

    dest_dir = os.path.join(SKILL_DIR, skill_name)

    # 覆盖式重装：先清掉旧目录，保证与仓库当前版本一致
    if os.path.isdir(dest_dir):
        shutil.rmtree(dest_dir)

    with zipfile.ZipFile(io.BytesIO(zip_data)) as z:
        root_folder = z.namelist()[0].split("/")[0]
        target_prefix = f"{root_folder}/{path}".rstrip("/") + "/"

        extracted_count = 0
        for file_info in z.infolist():
            if file_info.filename.startswith(target_prefix):
                relative_path = file_info.filename[len(target_prefix) :]
                if not relative_path:
                    continue

                local_path = os.path.join(dest_dir, relative_path)
                if file_info.is_dir():
                    os.makedirs(local_path, exist_ok=True)
                else:
                    os.makedirs(os.path.dirname(local_path), exist_ok=True)
                    with open(local_path, "wb") as f:
                        f.write(z.read(file_info.filename))
                extracted_count += 1

        if extracted_count == 0:
            raise HTTPException(status_code=404, detail=f"仓库中找不到文件夹 '{path}'")
    return skill_name


def _download_skill_from_github(url: str) -> str:
    """根据 GitHub URL 下载第三方 Skill 到本地 SKILL_DIR，返回 skill 名"""
    owner, repo, branch, path = _parse_skill_github_url(url)
    zip_url = f"https://github.com/{owner}/{repo}/archive/refs/heads/{branch}.zip"
    zip_data = urllib.request.urlopen(zip_url).read()
    return _extract_skill_from_zip(zip_data, repo, path)


@router.post("/skills/install")
def install_skill_api(req: InstallSkillReq):
    """根据 GitHub URL 下载第三方 Skill 并热更新内存"""
    try:
        skill_name = _download_skill_from_github(req.url)

        # 解压成功后，触发 searcher 的内存热更新
        searcher = SkillSearcher()
        searcher.reload_index()

        return {
            "status": "success",
            "message": f"Skill '{skill_name}' 下载成功并已热加载入内存！",
        }

    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Skill 下载/解压失败: {str(e)}")


class UninstallSkillReq(BaseModel):
    name: str


@router.post("/skills/uninstall")
def uninstall_skill_api(req: UninstallSkillReq):
    """删除本地已安装的 Skill（目录名或 SKILL.md 的 name 匹配），并热更新内存"""
    try:
        name = req.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="缺少 skill name")

        md_file, _ = _find_skill_md_file(name)
        if not md_file.exists():
            raise HTTPException(
                status_code=404, detail=f"未找到已安装的 Skill '{name}'"
            )

        shutil.rmtree(md_file.parent)
        SkillSearcher().reload_index()
        return {"status": "success", "message": f"Skill '{name}' 已删除"}

    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"删除 Skill 失败: {str(e)}")


@router.post("/skills/install-batch")
def install_skills_batch_api(req: InstallSkillsBatchReq):
    """批量下载多个第三方 Skill 并热更新内存（同一仓库 zip 只下载一次）"""
    # 1. 解析全部 URL，按 (owner, repo, branch) 分组，同一仓库共享一次 zip 下载
    groups = {}
    for url in req.urls:
        owner, repo, branch, path = _parse_skill_github_url(url)
        groups.setdefault((owner, repo, branch), []).append(path)

    installed, failed = [], []
    for (owner, repo, branch), paths in groups.items():
        zip_url = f"https://github.com/{owner}/{repo}/archive/refs/heads/{branch}.zip"
        try:
            zip_data = urllib.request.urlopen(zip_url).read()
        except Exception as e:
            for path in paths:
                failed.append({"path": path or repo, "error": f"仓库下载失败: {e}"})
            continue

        for path in paths:
            try:
                installed.append(_extract_skill_from_zip(zip_data, repo, path))
            except HTTPException as e:
                failed.append({"path": path or repo, "error": str(e.detail)})
            except Exception as e:
                failed.append({"path": path or repo, "error": str(e)})

    # 2. 只要有成功安装就统一热加载一次
    if installed:
        SkillSearcher().reload_index()

    message = f"批量安装完成：成功 {len(installed)} 个"
    if failed:
        message += f"，失败 {len(failed)} 个"
    return {
        "status": "partial" if failed else "success",
        "installed": installed,
        "failed": failed,
        "message": message,
    }


# ==========================================
# 3. Cron 闹钟列表 API
# ==========================================
@router.get("/cron")
def get_crons_api():
    """读取 cron.json 返回现有闹钟列表"""
    try:
        return list_crons()
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"获取闹钟列表失败: {str(e)}")


# ==========================================
# 4. MCP Schema 刷新 API
# ==========================================
# single-flight 门闸：刷新进行中时直接返回，防止连点导致全量刷新排队堆积
_MCP_REFRESH_GATE = threading.Lock()


@router.post("/mcp/refresh")
def refresh_mcp_api():
    """手动刷新 MCP Schema 并更新内存检索树"""
    if not _MCP_REFRESH_GATE.acquire(blocking=False):
        return {"status": "refreshing", "message": "MCP 正在刷新中，请稍候…"}
    try:
        # 1. 重新拉取物理文件
        schemas = refresh_schemas()
        # 2. 触发 Searcher 的内存热更新
        MCPSearcher().reload_index()
        # 3. 后台重建向量矩阵，避免刷新后首次搜索 JIT 卡顿
        rebuild_vectors_async()

        return {
            "status": "success",
            "message": f"MCP 缓存已刷新，共加载 {len(schemas)} 个工具",
        }
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"刷新 MCP 失败: {str(e)}")
    finally:
        _MCP_REFRESH_GATE.release()


# ==========================================
# 🌟 新增：MCP 录入安装 API
# ==========================================
class InstallMCPReq(BaseModel):
    config_json: str
    repo: str = ""  # 源码仓库地址；官方仓库（PurrPod/mcps）时额外下载源码


def _download_official_mcp_source(repo: str, server_names: list) -> str:
    """官方 MCP：从 PurrPod/mcps 仓库下载对应子文件夹源码到 ~/.purrcat/mcps/"""
    match = re.match(r"https?://github\.com/PurrPod/mcps", repo)
    if not match:
        return ""

    zip_url = "https://github.com/PurrPod/mcps/archive/refs/heads/main.zip"
    response = urllib.request.urlopen(zip_url)
    zip_data = response.read()

    downloaded = []
    with zipfile.ZipFile(io.BytesIO(zip_data)) as z:
        root_folder = z.namelist()[0].split("/")[0]

        for name in server_names:
            # 兼容仓库内不同目录层级：<root>/<name>/ 或 <root>/mcps/<name>/
            target_prefix = None
            for candidate in (f"{root_folder}/{name}/", f"{root_folder}/mcps/{name}/"):
                if any(f.filename.startswith(candidate) for f in z.infolist()):
                    target_prefix = candidate
                    break
            if not target_prefix:
                continue

            dest_dir = os.path.join(MCP_SOURCE_DIR, name)
            for file_info in z.infolist():
                if file_info.filename.startswith(target_prefix):
                    relative_path = file_info.filename[len(target_prefix) :]
                    if not relative_path:
                        continue
                    local_path = os.path.join(dest_dir, relative_path)
                    if file_info.is_dir():
                        os.makedirs(local_path, exist_ok=True)
                    else:
                        os.makedirs(os.path.dirname(local_path), exist_ok=True)
                        with open(local_path, "wb") as f:
                            f.write(z.read(file_info.filename))
            downloaded.append(name)

    return ",".join(downloaded)


@router.post("/mcp/install")
def install_mcp_api(req: InstallMCPReq):
    """解析并合并用户传入的 MCP Server JSON 配置，落盘并热更新；官方 MCP 额外下载源码"""
    try:
        new_config = json.loads(req.config_json)
        if "mcpServers" not in new_config:
            raise HTTPException(
                status_code=400, detail="JSON 格式必须以 'mcpServers' 为顶层键"
            )

        # 1. 读出现有配置
        existing_config = get_mcp_config()
        if "mcpServers" not in existing_config:
            existing_config["mcpServers"] = {}

        # 2. 遍历并合并配置
        for srv_name, srv_conf in new_config["mcpServers"].items():
            existing_config["mcpServers"][srv_name] = srv_conf

        # 3. 落盘保存配置文件 mcp_config.json
        os.makedirs(os.path.dirname(MCP_CONFIG_PATH), exist_ok=True)
        with open(MCP_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(existing_config, f, indent=2, ensure_ascii=False)

        # 4. 官方 MCP：下载源码到 ~/.purrcat/mcps/（失败不阻断配置安装）
        source_note = ""
        try:
            downloaded = _download_official_mcp_source(
                req.repo, list(new_config["mcpServers"].keys())
            )
            if downloaded:
                source_note = f"；已下载官方源码: {downloaded}"
        except Exception as e:
            traceback.print_exc()
            source_note = f"；官方源码下载失败: {e}"

        # 5. 刷新 Schema 并重建检索树 (它会自动通信子进程并更新 mcp_schema.json)
        schemas = refresh_schemas()
        MCPSearcher().reload_index()
        rebuild_vectors_async()

        return {
            "status": "success",
            "message": f"MCP 配置已合并并热加载成功！当前系统共载入 {len(schemas)} 个工具。{source_note}",
        }

    except json.JSONDecodeError:
        raise HTTPException(
            status_code=400, detail="输入的不是合法的 JSON 格式，请检查语法"
        )
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"安装 MCP 失败: {str(e)}")


class UninstallMCPReq(BaseModel):
    name: str


@router.post("/mcp/uninstall")
def uninstall_mcp_api(req: UninstallMCPReq):
    """从 mcp_config.json 移除该 Server，清理本地源码并热更新 Schema"""
    try:
        name = req.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="缺少 server 名")

        existing = get_mcp_config()
        servers = existing.get("mcpServers", {})
        if name not in servers:
            raise HTTPException(status_code=404, detail=f"未配置 MCP Server '{name}'")

        del servers[name]
        with open(MCP_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2, ensure_ascii=False)

        # 清理官方源码目录（若有）
        src_dir = os.path.join(MCP_SOURCE_DIR, name)
        if os.path.isdir(src_dir):
            shutil.rmtree(src_dir)

        refresh_schemas()
        MCPSearcher().reload_index()
        rebuild_vectors_async()
        return {
            "status": "success",
            "message": f"MCP Server '{name}' 已删除",
        }

    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"删除 MCP 失败: {str(e)}")


# ==========================================
# 🌟 MCP 已配置列表 API（市场"已安装"检测用）
# ==========================================
@router.get("/mcp/list")
def list_configured_mcps_api():
    """返回 mcp_config.json 中已配置的 MCP Server 名称列表"""
    try:
        config = get_mcp_config()
        return list(config.get("mcpServers", {}).keys())
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"获取 MCP 配置列表失败: {str(e)}")


# ==========================================
# 5. Skill 刷新 API
# ==========================================
_SKILL_REFRESH_GATE = threading.Lock()


@router.post("/skills/refresh")
def refresh_skills_api():
    """手动扫描本地 Skill 文件夹并更新内存检索树"""
    if not _SKILL_REFRESH_GATE.acquire(blocking=False):
        return {"status": "refreshing", "message": "Skill 正在刷新中，请稍候…"}
    try:
        searcher = SkillSearcher()
        searcher.reload_index()
        # 后台重建向量矩阵，避免刷新后首次搜索 JIT 卡顿
        rebuild_skill_vectors_async()

        return {
            "status": "success",
            "message": f"Skill 已刷新，共加载 {len(searcher.skills)} 个技能",
        }
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"刷新 Skill 失败: {str(e)}")
    finally:
        _SKILL_REFRESH_GATE.release()


# ==========================================
# 6. 添加、删除闹钟 API
# ==========================================
class AddCronReq(BaseModel):
    title: str
    trigger_time: str
    repeat_rule: str = "none"
    task_hook: str = "Agent"
    task_inputs: dict = {}


@router.post("/cron")
def add_cron_api(req: AddCronReq):
    """添加闹钟"""
    try:
        result = add_cron(
            title=req.title,
            trigger_time=req.trigger_time,
            repeat_rule=req.repeat_rule,
            task_hook=req.task_hook,  # 🌟 透传参数
            task_inputs=req.task_inputs,  # 🌟 透传参数
        )
        return {"status": "success", "data": result}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=400, detail=f"添加闹钟失败: {str(e)}")


@router.delete("/cron/{identifier}")
def delete_cron_api(identifier: str):
    """删除闹钟 (支持传 id 或 title)"""
    try:
        result = delete_cron(identifier)
        return {"status": "success", "data": result}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=400, detail=f"删除闹钟失败: {str(e)}")


# ==========================================
# 7. Agent 心跳 API（GOAL.md 定时注入）
# ==========================================


class HeartbeatReq(BaseModel):
    interval: int  # 秒，最短 60
    active: bool
    goal: str = ""  # GOAL.md 内容；开启心跳时必填非空


@router.get("/heartbeat")
def get_heartbeat_api():
    """获取心跳配置 + GOAL.md 当前内容"""
    from src.agent.heartbeat import get_heartbeat_manager

    cfg = get_heartbeat_manager().get_config()
    return {
        "interval": cfg["interval"],
        "active": cfg["active"],
        "goal": get_heartbeat_manager().read_goal(),
    }


@router.post("/heartbeat")
def save_heartbeat_api(req: HeartbeatReq):
    """保存心跳配置；开启心跳时必须提交非空 GOAL.md 内容"""
    from src.agent.heartbeat import MIN_INTERVAL

    goal = (req.goal or "").strip()
    if req.active and not goal:
        raise HTTPException(status_code=400, detail="GOAL.md 内容为空，无法开启心跳")

    try:
        os.makedirs(AGENT_CORE_DIR, exist_ok=True)

        # 先落盘 GOAL.md
        with open(GOAL_MD_PATH, "w", encoding="utf-8") as f:
            f.write(req.goal or "")

        # 再落盘心跳配置（原子写入）
        cfg = {"interval": max(MIN_INTERVAL, req.interval), "active": req.active}
        tmp_file = HEARTBEAT_FILE + ".tmp"
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        os.replace(tmp_file, HEARTBEAT_FILE)
        return {"status": "success", "data": cfg}
    except HTTPException:
        raise
    except Exception as e:
        import traceback

        traceback.print_exc()
        raise HTTPException(status_code=400, detail=f"保存心跳配置失败: {str(e)}")


# ==========================================
# 8. 市场通用：远程 JSON 下载助手（带超时）
# ==========================================
REMOTE_REQUEST_TIMEOUT = 15

SENSORS_REGISTRY_URL = (
    "https://raw.githubusercontent.com/PurrPod/sensors/main/registry.json"
)
GRAPHS_REGISTRY_URL = (
    "https://raw.githubusercontent.com/PurrPod/graphs/main/registry.json"
)
# 传感器代码位于官方仓库 sensors/ 子目录下：sensors/<name>/<name>.py（如 feishu-bot）
SENSORS_CODE_BASE = "https://raw.githubusercontent.com/PurrPod/sensors/main/sensors"
GRAPHS_CODE_BASE = "https://raw.githubusercontent.com/PurrPod/graphs/main/graphs"


def _http_get_json(url: str, timeout: int = REMOTE_REQUEST_TIMEOUT):
    """同步 GET 一个远程 URL 并解析 JSON，带超时防卡死"""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "purrcat-market/1.0",
            "Accept": "application/json,text/plain,*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")
    return json.loads(text)


def _http_download(url: str, timeout: int = REMOTE_REQUEST_TIMEOUT) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "purrcat-market/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


# ==========================================
# 9. Sensor 市场：Registry + 已安装列表 + 安装
# ==========================================
@router.get("/market/sensors")
def get_sensor_registry_api():
    """从官方 PurrPod/sensors 仓库拉取 registry.json 返回给前端市场"""
    try:
        data = _http_get_json(SENSORS_REGISTRY_URL)
        sensors = data.get("sensors", []) if isinstance(data, dict) else []
        return {
            "version": data.get("version") if isinstance(data, dict) else None,
            "repository": data.get("repository") if isinstance(data, dict) else None,
            "sensors": sensors,
        }
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=502, detail=f"拉取 Sensor 注册表失败: {str(e)}")


@router.get("/market/sensors/installed")
def list_installed_sensors_api():
    """返回 activate_sensor.json 中已配置（不管 enabled）的传感器名列表"""
    try:
        cfg = get_sensor_config() or {}
        installed = []
        for name, entry in cfg.items():
            installed.append(
                {
                    "name": name,
                    "enabled": bool(entry.get("enabled", False))
                    if isinstance(entry, dict)
                    else False,
                    "has_code": os.path.exists(
                        os.path.join(SENSOR_EXTENSION_DIR, f"{name}.py")
                    ),
                }
            )
        return installed
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(
            status_code=500, detail=f"读取本地 Sensor 列表失败: {str(e)}"
        )


class InstallSensorReq(BaseModel):
    sensor: dict  # registry 中的单条 sensor 对象（含 name / description / enabled / env 等）


@router.post("/market/sensors/install")
def install_sensor_api(req: InstallSensorReq):
    """
    安装 Sensor（支持覆盖式重新下载）：
      1) 把配置合并写入 activate_sensor.json（按 name 覆盖，保留用户已填 env）
      2) 下载对应的代码文件 <name>.py 到 ~/.purrcat/sensor/（覆盖旧文件）
    """
    try:
        sensor = req.sensor or {}
        name = str(sensor.get("name", "")).strip()
        if not name:
            raise HTTPException(status_code=400, detail="sensor 缺少 name 字段")

        # 1. 合并配置：已有配置的 env 非空值不被 registry 占位覆盖
        existing_cfg = get_sensor_config() or {}
        existing_entry = (
            existing_cfg.get(name, {}) if isinstance(existing_cfg, dict) else {}
        )
        if not isinstance(existing_entry, dict):
            existing_entry = {}

        merged_env = {}
        new_env = sensor.get("env") or {}
        old_env = existing_entry.get("env") or {}
        if isinstance(new_env, dict) and isinstance(old_env, dict):
            for k, v in new_env.items():
                old_v = old_env.get(k)
                # 老值非空（非空字符串/非 None）则保留，否则用新的默认占位
                if old_v not in (None, ""):
                    merged_env[k] = old_v
                else:
                    merged_env[k] = v
            # 保留老配置中存在但 registry 已不再声明的自定义 env
            for k, v in old_env.items():
                if k not in merged_env:
                    merged_env[k] = v

        merged = {
            "enabled": existing_entry.get(
                "enabled",
                bool(sensor.get("enabled", False)) if "enabled" in sensor else False,
            ),
            "env": merged_env,
        }
        # 其余 registry 字段原封不动保留一份（方便调试/回查；
        # capabilities 为旧架构字段，已废弃不落盘）
        for k, v in sensor.items():
            if k not in ("enabled", "env", "name", "capabilities"):
                merged[k] = v

        existing_cfg[name] = merged
        os.makedirs(os.path.dirname(SENSOR_CONFIG_PATH), exist_ok=True)
        _save_json_file(SENSOR_CONFIG_PATH, existing_cfg)

        # 2. 下载代码：优先 sensors/<name>/<name>.py，其次 sensors/<name>.py
        code_bytes = None
        last_err = None
        for candidate in (
            f"{SENSORS_CODE_BASE}/{name}/{name}.py",
            f"{SENSORS_CODE_BASE}/{name}.py",
        ):
            try:
                code_bytes = _http_download(candidate)
                break
            except Exception as e:  # noqa: PERF203
                last_err = e
                code_bytes = None
        if code_bytes is None:
            # 代码下载失败不阻断配置落盘（SensorManager 启动时会再次尝试从官方 sensors 仓库下载）
            msg = (
                f"Sensor '{name}' 配置已写入激活配置，但代码文件下载失败"
                + (f": {last_err}" if last_err else "")
                + "；启动阶段会再次尝试从官方 sensors 仓库下载。"
            )
            return {"status": "partial", "message": msg, "code_downloaded": False}

        os.makedirs(SENSOR_EXTENSION_DIR, exist_ok=True)
        dest = os.path.join(SENSOR_EXTENSION_DIR, f"{name}.py")
        with open(dest, "wb") as f:
            f.write(code_bytes)
        return {
            "status": "success",
            "message": f"Sensor '{name}' 配置已合并，代码已下载到 {dest}。",
            "code_downloaded": True,
        }

    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"安装 Sensor 失败: {str(e)}")


class UninstallSensorReq(BaseModel):
    name: str


@router.post("/market/sensors/uninstall")
def uninstall_sensor_api(req: UninstallSensorReq):
    """从 activate_sensor.json 移除该 Sensor 并删除本地代码文件"""
    try:
        name = req.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="缺少 sensor 名")

        cfg = get_sensor_config() or {}
        if name not in cfg:
            raise HTTPException(status_code=404, detail=f"未配置 Sensor '{name}'")

        del cfg[name]
        os.makedirs(os.path.dirname(SENSOR_CONFIG_PATH), exist_ok=True)
        _save_json_file(SENSOR_CONFIG_PATH, cfg)

        code_file = os.path.join(SENSOR_EXTENSION_DIR, f"{name}.py")
        if os.path.exists(code_file):
            os.remove(code_file)

        return {"status": "success", "message": f"Sensor '{name}' 已删除"}

    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"删除 Sensor 失败: {str(e)}")


# ==========================================
# 10. Graph 市场：Registry + 已安装列表 + 安装
# ==========================================
def _extract_registry_graphs(data) -> list:
    """从 registry 数据中提取 graphs 列表（兼容 graphs list 或 { graphs: [...] }）"""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("graphs", "items", "data"):
            if isinstance(data.get(key), list):
                return data[key]
    return []


@router.get("/market/graphs")
def get_graph_registry_api():
    """从官方 PurrPod/graphs 仓库拉取 registry.json 返回前端市场"""
    try:
        data = _http_get_json(GRAPHS_REGISTRY_URL)
        return {
            "version": data.get("version") if isinstance(data, dict) else None,
            "repository": data.get("repository") if isinstance(data, dict) else None,
            "graphs": _extract_registry_graphs(data),
        }
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=502, detail=f"拉取 Graph 注册表失败: {str(e)}")


@router.get("/market/graphs/installed")
def list_installed_graphs_api():
    """返回 ~/.purrcat/graph 目录下已安装的 graph（文件夹结构）名字列表"""
    try:
        names = {
            entry["name"]
            for entry in list_graphs()
            if isinstance(entry, dict) and entry.get("name")
        }
        return sorted(names)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(
            status_code=500, detail=f"读取本地 Graph 列表失败: {str(e)}"
        )


class InstallGraphReq(BaseModel):
    name: str


# ==========================================
# 11. Graph 依赖自动安装：安装 graph 前补齐其 dependencies 声明的 mcp/skill
# ==========================================
MCP_REGISTRY_URL = "https://raw.githubusercontent.com/PurrPod/mcps/main/registry.json"
SKILL_REGISTRY_URL = (
    "https://raw.githubusercontent.com/PurrPod/skills/main/registry.json"
)
# UI 插件（极简模式 webmin 插件系统）官方发布源
UI_PLUGIN_REGISTRY_URL = (
    "https://raw.githubusercontent.com/PurrPod/ui-plugins/main/registry.json"
)
UI_PLUGIN_CODE_BASE = (
    "https://raw.githubusercontent.com/PurrPod/ui-plugins/main/plugins"
)
# Agent Loop（PARADIGM 范式）官方发布源
AGENTLOOP_REGISTRY_URL = (
    "https://raw.githubusercontent.com/PurrPod/agentloops/main/registry.json"
)
AGENTLOOP_CODE_BASE = (
    "https://raw.githubusercontent.com/PurrPod/agentloops/main/agentloops"
)


def _ensure_graph_mcp_deps(mcp_names) -> list:
    """本地缺失的 MCP 依赖从市场安装；市场也缺失时跳过。返回处理说明列表"""
    notes = []
    names = [str(n).strip() for n in (mcp_names or []) if str(n).strip()]
    if not names:
        return notes

    configured = set(get_mcp_config().get("mcpServers", {}).keys())
    missing = [n for n in names if n not in configured]
    if not missing:
        return notes

    data = _http_get_json(MCP_REGISTRY_URL)
    raw = data.get("mcps", []) if isinstance(data, dict) else data
    entries = list(raw.values()) if isinstance(raw, dict) else (raw or [])

    merged_servers = {}
    repo_server_pairs = []  # (repo, [server names])
    for name in missing:
        target = None
        for e in entries:
            if not isinstance(e, dict):
                continue
            servers = e.get("mcpServers") or {}
            if str(e.get("name", "")).lower() == name.lower() or any(
                k.lower() == name.lower() for k in servers
            ):
                target = e
                break
        if not target or not target.get("mcpServers"):
            notes.append(f"MCP '{name}' 本地与市场均缺失，已跳过")
            continue
        merged_servers.update(target["mcpServers"])
        repo_server_pairs.append(
            (target.get("repo") or "", list(target["mcpServers"].keys()))
        )

    if not merged_servers:
        return notes

    # 合并配置落盘
    existing_config = get_mcp_config()
    existing_config.setdefault("mcpServers", {}).update(merged_servers)
    os.makedirs(os.path.dirname(MCP_CONFIG_PATH), exist_ok=True)
    with open(MCP_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(existing_config, f, indent=2, ensure_ascii=False)

    # 官方源码下载（失败不阻断配置安装）
    for repo, server_names in repo_server_pairs:
        try:
            _download_official_mcp_source(repo, server_names)
        except Exception as e:
            traceback.print_exc()

    # 热更新 Schema 与检索树
    refresh_schemas()
    MCPSearcher().reload_index()
    rebuild_vectors_async()
    notes.append(f"已从市场自动安装 MCP 依赖: {', '.join(merged_servers.keys())}")
    return notes


def _ensure_graph_skill_deps(skill_names) -> list:
    """本地缺失的 Skill 依赖从市场安装；市场也缺失时跳过。返回处理说明列表"""
    notes = []
    names = [str(n).strip() for n in (skill_names or []) if str(n).strip()]
    if not names:
        return notes

    try:
        local_names = set()
        for s in SkillSearcher().skills:
            local_names.add(str(s.get("name", "")).lower())
            local_names.add(str(s.get("dir_name", "")).lower())
    except Exception:
        local_names = set()

    missing = [n for n in names if n.lower() not in local_names]
    if not missing:
        return notes

    data = _http_get_json(SKILL_REGISTRY_URL)
    raw = data.get("skills", {}) if isinstance(data, dict) else {}
    items = list(raw.items()) if isinstance(raw, dict) else enumerate(raw or [])

    installed = []
    for name in missing:
        target = None
        for key, e in items:
            if not isinstance(e, dict):
                continue
            if (
                str(key or "").lower() == name.lower()
                or str(e.get("name", "")).lower() == name.lower()
            ):
                target = e
                break
        link = (target or {}).get("skill-single-link") or ""
        if not link:
            notes.append(f"Skill '{name}' 本地与市场均缺失，已跳过")
            continue
        try:
            installed.append(_download_skill_from_github(link))
        except Exception as e:
            traceback.print_exc()
            notes.append(f"Skill '{name}' 安装失败({e})，已跳过")

    if installed:
        SkillSearcher().reload_index()
        rebuild_skill_vectors_async()
        notes.append(f"已从市场自动安装 Skill 依赖: {', '.join(installed)}")
    return notes


@router.post("/market/graphs/install")
def install_graph_api(req: InstallGraphReq):
    """
    安装 Graph（文件夹结构）：
      从 registry 拿到该 graph 的文件清单（graph.json + asset/* 等），
      逐文件从 PurrPod/graphs 仓库下载写入 {GRAPHS_DIR}/{name}/；
      安装前检查 graph.json 声明的 mcp/skill 依赖，本地缺失的先从市场安装，市场也缺失时跳过
    """
    try:
        name = req.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="缺少 graph name")
        safe_name = os.path.basename(name).replace("\\", "/")
        if not safe_name or safe_name in (".", ".."):
            raise HTTPException(status_code=400, detail="非法 graph name")

        # 1) 从 registry 取条目与文件清单
        try:
            registry = _http_get_json(GRAPHS_REGISTRY_URL)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"拉取 Graph 注册表失败: {e}")
        entry = next(
            (
                g
                for g in _extract_registry_graphs(registry)
                if isinstance(g, dict)
                and str(g.get("name", "")).strip().lower() == safe_name.lower()
            ),
            None,
        )
        if entry is None:
            raise HTTPException(
                status_code=404, detail=f"市场注册表中找不到 Graph '{safe_name}'"
            )

        files = [str(f) for f in (entry.get("files") or []) if str(f).strip()]
        if "graph.json" not in files:
            files.insert(0, "graph.json")
        # 相对路径防御：不允许绝对路径 / 上跳
        for rel in files:
            if rel.startswith(("/", "\\")) or ".." in rel.replace("\\", "/").split("/"):
                raise HTTPException(
                    status_code=502, detail=f"注册表文件清单含非法路径: {rel}"
                )

        # 2) 重装场景下清掉旧目录，保证与市场版本一致
        target_dir = os.path.join(GRAPHS_DIR, safe_name)
        if os.path.isdir(target_dir):
            shutil.rmtree(target_dir)
        os.makedirs(target_dir, exist_ok=True)

        graph_data = None
        downloaded = []
        for rel in files:
            url = f"{GRAPHS_CODE_BASE}/{safe_name}/{rel}"
            try:
                raw = _http_download(url)
            except Exception as e:
                raise HTTPException(
                    status_code=502, detail=f"下载 Graph 文件失败 ({url}): {e}"
                )
            dest = os.path.join(target_dir, *rel.replace("\\", "/").split("/"))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "wb") as f:
                f.write(raw)
            downloaded.append(rel)

            if rel == "graph.json":
                try:
                    graph_data = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as e:
                    raise HTTPException(
                        status_code=502, detail=f"Graph JSON 解析失败: {e}"
                    )

        if not isinstance(graph_data, dict):
            raise HTTPException(status_code=502, detail="Graph JSON 顶层必须是对象")

        # 🌟 依赖补齐：graph 声明的 mcps/skills，本地缺失的先从市场安装（缺失即跳过）
        try:
            deps = graph_data.get("dependencies", {}) or {}
            dep_notes = _ensure_graph_mcp_deps(deps.get("mcps", []))
            dep_notes += _ensure_graph_skill_deps(deps.get("skills", []))
        except Exception as e:
            traceback.print_exc()
            dep_notes = [f"依赖检测失败({e})，已跳过"]

        message = (
            f"Graph '{safe_name}' 已安装到 {target_dir}（{len(downloaded)} 个文件）"
        )
        if dep_notes:
            message += "。" + "；".join(dep_notes)
        return {
            "status": "success",
            "message": message,
        }
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"安装 Graph 失败: {str(e)}")


class UninstallGraphReq(BaseModel):
    name: str


@router.post("/market/graphs/uninstall")
def uninstall_graph_api(req: UninstallGraphReq):
    """删除 {GRAPHS_DIR}/{name} 文件夹（新目录结构）"""
    try:
        name = req.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="缺少 graph name")
        safe_name = os.path.basename(name).replace("\\", "/")
        if not safe_name or safe_name in (".", ".."):
            raise HTTPException(status_code=400, detail="非法 graph name")

        target_dir = os.path.join(GRAPHS_DIR, safe_name)
        if not os.path.isdir(target_dir):
            raise HTTPException(status_code=404, detail=f"未安装 Graph '{safe_name}'")

        shutil.rmtree(target_dir)
        return {"status": "success", "message": f"Graph '{safe_name}' 已删除"}

    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"删除 Graph 失败: {str(e)}")


# ==========================================
# 12. UI 插件市场：Registry + 已安装列表 + 安装（含依赖自动补齐）+ 卸载
# ==========================================
def _extract_registry_items(data, *keys) -> list:
    """从 registry 数据中提取条目列表（兼容 list 与 { <key>: [...] } / { items|data: [...] }）。"""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in tuple(keys) + ("items", "data"):
            if isinstance(data.get(key), list):
                return data[key]
    return []


def _normalize_dependency_list(raw) -> list:
    """归一化依赖清单：只保留白名单类型，统一为 {"type","id"}（白名单即宿主的 DEP_TYPES）。"""
    out = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if not isinstance(item, dict):
            continue
        dep_type = str(item.get("type") or "").strip()
        dep_id = str(item.get("id") or "").strip()
        if dep_type in DEP_TYPES and dep_id:
            out.append({"type": dep_type, "id": dep_id})
    return out


def _scan_installed_ui_plugins() -> list:
    """列出「用户根 + 沙盒根」下已安装的 UI 插件（含 plugin.json 的目录，跳过 <id>.trash）。"""
    names = set()
    for root_dir in (USER_PLUGIN_ROOT, SANDBOX_PLUGIN_ROOT):
        if not os.path.isdir(root_dir):
            continue
        for name in os.listdir(root_dir):
            if name.endswith(".trash"):
                continue
            if os.path.isfile(os.path.join(root_dir, name, "plugin.json")):
                names.add(name)
    return sorted(names)


def _install_sensor_by_name(name: str) -> str:
    """按名字从官方 sensors 市场安装一个 Sensor，返回处理说明。"""
    safe_name = os.path.basename(str(name or "")).replace("\\", "/")
    if not safe_name or safe_name in (".", ".."):
        raise HTTPException(status_code=400, detail="非法 sensor name")
    registry = _http_get_json(SENSORS_REGISTRY_URL)
    sensors = registry.get("sensors", []) if isinstance(registry, dict) else []
    entry = next(
        (
            s
            for s in sensors
            if isinstance(s, dict)
            and str(s.get("name", "")).strip().lower() == safe_name.lower()
        ),
        None,
    )
    if entry is None:
        raise HTTPException(
            status_code=404, detail=f"市场注册表中找不到 Sensor '{safe_name}'"
        )
    res = install_sensor_api(InstallSensorReq(sensor=entry))
    return (res or {}).get("message") or f"Sensor '{safe_name}' 已安装"


def _install_graph_by_name(name: str) -> dict:
    """按名字从官方 graphs 市场安装一个 Graph（含其声明的 mcp/skill 依赖）。"""
    return install_graph_api(InstallGraphReq(name=name))


def _install_agentloop_by_name(name: str) -> str:
    """按名字从官方 agentloop 市场安装一个 Agent Loop（范式）到 paradigms 目录。"""
    safe_name = os.path.basename(str(name or "")).replace("\\", "/")
    if not safe_name or safe_name in (".", ".."):
        raise HTTPException(status_code=400, detail="非法 agentloop name")

    registry = _http_get_json(AGENTLOOP_REGISTRY_URL)
    entry = next(
        (
            a
            for a in _extract_registry_items(registry, "agentloops")
            if isinstance(a, dict)
            and str(a.get("name", "")).strip().lower() == safe_name.lower()
        ),
        None,
    )
    if entry is None:
        raise HTTPException(
            status_code=404, detail=f"市场注册表中找不到 AgentLoop '{safe_name}'"
        )

    files = [str(f) for f in (entry.get("files") or []) if str(f).strip()]
    if f"{safe_name}.yaml" not in files:
        files.insert(0, f"{safe_name}.yaml")
    for rel in files:
        if rel.startswith(("/", "\\")) or ".." in rel.replace("\\", "/").split("/"):
            raise HTTPException(
                status_code=502, detail=f"注册表文件清单含非法路径: {rel}"
            )

    os.makedirs(PARADIGMS_DIR, exist_ok=True)
    written = []
    for rel in files:
        url = f"{AGENTLOOP_CODE_BASE}/{rel}"
        try:
            raw = _http_download(url)
        except Exception as e:
            raise HTTPException(
                status_code=502, detail=f"下载 AgentLoop 文件失败 ({url}): {e}"
            )
        dest = os.path.join(PARADIGMS_DIR, *rel.replace("\\", "/").split("/"))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as f:
            f.write(raw)
        written.append(rel)

    # 落盘后做一次 YAML 解析校验：失败时报错但不回滚已写入文件
    for rel in written:
        if not rel.endswith((".yaml", ".yml")):
            continue
        path = os.path.join(PARADIGMS_DIR, *rel.replace("\\", "/").split("/"))
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if not isinstance(data, dict) or not data.get("hooks"):
                raise ValueError("YAML 缺少 hooks 字段")
        except Exception as e:
            raise HTTPException(
                status_code=502, detail=f"AgentLoop 文件校验失败 ({rel}): {e}"
            )

    return f"AgentLoop '{safe_name}' 已安装到 {PARADIGMS_DIR}（{len(written)} 个文件）"


def _ui_plugin_root_dir(raw_root) -> str:
    """把插件声明的 root 映射为落盘根目录（user → 用户根，sandbox → 沙盒根）。

    内置插件随 App 分发、只读，不接受从市场安装；root 缺失或非法时按用户根兜底。
    """
    key = str(raw_root or "").strip().lower()
    if key == "builtin":
        raise HTTPException(
            status_code=400, detail="内置插件随 App 分发，不支持从市场安装"
        )
    return ROOT_TO_DIR.get(key) or USER_PLUGIN_ROOT


def _install_ui_plugin_entry(entry: dict, notes: list, seen: set) -> dict:
    """按注册表条目把 UI 插件文件夹落盘到其声明的 root，然后递归补齐其依赖。"""
    name = str(entry.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=502, detail="UI 插件注册表条目缺少 name")

    files = [str(f) for f in (entry.get("files") or []) if str(f).strip()]
    if "plugin.json" not in files:
        files.insert(0, "plugin.json")
    # 相对路径防御：不允许绝对路径 / 上跳
    for rel in files:
        if rel.startswith(("/", "\\")) or ".." in rel.replace("\\", "/").split("/"):
            raise HTTPException(
                status_code=502, detail=f"注册表文件清单含非法路径: {rel}"
            )

    # 落盘根由注册表条目声明的 root 决定（user → 用户根，sandbox → 沙盒根），
    # 不再全部塞进用户根；内置插件不接受市场安装。
    root_dir = _ui_plugin_root_dir(entry.get("root"))
    # 重装场景：清掉两个可写根下同名的旧目录，避免旧根残留把新装位置遮住（用户根优先级更高）
    for stale_root in (USER_PLUGIN_ROOT, SANDBOX_PLUGIN_ROOT):
        stale_dir = os.path.join(stale_root, name)
        if os.path.isdir(stale_dir):
            plugin_runtime.stop(name)
            shutil.rmtree(stale_dir)
    target_dir = os.path.join(root_dir, name)
    os.makedirs(target_dir, exist_ok=True)

    plugin_data = None
    downloaded = []
    for rel in files:
        url = f"{UI_PLUGIN_CODE_BASE}/{name}/{rel}"
        try:
            raw = _http_download(url)
        except Exception as e:
            raise HTTPException(
                status_code=502, detail=f"下载 UI 插件文件失败 ({url}): {e}"
            )
        dest = os.path.join(target_dir, *rel.replace("\\", "/").split("/"))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as f:
            f.write(raw)
        downloaded.append(rel)
        if rel == "plugin.json":
            try:
                plugin_data = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as e:
                raise HTTPException(
                    status_code=502, detail=f"UI 插件 plugin.json 解析失败: {e}"
                )

    if not isinstance(plugin_data, dict):
        raise HTTPException(status_code=502, detail="UI 插件缺少合法的 plugin.json")

    # 依赖：注册表条目声明优先，其次回退到 plugin.json 的 dependency 字段
    deps = _normalize_dependency_list(entry.get("dependency"))
    if not deps:
        deps = _normalize_dependency_list(plugin_data.get("dependency"))
    for dep in deps:
        _ensure_market_dep(dep["type"], dep["id"], notes, seen)

    return {
        "status": "success",
        "message": f"UI 插件 '{name}' 已安装到 {target_dir}（{len(downloaded)} 个文件）",
    }


def _install_ui_plugin_by_name(name: str, notes: list = None, seen: set = None) -> dict:
    """从官方 ui-plugin 仓库按名字安装一个 UI 插件（seen 防依赖成环）。"""
    notes = notes if notes is not None else []
    seen = seen if seen is not None else set()
    safe_name = os.path.basename(str(name or "")).replace("\\", "/")
    if not safe_name or safe_name in (".", ".."):
        raise HTTPException(status_code=400, detail="非法 UI 插件 name")
    if safe_name in seen:
        return {
            "status": "skip",
            "message": f"UI 插件 '{safe_name}' 已在本次安装链中处理过",
        }
    seen.add(safe_name)

    registry = _http_get_json(UI_PLUGIN_REGISTRY_URL)
    entry = next(
        (
            p
            for p in _extract_registry_items(registry, "plugins")
            if isinstance(p, dict)
            and str(p.get("name", "")).strip().lower() == safe_name.lower()
        ),
        None,
    )
    if entry is None:
        raise HTTPException(
            status_code=404, detail=f"市场注册表中找不到 UI 插件 '{safe_name}'"
        )
    return _install_ui_plugin_entry(entry, notes, seen)


def _ensure_market_dep(dep_type: str, dep_id: str, notes: list, seen: set) -> None:
    """按类型把一个依赖交给对应安装通道；失败只记 notes，不中断整单安装。"""
    try:
        if dep_type == "skill":
            notes.extend(_ensure_graph_skill_deps([dep_id]))
        elif dep_type == "mcp":
            notes.extend(_ensure_graph_mcp_deps([dep_id]))
        elif dep_type == "sensor":
            notes.append(_install_sensor_by_name(dep_id))
        elif dep_type == "graph":
            notes.append(
                _install_graph_by_name(dep_id).get("message")
                or f"Graph '{dep_id}' 已安装"
            )
        elif dep_type == "plugin":
            notes.append(
                _install_ui_plugin_by_name(dep_id, notes, seen).get("message")
                or f"UI 插件 '{dep_id}' 已处理"
            )
        elif dep_type == "agentloop":
            notes.append(_install_agentloop_by_name(dep_id))
        else:
            notes.append(f"不支持的依赖类型 '{dep_type}'，已跳过")
    except HTTPException as e:
        notes.append(f"{dep_type} 依赖 '{dep_id}' 安装失败({e.detail})，已跳过")
    except Exception as e:
        traceback.print_exc()
        notes.append(f"{dep_type} 依赖 '{dep_id}' 安装失败({e})，已跳过")


class InstallUiPluginReq(BaseModel):
    name: str


class UninstallUiPluginReq(BaseModel):
    name: str


@router.get("/market/ui-plugins")
def get_ui_plugin_registry_api():
    """从官方 PurrPod/ui-plugins 仓库拉取 registry.json 返回前端市场"""
    try:
        data = _http_get_json(UI_PLUGIN_REGISTRY_URL)
        return {
            "version": data.get("version") if isinstance(data, dict) else None,
            "repository": data.get("repository") if isinstance(data, dict) else None,
            "plugins": _extract_registry_items(data, "plugins"),
        }
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=502, detail=f"拉取 UI 插件注册表失败: {str(e)}")


@router.get("/market/ui-plugins/installed")
def list_installed_ui_plugins_api():
    """返回已安装的 UI 插件名字列表（用户根 + 沙盒根两个可写根合并去重）"""
    try:
        return _scan_installed_ui_plugins()
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(
            status_code=500, detail=f"读取本地 UI 插件列表失败: {str(e)}"
        )


@router.post("/market/ui-plugins/install")
def install_ui_plugin_api(req: InstallUiPluginReq):
    """
    安装 UI 插件到其注册表条目声明的 root（user → 用户根 ~/.purrcat/webmin-plugins，
    sandbox → 沙盒根 {AGENT_VM_DIR}/ui-plugin）：
      从 registry 拿到该插件的文件清单，逐文件从 PurrPod/ui-plugins 仓库下载落盘；
      再按插件声明的 dependency 逐一补齐 skill/mcp/sensor/graph/agentloop/plugin 依赖，
      缺失或失败只记录说明，不阻断插件本体安装。
    """
    try:
        name = req.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="缺少 UI 插件 name")
        notes = []
        res = _install_ui_plugin_by_name(name, notes, set())
        message = res.get("message") or f"UI 插件 '{name}' 已安装"
        if notes:
            message += "。" + "；".join(notes)
        return {"status": "success", "message": message}
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"安装 UI 插件失败: {str(e)}")


@router.post("/market/ui-plugins/uninstall")
def uninstall_ui_plugin_api(req: UninstallUiPluginReq):
    """卸载 UI 插件：在用户根 / 沙盒根中找到该插件目录，移动为同根下的 <name>.trash（可恢复）。"""
    try:
        name = req.name.strip()
        if not name or any(c in name for c in ("/", "\\", "..")):
            raise HTTPException(status_code=400, detail="非法的插件 name")

        target = None
        for root_dir in (USER_PLUGIN_ROOT, SANDBOX_PLUGIN_ROOT):
            cand = os.path.join(root_dir, name)
            if os.path.isdir(cand):
                target = cand
                break
        if target is None:
            raise HTTPException(status_code=404, detail=f"未安装 UI 插件 '{name}'")

        trash = f"{target}.trash"
        if os.path.exists(trash):
            shutil.rmtree(trash, ignore_errors=True)
        plugin_runtime.stop(name)  # 先停插件自带的后端子进程，再移动目录
        shutil.move(target, trash)
        return {"status": "success", "message": f"UI 插件 '{name}' 已删除"}
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"卸载 UI 插件失败: {str(e)}")


# ==========================================
# 13. AgentLoop 市场：Registry + 已安装列表 + 安装（含依赖补齐）+ 卸载
# ==========================================
def _scan_installed_agentloops() -> list:
    """列出 paradigms 目录下已安装的 AgentLoop 名字（去掉 .yaml/.yml 后缀）。"""
    names = []
    if not os.path.isdir(PARADIGMS_DIR):
        return names
    for f in sorted(os.listdir(PARADIGMS_DIR)):
        if f.endswith((".yaml", ".yml")):
            names.append(os.path.splitext(f)[0])
    return names


class InstallAgentloopReq(BaseModel):
    name: str


class UninstallAgentloopReq(BaseModel):
    name: str


@router.get("/market/agentloops")
def get_agentloop_registry_api():
    """从官方 PurrPod/agentloops 仓库拉取 registry.json 返回前端市场"""
    try:
        data = _http_get_json(AGENTLOOP_REGISTRY_URL)
        return {
            "version": data.get("version") if isinstance(data, dict) else None,
            "repository": data.get("repository") if isinstance(data, dict) else None,
            "agentloops": _extract_registry_items(data, "agentloops"),
        }
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(
            status_code=502, detail=f"拉取 AgentLoop 注册表失败: {str(e)}"
        )


@router.get("/market/agentloops/installed")
def list_installed_agentloops_api():
    """返回 paradigms 目录（~/.purrcat/paradigms）下已安装的 AgentLoop 名字列表"""
    try:
        return _scan_installed_agentloops()
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(
            status_code=500, detail=f"读取本地 AgentLoop 列表失败: {str(e)}"
        )


@router.post("/market/agentloops/install")
def install_agentloop_api(req: InstallAgentloopReq):
    """
    安装 AgentLoop（范式 YAML）到 ~/.purrcat/paradigms：
      从注册表取文件清单，逐文件从 PurrPod/agentloops 仓库下载落盘，
      落盘后解析 YAML 校验 hooks；缺失或校验失败会报错。
    """
    try:
        name = req.name.strip()
        if not name or any(c in name for c in ("/", "\\", "..")):
            raise HTTPException(status_code=400, detail="非法的 AgentLoop name")
        return {"status": "success", "message": _install_agentloop_by_name(name)}
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"安装 AgentLoop 失败: {str(e)}")


@router.post("/market/agentloops/uninstall")
def uninstall_agentloop_api(req: UninstallAgentloopReq):
    """卸载 AgentLoop：删除 paradigms 目录下对应的 YAML（默认 PARADIGM 除外）。"""
    try:
        name = req.name.strip()
        if not name or any(c in name for c in ("/", "\\", "..")):
            raise HTTPException(status_code=400, detail="非法的 AgentLoop name")
        if name.lower() == "paradigm":
            raise HTTPException(
                status_code=400, detail="默认 AgentLoop（PARADIGM）不可删除"
            )

        target = os.path.join(PARADIGMS_DIR, f"{name}.yaml")
        if not os.path.isfile(target):
            raise HTTPException(status_code=404, detail=f"未安装 AgentLoop '{name}'")
        os.remove(target)
        return {"status": "success", "message": f"AgentLoop '{name}' 已删除"}
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"卸载 AgentLoop 失败: {str(e)}")
