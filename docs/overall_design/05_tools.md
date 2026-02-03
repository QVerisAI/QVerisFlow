# 工具系统设计

## 1. 设计理念

基于 Anthropic Claude Agent SDK 的核心原则：**给 Agent 一台计算机**

工具系统分为三个层次：

```
┌─────────────────────────────────────────────────────────────┐
│                      工具系统架构                            │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │               第一层：核心工具（必备）                  │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────────────┐   │   │
│  │  │ 文件系统  │  │   Bash   │  │    代码执行       │   │   │
│  │  │ ls/read/ │  │ execute  │  │  Python/JS       │   │   │
│  │  │ write    │  │          │  │                  │   │   │
│  │  └──────────┘  └──────────┘  └──────────────────┘   │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │               第二层：业务工具（领域相关）              │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────────────┐   │   │
│  │  │ 数据查询  │  │ 搜索工具  │  │    分析工具       │   │   │
│  │  │ 财务/行情 │  │ 公告/研报 │  │  技术/基本面     │   │   │
│  │  └──────────┘  └──────────┘  └──────────────────┘   │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │               第三层：扩展工具（外部服务）              │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────────────┐   │   │
│  │  │   MCP    │  │ 外部 API │  │    自定义工具     │   │   │
│  │  │ Protocol │  │          │  │                  │   │   │
│  │  └──────────┘  └──────────┘  └──────────────────┘   │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. 工具注册表

```python
# etf_common/agent_framework/tools/tool_registry.py

from typing import Dict, List, Optional, Callable, Any
from pathlib import Path
import importlib
import yaml

from .tool_definition import ToolDefinition, ToolCategory


