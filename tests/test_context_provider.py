"""
测试 RuntimeContextProvider 上下文提供器

验证：
- 时间上下文生成
- 领域知识加载（从配置文件）
- 数据时效性上下文
- 模型能力矩阵
- 完整 prompt 格式化
- Schema 约束提取
"""

import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock

from src.core.context_provider import (
    RuntimeContextProvider,
    extract_schema_constraints,
    format_tool_with_quality_metrics,
    get_runtime_context_provider,
    get_current_time_context,
)


class TestRuntimeContextProvider:
    """测试 RuntimeContextProvider 类"""

    def test_init_default(self):
        """测试默认初始化"""
        provider = RuntimeContextProvider()
        assert provider.timezone == "Asia/Shanghai"
        assert provider.domain == "general"
        assert provider.data_cache_ttl == 3600

    def test_init_custom(self):
        """测试自定义初始化"""
        provider = RuntimeContextProvider(
            timezone="America/New_York",
            domain="financial",
            data_cache_ttl=1800,
            execution_id="test-exec-123",
            workflow_id="test-wf-456",
        )
        assert provider.timezone == "America/New_York"
        assert provider.domain == "financial"
        assert provider.data_cache_ttl == 1800
        assert provider.execution_id == "test-exec-123"
        assert provider.workflow_id == "test-wf-456"

    def test_get_time_context(self):
        """测试获取时间上下文"""
        provider = RuntimeContextProvider()
        ctx = provider.get_time_context()

        # 验证必需字段存在
        assert "current_datetime" in ctx
        assert "current_date" in ctx
        assert "current_date_iso" in ctx
        assert "current_weekday" in ctx
        assert "current_quarter" in ctx
        assert "current_year" in ctx
        assert "current_month" in ctx
        assert "timezone" in ctx

        # 验证时间格式
        assert len(ctx["current_datetime"]) == 19  # YYYY-MM-DD HH:MM:SS
        assert ctx["current_year"].isdigit()
        assert ctx["current_month"].isdigit()
        assert ctx["current_weekday"].startswith("周")

    def test_get_time_context_quarter_calculation(self):
        """测试季度计算"""
        provider = RuntimeContextProvider()
        ctx = provider.get_time_context()

        # 验证季度格式
        assert "Q" in ctx["current_quarter"]
        year = ctx["current_year"]
        assert ctx["current_quarter"].startswith(year)

    def test_get_data_freshness_context(self):
        """测试数据时效性上下文"""
        provider = RuntimeContextProvider(data_cache_ttl=7200)
        ctx = provider.get_data_freshness_context()

        assert ctx["cache_ttl_seconds"] == 7200
        assert ctx["cache_ttl_minutes"] == 120
        assert ctx["cache_ttl_hours"] == 2
        assert "2 小时" in ctx["freshness_warning"]

    def test_get_data_freshness_context_minutes(self):
        """测试分钟级数据时效性"""
        provider = RuntimeContextProvider(data_cache_ttl=1800)
        ctx = provider.get_data_freshness_context()

        assert ctx["cache_ttl_minutes"] == 30
        assert "30 分钟" in ctx["freshness_warning"]

    def test_format_time_prompt(self):
        """测试时间 prompt 格式化"""
        provider = RuntimeContextProvider()
        prompt = provider.format_time_prompt()

        assert "当前执行环境" in prompt
        assert "当前时间" in prompt
        assert "当前日期" in prompt
        assert "当前季度" in prompt
        assert "数据时效性" in prompt
        assert "重要" in prompt

    def test_format_domain_prompt_with_config(self):
        """测试从配置加载领域知识的 prompt 格式化"""
        # Mock 配置
        mock_config = {
            "domains": {
                "financial": {
                    "name": "金融分析",
                    "description": "股票、基金分析",
                    "data_sources": ["交易所数据", "财经平台"],
                    "timeliness": {"price_delay": "15分钟"},
                    "terminology": ["PE", "PB", "ROE"],
                    "compliance": ["不提供投资建议"],
                }
            }
        }

        with patch.object(RuntimeContextProvider, "config", mock_config):
            provider = RuntimeContextProvider(domain="financial")
            prompt = provider.format_domain_prompt()

            assert "金融分析" in prompt
            assert "股票、基金分析" in prompt
            assert "交易所数据" in prompt
            assert "PE" in prompt
            assert "不提供投资建议" in prompt

    def test_format_domain_prompt_empty(self):
        """测试空领域配置"""
        mock_config = {"domains": {}}

        with patch.object(RuntimeContextProvider, "config", mock_config):
            provider = RuntimeContextProvider(domain="unknown")
            prompt = provider.format_domain_prompt()
            assert prompt == ""

    def test_format_for_prompt_full(self):
        """测试完整 prompt 格式化"""
        provider = RuntimeContextProvider()
        prompt = provider.format_for_prompt(
            include_time=True,
            include_domain=False,
            include_model_capabilities=False,
        )

        assert "当前执行环境" in prompt
        assert "当前时间" in prompt

    def test_format_for_prompt_time_only(self):
        """测试仅时间上下文"""
        provider = RuntimeContextProvider()
        prompt = provider.format_for_prompt(
            include_time=True,
            include_domain=False,
            include_model_capabilities=False,
        )

        assert "当前执行环境" in prompt

    def test_format_execution_context(self):
        """测试执行进度上下文"""
        provider = RuntimeContextProvider(
            workflow_id="wf-123",
            execution_id="exec-456",
        )
        prompt = provider.format_execution_context(
            node_index=2,
            total_nodes=5,
            completed_nodes=2,
        )

        assert "执行进度" in prompt
        assert "wf-123" in prompt
        assert "exec-456" in prompt
        assert "3 / 5" in prompt  # node_index + 1
        assert "40" in prompt  # 40% progress

    def test_get_runtime_context_dict(self):
        """测试获取运行时上下文字典"""
        provider = RuntimeContextProvider(
            domain="financial",
            timezone="Asia/Shanghai",
            workflow_id="wf-test",
            execution_id="exec-test",
        )
        ctx = provider.get_runtime_context_dict()

        assert "_runtime" in ctx
        runtime = ctx["_runtime"]
        assert "current_time" in runtime
        assert "current_date" in runtime
        assert "current_quarter" in runtime
        assert runtime["domain"] == "financial"
        assert runtime["timezone"] == "Asia/Shanghai"
        assert runtime["workflow_id"] == "wf-test"
        assert runtime["execution_id"] == "exec-test"


