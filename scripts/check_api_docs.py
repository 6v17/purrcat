#!/usr/bin/env python3
"""校验 docs/api/ 下的 API 文档与 src/server 的真实路由是否一致。

只做**校验**，绝不改写文档。若发现漂移则非零退出，供 CI 拦截。

用法：
    python scripts/check_api_docs.py

比对范围：
    真实路由 = src/server/api/*.py 的全部路由 + main.py 中 /api 开头的路由
    文档路由 = docs/api/**/*.md 中的表格行（如 “| GET | ` /api/xxx ` |”）
              以及标题（如 “### GET ` /api/xxx ` ”）
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API_DIR = ROOT / "src" / "server" / "api"
MAIN_PY = ROOT / "main.py"
DOCS_DIR = ROOT / "docs" / "api"

HTTP_METHODS = {"get", "post", "put", "delete", "patch", "head", "options"}
VALID_METHODS = {m.upper() for m in HTTP_METHODS} | {"WS"}


def normalize_path(path: str) -> str:
    """去掉 FastAPI 路径转换器后缀：{name:path} -> {name}。"""
    return re.sub(r"\{([^}:]+):[^}]+\}", r"{\1}", path)


def _router_prefixes(tree: ast.Module) -> dict[str, str]:
    prefixes = {"app": ""}
    for node in tree.body:
        if not (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)):
            continue
        func = node.value.func
        fname = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
        if fname not in ("APIRouter", "FastAPI"):
            continue
        target = node.targets[0]
        name = target.id if isinstance(target, ast.Name) else "?"
        prefix = ""
        for kw in node.value.keywords:
            if kw.arg == "prefix" and isinstance(kw.value, ast.Constant):
                prefix = str(kw.value.value)
        prefixes[name] = prefix
    return prefixes


def extract_routes() -> set[tuple[str, str]]:
    """从源码中抽取 (方法, 归一化路径)。"""
    routes: set[tuple[str, str]] = set()
    files = [p for p in sorted(API_DIR.glob("*.py")) if p.name != "__init__.py"]
    if MAIN_PY.is_file():
        files.append(MAIN_PY)

    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
        prefixes = _router_prefixes(tree)
        is_main = path == MAIN_PY
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                if not (
                    isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)
                ):
                    continue
                obj = dec.func.value
                if not (isinstance(obj, ast.Name) and obj.id in prefixes):
                    continue
                attr = dec.func.attr
                if attr == "websocket":
                    method = "WS"
                elif attr in HTTP_METHODS:
                    method = attr.upper()
                else:
                    continue
                sub = ""
                if dec.args and isinstance(dec.args[0], ast.Constant):
                    sub = str(dec.args[0].value)
                full = normalize_path(prefixes[obj.id] + sub)
                if is_main and not full.startswith("/api"):
                    continue
                routes.add((method, full))
    return routes


DOC_ROW_RE = re.compile(
    r"^\|\s*([A-Z]{2,7}(?:\s*/\s*[A-Z]{2,7})*)\s*\|\s*`(/(?:api|acp)/[^`]+)`"
)
DOC_HEAD_RE = re.compile(
    r"^#{1,6}\s+([A-Z]{2,7}(?:\s*/\s*[A-Z]{2,7})*)\s+`(/(?:api|acp)/[^`]+)`"
)


def _is_real_path(path: str) -> bool:
    """过滤文档中的示例/通配路径（/api/...、/api/*、含占位尖括号等）。"""
    return not any(ch in path for ch in ("*", "<", " ")) and "..." not in path


def extract_documented() -> set[tuple[str, str]]:
    """从 docs/api 下所有 Markdown 中抽取 (方法, 归一化路径)。"""
    documented: set[tuple[str, str]] = set()
    for doc in sorted(DOCS_DIR.rglob("*.md")):
        for line in doc.read_text(encoding="utf-8").splitlines():
            for regex in (DOC_HEAD_RE, DOC_ROW_RE):
                m = regex.match(line)
                if not m:
                    continue
                path = normalize_path(m.group(2))
                if not _is_real_path(path):
                    continue
                for method in m.group(1).split("/"):
                    method = method.strip()
                    if method in VALID_METHODS:
                        documented.add((method, path))
    return documented


def main() -> int:
    if not DOCS_DIR.is_dir():
        print(f"[ERROR] 文档目录不存在：{DOCS_DIR}", file=sys.stderr)
        return 1

    actual = extract_routes()
    documented = extract_documented()

    missing = sorted(actual - documented)  # 代码有、文档缺
    stale = sorted(documented - actual)  # 文档有、代码无

    print(f"源码路由 {len(actual)} 个，文档记录 {len(documented)} 个")

    if not missing and not stale:
        print("[OK] 文档与 src/server 路由一致")
        return 0

    if missing:
        print(f"\n[缺文档] 代码中存在但文档未记录（{len(missing)}）：")
        for method, path in missing:
            print(f"  {method:6} {path}")
    if stale:
        print(f"\n[过期] 文档记录了但代码中不存在（{len(stale)}）：")
        for method, path in stale:
            print(f"  {method:6} {path}")
    print("\n请更新 docs/api/ 下的文档后重试（本脚本只校验，不会自动改写文档）。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