class ToolRegistry:
    """
    工具注册表
    
    支持：
    - @工具名 引用解析
    - 按分类查询
    - 动态注册
    - YAML 配置加载
    """
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._tools: Dict[str, ToolDefinition] = {}
        self._implementations: Dict[str, Callable] = {}
        self._alias_map: Dict[str, str] = {}  # alias -> tool_id
        self._category_index: Dict[ToolCategory, List[str]] = {}
        self._initialized = True
    
    # ========== 注册方法 ==========
    
    def register(
        self,
        definition: ToolDefinition,
        implementation: Callable = None
    ) -> None:
        """
        注册工具
        
        Args:
            definition: 工具定义
            implementation: 工具实现函数（可选，延迟绑定）
        """
        tool_id = definition.tool_id
        
        self._tools[tool_id] = definition
        self._alias_map[definition.alias] = tool_id
        
        if implementation:
            self._implementations[tool_id] = implementation
        
        # 更新分类索引
        category = definition.category
        if category not in self._category_index:
            self._category_index[category] = []
        if tool_id not in self._category_index[category]:
            self._category_index[category].append(tool_id)
    
    def register_implementation(
        self,
        tool_id: str,
        implementation: Callable
    ) -> None:
        """注册工具实现"""
        if tool_id not in self._tools:
            raise ValueError(f"工具 {tool_id} 未定义")
        self._implementations[tool_id] = implementation
    
    def register_from_yaml(self, yaml_path: str) -> None:
        """从 YAML 文件注册工具"""
        path = Path(yaml_path)
        
        if path.is_dir():
            for yaml_file in path.glob("*.yaml"):
                self._load_yaml_tool(yaml_file)
        else:
            self._load_yaml_tool(path)
    
    def _load_yaml_tool(self, yaml_path: Path) -> None:
        """加载单个 YAML 工具定义"""
        with open(yaml_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        
        definition = ToolDefinition(**data)
        self.register(definition)
    
    # ========== 查询方法 ==========
    
    def get(self, tool_id: str) -> Optional[ToolDefinition]:
        """通过 ID 获取工具"""
        return self._tools.get(tool_id)
    
    def get_by_alias(self, alias: str) -> Optional[ToolDefinition]:
        """通过别名获取工具（@工具名 解析）"""
        tool_id = self._alias_map.get(alias)
        return self._tools.get(tool_id) if tool_id else None
    
    def get_by_category(self, category: ToolCategory) -> List[ToolDefinition]:
        """按分类获取工具"""
        tool_ids = self._category_index.get(category, [])
        return [self._tools[tid] for tid in tool_ids]
    
    def list_all(self) -> List[ToolDefinition]:
        """列出所有工具"""
        return list(self._tools.values())
    
    def list_aliases(self) -> List[str]:
        """列出所有工具别名"""
        return list(self._alias_map.keys())
    
    # ========== 执行方法 ==========
    
    async def execute(
        self,
        tool_id: str,
        params: Dict[str, Any],
        context: Dict[str, Any] = None
    ) -> Any:
        """
        执行工具
        
        Args:
            tool_id: 工具 ID
            params: 参数字典
            context: 执行上下文（workspace 等）
            
        Returns:
            工具执行结果
        """
        if tool_id not in self._tools:
            raise ValueError(f"工具 {tool_id} 未注册")
        
        if tool_id not in self._implementations:
            raise ValueError(f"工具 {tool_id} 未实现")
        
        definition = self._tools[tool_id]
        implementation = self._implementations[tool_id]
        
        # 注入上下文
        if context:
            params = {**params, "_context": context}
        
        # 执行
        if definition.is_async:
            result = await implementation(**params)
        else:
            result = implementation(**params)
        
        return result
    
    async def execute_by_alias(
        self,
        alias: str,
        params: Dict[str, Any],
        context: Dict[str, Any] = None
    ) -> Any:
        """通过别名执行工具"""
        tool_id = self._alias_map.get(alias)
        if not tool_id:
            raise ValueError(f"工具别名 @{alias} 未注册")
        return await self.execute(tool_id, params, context)
    
    # ========== 转换方法 ==========
    
    def to_openai_functions(
        self,
        tool_ids: List[str] = None
    ) -> List[Dict[str, Any]]:
        """转换为 OpenAI Function Calling 格式"""
        tools = self._tools.values()
        if tool_ids:
            tools = [t for t in tools if t.tool_id in tool_ids]
        
        return [t.to_function_schema() for t in tools]
    
    def to_prompt_descriptions(
        self,
        tool_ids: List[str] = None
    ) -> str:
        """生成工具描述文本（用于 Prompt）"""
        tools = self._tools.values()
        if tool_ids:
            tools = [t for t in tools if t.tool_id in tool_ids]
        
        return "\n\n".join([t.to_prompt_description() for t in tools])


# ========== 工具装饰器 ==========

def tool(
    tool_id: str,
    name: str,
    alias: str,
    description: str,
    category: ToolCategory,
    input_schema: Dict[str, Any],
    output_schema: Dict[str, Any] = None,
    **kwargs
):
    """
    工具注册装饰器
    
    用法：
    @tool(
        tool_id="stock_price",
        name="股票价格查询",
        alias="股票价格",
        description="查询股票的历史价格数据",
        category=ToolCategory.STOCK_DATA,
        input_schema={...}
    )
    async def get_stock_price(ticker: str, start_date: str, end_date: str):
        ...
    """
    def decorator(func: Callable):
        definition = ToolDefinition(
            tool_id=tool_id,
            name=name,
            alias=alias,
            description=description,
            category=category,
            input_schema=input_schema,
            output_schema=output_schema or {"type": "object"},
            **kwargs
        )
        
        registry = ToolRegistry()
        registry.register(definition, func)
        
        return func
    
    return decorator
```

---

## 3. 核心工具：文件系统

```python
# etf_common/agent_framework/tools/file_tools.py

from typing import List, Dict, Any
from .tool_registry import tool, ToolCategory


@tool(
    tool_id="file_ls",
    name="列出目录",
    alias="列出目录",
    description="列出指定目录下的文件和子目录",
    category=ToolCategory.FILE_SYSTEM,
    input_schema={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "目录路径（相对于工作空间）"
            }
        },
        "required": ["path"]
    }
)
async def file_ls(path: str, _context: Dict = None) -> List[str]:
    """列出目录内容"""
    workspace = _context.get("workspace") if _context else None
    if workspace:
        return workspace.ls(path)
    
    from pathlib import Path
    target = Path(path)
    if not target.exists():
        return []
    return sorted([f.name for f in target.iterdir()])