class TestExtractSchemaConstraints:
    """测试 Schema 约束提取函数"""

    def test_empty_schema(self):
        """测试空 schema"""
        result = extract_schema_constraints({})
        assert result == "无特殊约束"

    def test_none_schema(self):
        """测试 None schema"""
        result = extract_schema_constraints(None)
        assert result == "无特殊约束"

    def test_enum_constraint(self):
        """测试枚举约束"""
        schema = {
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["active", "inactive", "pending"],
                }
            },
            "required": ["status"],
        }
        result = extract_schema_constraints(schema)
        assert "status" in result
        assert "只能是" in result
        assert "必填" in result

    def test_numeric_range_constraint(self):
        """测试数值范围约束"""
        schema = {
            "properties": {
                "age": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 150,
                }
            }
        }
        result = extract_schema_constraints(schema)
        assert "age" in result
        assert "最小值 0" in result
        assert "最大值 150" in result

    def test_string_length_constraint(self):
        """测试字符串长度约束"""
        schema = {
            "properties": {
                "username": {
                    "type": "string",
                    "minLength": 3,
                    "maxLength": 20,
                }
            }
        }
        result = extract_schema_constraints(schema)
        assert "username" in result
        assert "最小长度 3" in result
        assert "最大长度 20" in result

    def test_pattern_constraint(self):
        """测试正则模式约束"""
        schema = {
            "properties": {
                "email": {
                    "type": "string",
                    "pattern": r"^[\w.-]+@[\w.-]+\.\w+$",
                }
            }
        }
        result = extract_schema_constraints(schema)
        assert "email" in result
        assert "格式正则" in result

    def test_format_constraint(self):
        """测试格式约束"""
        schema = {
            "properties": {
                "birth_date": {
                    "type": "string",
                    "format": "date",
                }
            }
        }
        result = extract_schema_constraints(schema)
        assert "birth_date" in result
        assert "日期格式" in result

    def test_default_value(self):
        """测试默认值"""
        schema = {
            "properties": {
                "limit": {
                    "type": "integer",
                    "default": 10,
                }
            }
        }
        result = extract_schema_constraints(schema)
        assert "limit" in result
        assert "默认值: 10" in result

    def test_combined_constraints(self):
        """测试组合约束"""
        schema = {
            "properties": {
                "count": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 10,
                }
            },
            "required": ["count"],
        }
        result = extract_schema_constraints(schema)
        assert "count" in result
        assert "必填" in result
        assert "最小值 1" in result
        assert "最大值 100" in result
        assert "默认值: 10" in result


