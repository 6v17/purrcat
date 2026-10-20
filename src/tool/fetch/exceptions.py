class FetchExecutionError(Exception):
    """基础的 Fetch 异常"""

    pass


class SkillNotFoundError(FetchExecutionError):
    """技能未找到异常"""

    def __init__(self, name: str):
        self.name = name
        super().__init__(f"未找到技能: {name}")


class MCPServerNotFoundError(FetchExecutionError):
    """MCP 服务器未找到异常"""

    def __init__(self, serve_name: str, available_servers: list):
        self.serve_name = serve_name
        self.available_servers = available_servers
        super().__init__(f"未找到 MCP 服务器: {serve_name}")


class MCPToolNotFoundError(FetchExecutionError):
    """MCP 工具未找到异常"""

    def __init__(self, serve_name: str, tool_names: list, available_tools: list):
        self.serve_name = serve_name
        self.tool_names = tool_names
        self.available_tools = available_tools
        super().__init__(f"MCP 服务器 {serve_name} 中未找到工具")


class MCPRefreshInProgressError(FetchExecutionError):
    """Schema 缓存正在刷新（合并 MCP 后的热加载），本次查询结果不可信，需稍候重试"""

    def __init__(self, serve_name: str = ""):
        self.serve_name = serve_name
        super().__init__(f"MCP Schema 缓存正在刷新（查询 {serve_name}）")


class WebNetworkError(FetchExecutionError):
    """Web 抓取网络异常"""

    pass