@tool(
    tool_id="file_read",
    name="读取文件",
    alias="读取文件",
    description="读取文件内容，支持指定行范围",
    category=ToolCategory.FILE_SYSTEM,
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件路径"},
            "start_line": {"type": "integer", "description": "起始行号（可选）"},
            "end_line": {"type": "integer", "description": "结束行号（可选）"}
        },
        "required": ["path"]
    }
)
async def file_read(
    path: str,
    start_line: int = None,
    end_line: int = None,
    _context: Dict = None
) -> str:
    """读取文件内容"""
    workspace = _context.get("workspace") if _context else None
    
    if workspace:
        if start_line or end_line:
            return workspace.read_file_lines(path, start_line, end_line)
        return workspace.read_file(path)
    
    from pathlib import Path
    content = Path(path).read_text(encoding='utf-8')
    
    if start_line or end_line:
        lines = content.split('\n')
        start = (start_line - 1) if start_line else 0
        end = end_line if end_line else len(lines)
        return '\n'.join(lines[start:end])
    
    return content


@tool(
    tool_id="file_write",
    name="写入文件",
    alias="写入文件",
    description="将内容写入文件（覆盖）",
    category=ToolCategory.FILE_SYSTEM,
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件路径"},
            "content": {"type": "string", "description": "文件内容"}
        },
        "required": ["path", "content"]
    }
)
async def file_write(
    path: str,
    content: str,
    _context: Dict = None
) -> str:
    """写入文件"""
    workspace = _context.get("workspace") if _context else None
    
    if workspace:
        return workspace.write_file(path, content)
    
    from pathlib import Path
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding='utf-8')
    return str(file_path)


@tool(
    tool_id="file_edit",
    name="编辑文件",
    alias="编辑文件",
    description="编辑文件中的指定内容（搜索替换）",
    category=ToolCategory.FILE_SYSTEM,
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件路径"},
            "old_content": {"type": "string", "description": "要替换的内容"},
            "new_content": {"type": "string", "description": "新内容"}
        },
        "required": ["path", "old_content", "new_content"]
    }
)
async def file_edit(
    path: str,
    old_content: str,
    new_content: str,
    _context: Dict = None
) -> str:
    """编辑文件"""
    workspace = _context.get("workspace") if _context else None
    
    if workspace:
        return workspace.edit_file(path, old_content, new_content)
    
    from pathlib import Path
    file_path = Path(path)
    content = file_path.read_text(encoding='utf-8')
    new_file_content = content.replace(old_content, new_content, 1)
    file_path.write_text(new_file_content, encoding='utf-8')
    return str(file_path)


@tool(
    tool_id="file_append",
    name="追加文件",
    alias="追加文件",
    description="向文件末尾追加内容",
    category=ToolCategory.FILE_SYSTEM,
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件路径"},
            "content": {"type": "string", "description": "要追加的内容"}
        },
        "required": ["path", "content"]
    }
)
async def file_append(
    path: str,
    content: str,
    _context: Dict = None
) -> str:
    """追加文件"""
    workspace = _context.get("workspace") if _context else None
    
    if workspace:
        return workspace.append_file(path, content)
    
    with open(path, 'a', encoding='utf-8') as f:
        f.write(content)
    return path
```

---

## 4. 核心工具：Bash 执行

```python
# etf_common/agent_framework/tools/bash_tools.py

from typing import Dict, Any
import asyncio
import subprocess

from .tool_registry import tool, ToolCategory