class TestFormatToolWithQualityMetrics:
    """测试工具质量指标格式化"""

    def test_basic_format(self):
        """测试基本格式化"""
        result = format_tool_with_quality_metrics(
            tool_name="天气查询",
            tool_id="weather_api",
            description="获取城市天气信息",
        )
        assert "天气查询" in result
        assert "weather_api" in result
        assert "获取城市天气信息" in result

    def test_with_success_rate(self):
        """测试带成功率"""
        result = format_tool_with_quality_metrics(
            tool_name="Test Tool",
            tool_id="test",
            description="Test",
            success_rate=0.95,
        )
        assert "95.0%" in result
        assert "历史成功率" in result

    def test_with_execution_time(self):
        """测试带执行时间"""
        result = format_tool_with_quality_metrics(
            tool_name="Test Tool",
            tool_id="test",
            description="Test",
            avg_execution_time=2.5,
        )
        assert "2.5秒" in result
        assert "平均响应时间" in result

    def test_with_cache_ttl(self):
        """测试带缓存 TTL"""
        result = format_tool_with_quality_metrics(
            tool_name="Test Tool",
            tool_id="test",
            description="Test",
            cache_ttl=3600,
        )
        assert "60 分钟" in result
        assert "数据时效性" in result

    def test_with_input_schema(self):
        """测试带输入 schema"""
        result = format_tool_with_quality_metrics(
            tool_name="Test Tool",
            tool_id="test",
            description="Test",
            input_schema={
                "properties": {
                    "city": {
                        "type": "string",
                        "enum": ["北京", "上海", "广州"],
                    }
                },
                "required": ["city"],
            },
        )
        assert "参数约束" in result
        assert "city" in result


class TestConvenienceFunctions:
    """测试便捷函数"""

    def test_get_runtime_context_provider(self):
        """测试获取上下文提供器"""
        provider = get_runtime_context_provider(
            timezone="UTC",
            domain="healthcare",
        )
        assert isinstance(provider, RuntimeContextProvider)
        assert provider.timezone == "UTC"
        assert provider.domain == "healthcare"

    def test_get_current_time_context(self):
        """测试获取当前时间上下文"""
        result = get_current_time_context()
        assert "当前执行环境" in result
        assert "当前时间" in result


class TestEdgeCases:
    """测试边缘情况"""

    def test_domain_context_with_list_data_sources(self):
        """测试列表类型的数据来源"""
        mock_config = {
            "domains": {
                "test": {
                    "name": "测试",
                    "data_sources": ["来源1", "来源2", "来源3"],
                }
            }
        }

        with patch.object(RuntimeContextProvider, "config", mock_config):
            provider = RuntimeContextProvider(domain="test")
            prompt = provider.format_domain_prompt()
            assert "来源1" in prompt
            assert "来源2" in prompt

    def test_domain_context_with_dict_timeliness(self):
        """测试字典类型的时效性"""
        mock_config = {
            "domains": {
                "test": {
                    "name": "测试",
                    "timeliness": {
                        "real_time": "实时",
                        "delayed": "延迟",
                    },
                }
            }
        }

        with patch.object(RuntimeContextProvider, "config", mock_config):
            provider = RuntimeContextProvider(domain="test")
            prompt = provider.format_domain_prompt()
            assert "数据时效性" in prompt
            assert "real_time" in prompt

    def test_execution_context_zero_nodes(self):
        """测试零节点情况"""
        provider = RuntimeContextProvider()
        prompt = provider.format_execution_context(
            node_index=0,
            total_nodes=0,
            completed_nodes=0,
        )
        # 不应该崩溃
        assert "执行进度" in prompt or prompt == ""

    def test_schema_with_large_enum(self):
        """测试大枚举值"""
        schema = {
            "properties": {
                "country": {
                    "type": "string",
                    "enum": ["CN", "US", "UK", "JP", "DE", "FR", "IT", "CA"],
                }
            }
        }
        result = extract_schema_constraints(schema)
        # 应该截断显示
        assert "等" in result or "country" in result