@tool(
    tool_id="bash_execute",
    name="执行命令",
    alias="执行命令",
    description="在工作空间中执行 Bash/Shell 命令",
    category=ToolCategory.BASH,
    input_schema={
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "要执行的命令"},
            "timeout": {"type": "integer", "description": "超时时间（秒）", "default": 30},
            "cwd": {"type": "string", "description": "工作目录（可选）"}
        },
        "required": ["command"]
    }
)
async def bash_execute(
    command: str,
    timeout: int = 30,
    cwd: str = None,
    _context: Dict = None
) -> Dict[str, Any]:
    """
    执行 Bash 命令
    
    官方推荐：Bash 作为通用工具，允许 Agent 灵活使用计算机
    """
    workspace = _context.get("workspace") if _context else None
    working_dir = cwd
    
    if workspace and not cwd:
        working_dir = str(workspace.root)
    
    try:
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=working_dir
        )
        
        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=timeout
        )
        
        return {
            "stdout": stdout.decode('utf-8'),
            "stderr": stderr.decode('utf-8'),
            "return_code": process.returncode,
            "success": process.returncode == 0
        }
        
    except asyncio.TimeoutError:
        return {
            "stdout": "",
            "stderr": f"命令超时（{timeout}秒）",
            "return_code": -1,
            "success": False
        }
    except Exception as e:
        return {
            "stdout": "",
            "stderr": str(e),
            "return_code": -1,
            "success": False
        }


@tool(
    tool_id="grep_search",
    name="文本搜索",
    alias="文本搜索",
    description="使用 grep 在文件中搜索文本",
    category=ToolCategory.BASH,
    input_schema={
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "搜索模式（正则表达式）"},
            "path": {"type": "string", "description": "搜索路径"},
            "recursive": {"type": "boolean", "description": "是否递归搜索", "default": True},
            "ignore_case": {"type": "boolean", "description": "是否忽略大小写", "default": False}
        },
        "required": ["pattern", "path"]
    }
)
async def grep_search(
    pattern: str,
    path: str,
    recursive: bool = True,
    ignore_case: bool = False,
    _context: Dict = None
) -> Dict[str, Any]:
    """使用 grep 搜索文本"""
    flags = []
    if recursive:
        flags.append("-r")
    if ignore_case:
        flags.append("-i")
    
    command = f"grep {' '.join(flags)} '{pattern}' {path}"
    return await bash_execute(command, _context=_context)
```

---

## 5. 业务工具示例：金融数据

```python
# etf_common/agent_framework/tools/builtin/financial_tools.py

from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta

from ..tool_registry import tool, ToolCategory


@tool(
    tool_id="stock_price",
    name="股票价格查询",
    alias="股票价格",
    description="查询股票的历史价格数据，包括开高低收、成交量等",
    category=ToolCategory.STOCK_DATA,
    input_schema={
        "type": "object",
        "properties": {
            "ticker": {
                "type": "string",
                "description": "股票代码，如 600519.SH"
            },
            "start_date": {
                "type": "string",
                "description": "开始日期，格式 YYYY-MM-DD"
            },
            "end_date": {
                "type": "string",
                "description": "结束日期，格式 YYYY-MM-DD"
            },
            "fields": {
                "type": "array",
                "items": {"type": "string"},
                "description": "返回字段，默认全部"
            }
        },
        "required": ["ticker"]
    },
    examples=[
        {
            "input": {"ticker": "600519.SH", "start_date": "2024-01-01"},
            "output": {"data": [...]}
        }
    ]
)
async def get_stock_price(
    ticker: str,
    start_date: str = None,
    end_date: str = None,
    fields: List[str] = None,
    _context: Dict = None
) -> Dict[str, Any]:
    """获取股票价格数据"""
    # 默认查询最近30天
    if not end_date:
        end_date = datetime.now().strftime("%Y-%m-%d")
    if not start_date:
        start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    
    # 调用实际数据源
    from etf_common.tushare import TushareClient
    client = TushareClient()
    
    data = await client.get_daily_prices(
        ts_code=ticker,
        start_date=start_date.replace("-", ""),
        end_date=end_date.replace("-", "")
    )
    
    return {
        "ticker": ticker,
        "start_date": start_date,
        "end_date": end_date,
        "data": data,
        "count": len(data) if data else 0
    }


@tool(
    tool_id="financial_data",
    name="财务数据查询",
    alias="财务数据",
    description="查询公司的财务报表数据，包括利润表、资产负债表、现金流量表",
    category=ToolCategory.FINANCIAL_DATA,
    input_schema={
        "type": "object",
        "properties": {
            "ticker": {
                "type": "string",
                "description": "股票代码"
            },
            "report_type": {
                "type": "string",
                "enum": ["income", "balance", "cashflow", "all"],
                "description": "报表类型",
                "default": "all"
            },
            "periods": {
                "type": "integer",
                "description": "返回最近几期数据",
                "default": 4
            }
        },
        "required": ["ticker"]
    }
)
async def get_financial_data(
    ticker: str,
    report_type: str = "all",
    periods: int = 4,
    _context: Dict = None
) -> Dict[str, Any]:
    """获取财务数据"""
    from etf_common.tushare import TushareClient
    client = TushareClient()
    
    result = {}
    
    if report_type in ["income", "all"]:
        result["income_statement"] = await client.get_income(
            ts_code=ticker,
            limit=periods
        )
    
    if report_type in ["balance", "all"]:
        result["balance_sheet"] = await client.get_balance_sheet(
            ts_code=ticker,
            limit=periods
        )
    
    if report_type in ["cashflow", "all"]:
        result["cashflow_statement"] = await client.get_cashflow(
            ts_code=ticker,
            limit=periods
        )
    
    return {
        "ticker": ticker,
        "report_type": report_type,
        "data": result
    }


@tool(
    tool_id="announcement_search",
    name="公告搜索",
    alias="公告搜索",
    description="搜索上市公司公告",
    category=ToolCategory.ANNOUNCEMENT_SEARCH,
    input_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "搜索关键词"
            },
            "ticker": {
                "type": "string",
                "description": "股票代码（可选，限定公司）"
            },
            "start_date": {
                "type": "string",
                "description": "开始日期"
            },
            "end_date": {
                "type": "string",
                "description": "结束日期"
            },
            "limit": {
                "type": "integer",
                "description": "返回数量限制",
                "default": 10
            }
        },
        "required": ["query"]
    }
)
async def search_announcements(
    query: str,
    ticker: str = None,
    start_date: str = None,
    end_date: str = None,
    limit: int = 10,
    _context: Dict = None
) -> Dict[str, Any]:
    """搜索公告"""
    from etf_common.caidazi_client import CaidaziClient
    client = CaidaziClient()
    
    results = await client.search_announcements(
        query=query,
        ticker=ticker,
        start_date=start_date,
        end_date=end_date,
        limit=limit
    )
    
    return {
        "query": query,
        "ticker": ticker,
        "results": results,
        "count": len(results) if results else 0
    }


@tool(
    tool_id="news_search",
    name="新闻搜索",
    alias="新闻搜索",
    description="搜索财经新闻",
    category=ToolCategory.NEWS_SEARCH,
    input_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "搜索关键词"
            },
            "days": {
                "type": "integer",
                "description": "搜索最近几天",
                "default": 7
            },
            "limit": {
                "type": "integer",
                "description": "返回数量限制",
                "default": 20
            }
        },
        "required": ["query"]
    }
)
async def search_news(
    query: str,
    days: int = 7,
    limit: int = 20,
    _context: Dict = None
) -> Dict[str, Any]:
    """搜索新闻"""
    from etf_common.caidazi_client import CaidaziClient
    client = CaidaziClient()
    
    results = await client.search_news(
        query=query,
        days=days,
        limit=limit
    )
    
    return {
        "query": query,
        "results": results,
        "count": len(results) if results else 0
    }


@tool(
    tool_id="research_report_search",
    name="研报搜索",
    alias="研报搜索",
    description="搜索券商研究报告",
    category=ToolCategory.RESEARCH_REPORT_SEARCH,
    input_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "搜索关键词"
            },
            "ticker": {
                "type": "string",
                "description": "股票代码（可选）"
            },
            "limit": {
                "type": "integer",
                "description": "返回数量限制",
                "default": 10
            }
        },
        "required": ["query"]
    }
)
async def search_research_reports(
    query: str,
    ticker: str = None,
    limit: int = 10,
    _context: Dict = None
) -> Dict[str, Any]:
    """搜索研报"""
    from etf_common.caidazi_client import CaidaziClient
    client = CaidaziClient()
    
    results = await client.search_research_reports(
        query=query,
        ticker=ticker,
        limit=limit
    )
    
    return {
        "query": query,
        "results": results,
        "count": len(results) if results else 0
    }
```

---

## 6. MCP 工具集成

```python
# etf_common/agent_framework/tools/mcp_tools.py

from typing import Dict, Any, List, Optional
import httpx

from .tool_registry import tool, ToolCategory
from .tool_definition import ToolDefinition


class MCPToolAdapter:
    """
    MCP (Model Context Protocol) 工具适配器
    
    支持将外部 MCP 服务的工具集成到框架中
    """
    
    def __init__(
        self,
        server_url: str,
        api_key: str = None
    ):
        self.server_url = server_url
        self.api_key = api_key
        self.client = httpx.AsyncClient()
    
    async def list_tools(self) -> List[ToolDefinition]:
        """获取 MCP 服务器的工具列表"""
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        
        response = await self.client.get(
            f"{self.server_url}/tools",
            headers=headers
        )
        response.raise_for_status()
        
        tools_data = response.json()
        
        return [
            ToolDefinition(
                tool_id=f"mcp_{t['name']}",
                name=t["name"],
                alias=t.get("alias", t["name"]),
                description=t.get("description", ""),
                category=ToolCategory.MCP,
                input_schema=t.get("inputSchema", {}),
                output_schema=t.get("outputSchema", {})
            )
            for t in tools_data.get("tools", [])
        ]
    
    async def execute(
        self,
        tool_name: str,
        params: Dict[str, Any]
    ) -> Any:
        """执行 MCP 工具"""
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        
        response = await self.client.post(
            f"{self.server_url}/execute",
            headers=headers,
            json={
                "tool": tool_name,
                "params": params
            }
        )
        response.raise_for_status()
        
        return response.json()
    
    def register_all(self, registry: "ToolRegistry"):
        """将所有 MCP 工具注册到注册表"""
        import asyncio
        
        async def _register():
            tools = await self.list_tools()
            for tool_def in tools:
                # 创建执行函数
                async def execute_func(
                    _tool_name=tool_def.name,
                    **kwargs
                ):
                    return await self.execute(_tool_name, kwargs)
                
                registry.register(tool_def, execute_func)
        
        asyncio.run(_register())
```

---

## 7. 工具使用示例

```python
# 示例：在 Agent 中使用工具

from etf_common.agent_framework.tools import ToolRegistry, ToolCategory

# 初始化注册表
registry = ToolRegistry()

# 注册内置工具
from etf_common.agent_framework.tools.file_tools import *
from etf_common.agent_framework.tools.bash_tools import *
from etf_common.agent_framework.tools.builtin.financial_tools import *

# 在 Agent 中使用
async def agent_with_tools():
    # 通过别名执行工具
    stock_data = await registry.execute_by_alias(
        alias="股票价格",
        params={
            "ticker": "600519.SH",
            "start_date": "2024-01-01"
        }
    )
    
    # 搜索公告
    announcements = await registry.execute_by_alias(
        alias="公告搜索",
        params={
            "query": "贵州茅台 业绩预告",
            "limit": 5
        }
    )
    
    # 生成工具描述（用于 Prompt）
    tool_descriptions = registry.to_prompt_descriptions([
        "stock_price",
        "announcement_search",
        "news_search"
    ])
    
    print(tool_descriptions)
```

---

## 8. 工具执行重试机制与熔断器

### 8.1 设计目标

工具执行可能因网络问题、服务不可用等原因失败。为了提高系统可靠性，我们引入：

- **重试机制**：自动重试可恢复的错误，采用指数退避策略
- **熔断器模式**：当工具持续失败时，暂时停止调用，防止雪崩效应

### 8.2 重试策略配置

```python
# src/tools/retry.py

from dataclasses import dataclass
from typing import Tuple, Type, Optional
from enum import Enum


class CircuitBreakerState(Enum):
    CLOSED = "closed"       # 正常状态
    OPEN = "open"           # 熔断状态
    HALF_OPEN = "half_open" # 半开状态（测试恢复）


@dataclass
class RetryPolicy:
    """重试策略配置"""
    
    max_retries: int = 3                    # 最大重试次数
    base_delay: float = 1.0                 # 基础延迟（秒）
    max_delay: float = 60.0                 # 最大延迟（秒）
    exponential_base: float = 2.0           # 指数基数
    jitter: bool = True                     # 是否添加抖动
    
    # 可重试的异常类型
    retryable_exceptions: Tuple[Type[Exception], ...] = (
        asyncio.TimeoutError,
        ConnectionError,
        httpx.HTTPStatusError,
    )
    
    # 熔断器配置
    failure_threshold: int = 5              # 触发熔断的失败次数
    recovery_timeout: float = 300.0         # 恢复超时（秒）
    half_open_test_requests: int = 1        # 半开状态测试请求数
```

### 8.3 熔断器实现

```python
class CircuitBreaker:
    """
    熔断器
    
    状态转换：
    CLOSED -> OPEN: 失败次数达到阈值
    OPEN -> HALF_OPEN: 恢复超时后
    HALF_OPEN -> CLOSED: 测试请求成功
    HALF_OPEN -> OPEN: 测试请求失败
    """
    
    def __init__(self, policy: RetryPolicy):
        self.policy = policy
        self.state = CircuitBreakerState.CLOSED
        self.failure_count = 0
        self.last_failure_time: Optional[float] = None
        self.half_open_successes = 0
    
    def can_execute(self) -> bool:
        """检查是否可以执行"""
        if self.state == CircuitBreakerState.CLOSED:
            return True
        
        if self.state == CircuitBreakerState.OPEN:
            # 检查是否超过恢复超时
            if self.last_failure_time:
                elapsed = time.time() - self.last_failure_time
                if elapsed >= self.policy.recovery_timeout:
                    self.state = CircuitBreakerState.HALF_OPEN
                    self.half_open_successes = 0
                    return True
            return False
        
        # HALF_OPEN 状态
        return True
    
    def record_success(self):
        """记录成功"""
        if self.state == CircuitBreakerState.HALF_OPEN:
            self.half_open_successes += 1
            if self.half_open_successes >= self.policy.half_open_test_requests:
                self.state = CircuitBreakerState.CLOSED
                self.failure_count = 0
        else:
            self.failure_count = 0
    
    def record_failure(self):
        """记录失败"""
        self.failure_count += 1
        self.last_failure_time = time.time()
        
        if self.state == CircuitBreakerState.HALF_OPEN:
            self.state = CircuitBreakerState.OPEN
        elif self.failure_count >= self.policy.failure_threshold:
            self.state = CircuitBreakerState.OPEN
```

### 8.4 重试执行器

```python
class RetryExecutor:
    """
    带重试和熔断的执行器
    """
    
    def __init__(self, policy: RetryPolicy = None):
        self.policy = policy or RetryPolicy()
        self._circuit_breakers: Dict[str, CircuitBreaker] = {}
    
    def _get_circuit_breaker(self, tool_id: str) -> CircuitBreaker:
        """获取或创建熔断器"""
        if tool_id not in self._circuit_breakers:
            self._circuit_breakers[tool_id] = CircuitBreaker(self.policy)
        return self._circuit_breakers[tool_id]
    
    async def execute(
        self,
        func: Callable,
        tool_id: str,
        **kwargs
    ) -> Any:
        """
        执行带重试的函数
        
        Args:
            func: 要执行的函数
            tool_id: 工具 ID（用于熔断器隔离）
            **kwargs: 传递给函数的参数
            
        Returns:
            函数执行结果
            
        Raises:
            CircuitBreakerOpenError: 熔断器打开
            MaxRetriesExceededError: 超过最大重试次数
        """
        circuit_breaker = self._get_circuit_breaker(tool_id)
        
        if not circuit_breaker.can_execute():
            raise CircuitBreakerOpenError(
                f"Circuit breaker is open for tool: {tool_id}"
            )
        
        last_exception = None
        
        for attempt in range(self.policy.max_retries + 1):
            try:
                result = await func(**kwargs)
                circuit_breaker.record_success()
                return result
                
            except self.policy.retryable_exceptions as e:
                last_exception = e
                circuit_breaker.record_failure()
                
                if attempt < self.policy.max_retries:
                    delay = self._calculate_delay(attempt)
                    logger.warning(
                        f"Tool {tool_id} failed (attempt {attempt + 1}), "
                        f"retrying in {delay:.2f}s: {e}"
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        f"Tool {tool_id} failed after {self.policy.max_retries + 1} attempts"
                    )
        
        raise MaxRetriesExceededError(
            f"Max retries exceeded for tool: {tool_id}",
            last_exception
        )
    
    def _calculate_delay(self, attempt: int) -> float:
        """计算重试延迟（指数退避 + 抖动）"""
        delay = min(
            self.policy.base_delay * (self.policy.exponential_base ** attempt),
            self.policy.max_delay
        )
        
        if self.policy.jitter:
            import random
            delay *= (0.5 + random.random())
        
        return delay
```

### 8.5 集成到 ToolRegistry

```python
class EnhancedToolRegistry(ToolRegistry):
    """增强的工具注册表，带重试和熔断"""
    
    def __init__(self, retry_policy: RetryPolicy = None):
        super().__init__()
        self._retry_executor = RetryExecutor(retry_policy or RetryPolicy())
    
    async def execute(
        self,
        tool_id: str,
        params: Dict[str, Any],
        context: Dict[str, Any] = None,
        skip_retry: bool = False
    ) -> Any:
        """
        执行工具（带重试和熔断）
        """
        if tool_id not in self._tools:
            raise ValueError(f"工具 {tool_id} 未注册")
        
        if tool_id not in self._implementations:
            raise ValueError(f"工具 {tool_id} 未实现")
        
        definition = self._tools[tool_id]
        implementation = self._implementations[tool_id]
        
        # 注入上下文
        if context:
            params = {**params, "_context": context}
        
        # 直接执行或使用重试执行器
        if skip_retry:
            if definition.is_async:
                return await implementation(**params)
            else:
                return implementation(**params)
        
        return await self._retry_executor.execute(
            func=lambda: implementation(**params) if not definition.is_async 
                        else implementation(**params),
            tool_id=tool_id,
        )
```

### 8.6 使用示例

```python
from tools import EnhancedToolRegistry, RetryPolicy

# 自定义重试策略
policy = RetryPolicy(
    max_retries=5,
    base_delay=2.0,
    failure_threshold=10,
    recovery_timeout=600.0
)

registry = EnhancedToolRegistry(retry_policy=policy)

# 执行工具（自动带重试和熔断）
try:
    result = await registry.execute(
        "stock_price",
        {"ticker": "600519.SH"}
    )
except CircuitBreakerOpenError:
    print("工具暂时不可用，请稍后再试")
except MaxRetriesExceededError:
    print("工具多次尝试失败")
```

### 8.7 熔断器状态监控

```python
# 获取熔断器状态
def get_circuit_breaker_status(registry: EnhancedToolRegistry) -> Dict[str, Any]:
    """获取所有工具的熔断器状态"""
    status = {}
    for tool_id, cb in registry._retry_executor._circuit_breakers.items():
        status[tool_id] = {
            "state": cb.state.value,
            "failure_count": cb.failure_count,
            "last_failure_time": cb.last_failure_time,
        }
    return status
```
