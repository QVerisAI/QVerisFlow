"""
JSON 工具测试

测试 json_utils 模块的各项功能，特别是嵌套 JSON 提取逻辑。
"""

import pytest
from src.utils.json_utils import (
    optimize_json_response,
    extract_structured_output,
    _try_extract_nested_structured_json,
    _try_parse_double_encoded,
)


class TestOptimizeJsonResponse:
    """optimize_json_response 测试"""

    def test_valid_json_unchanged(self):
        """测试有效 JSON 不变"""
        content = '{"summary": "test", "data": {"key": "value"}}'
        result = optimize_json_response(content)
        assert result == content

    def test_remove_markdown_code_block(self):
        """测试移除 markdown 代码块标记"""
        content = '```json\n{"summary": "test"}\n```'
        result = optimize_json_response(content)
        assert result is not None
        assert "```" not in result
        assert '"summary"' in result

    def test_remove_prefix_text(self):
        """测试移除前缀文字"""
        content = '以下是JSON结果：{"summary": "test"}'
        result = optimize_json_response(content)
        assert result is not None
        assert result.startswith("{")

    def test_remove_suffix_text(self):
        """测试移除后缀文字"""
        content = '{"summary": "test"}\n希望以上信息有帮助'
        result = optimize_json_response(content)
        assert result is not None
        assert result.endswith("}")

    def test_empty_content_returns_none(self):
        """测试空内容返回 None"""
        assert optimize_json_response("") is None
        assert optimize_json_response(None) is None


class TestTryExtractNestedStructuredJson:
    """_try_extract_nested_structured_json 测试"""

    def test_extract_from_prefix_text(self):
        """测试从带前缀文字的内容中提取 JSON"""
        content = '以下是分析结果：{"summary": "测试摘要", "data": {"key": "value"}}'
        result = _try_extract_nested_structured_json(content)
        assert result is not None
        assert result["summary"] == "测试摘要"
        assert result["data"]["key"] == "value"

    def test_extract_from_markdown_block(self):
        """测试从 markdown 代码块中提取 JSON"""
        content = '```json\n{"summary": "测试", "data": null}\n```'
        result = _try_extract_nested_structured_json(content)
        assert result is not None
        assert result["summary"] == "测试"

    def test_extract_from_suffix_text(self):
        """测试从带后缀文字的内容中提取 JSON"""
        content = '{"summary": "结果", "narrative": "详细描述"}\n\n希望以上信息有帮助！'
        result = _try_extract_nested_structured_json(content)
        assert result is not None
        assert result["summary"] == "结果"
        assert result["narrative"] == "详细描述"

    def test_extract_nested_json_with_complex_data(self):
        """测试提取包含复杂嵌套数据的 JSON"""
        content = """这是返回结果:
{"summary": "数据采集完成", "data": {"items": [1, 2, 3], "nested": {"a": "b"}}, "highlights": ["重点1"]}
以上是分析结果。"""
        result = _try_extract_nested_structured_json(content)
        assert result is not None
        assert result["summary"] == "数据采集完成"
        assert result["data"]["items"] == [1, 2, 3]
        assert result["data"]["nested"]["a"] == "b"
        assert result["highlights"] == ["重点1"]

    def test_no_standard_fields_returns_none(self):
        """测试没有标准字段时返回 None"""
        content = '{"foo": "bar", "baz": 123}'
        result = _try_extract_nested_structured_json(content)
        assert result is None

    def test_empty_content_returns_none(self):
        """测试空内容返回 None"""
        assert _try_extract_nested_structured_json("") is None
        assert _try_extract_nested_structured_json(None) is None

    def test_no_json_content_returns_none(self):
        """测试没有 JSON 内容时返回 None"""
        content = "这是一段普通文本，没有 JSON 内容"
        result = _try_extract_nested_structured_json(content)
        assert result is None

    def test_extract_with_escaped_quotes(self):
        """测试处理包含转义引号的 JSON"""
        content = r'前缀{"summary": "包含\"引号\"的内容", "data": null}后缀'
        result = _try_extract_nested_structured_json(content)
        assert result is not None
        assert "引号" in result["summary"]


class TestTryParseDoubleEncoded:
    """_try_parse_double_encoded 测试"""

    def test_parse_double_encoded_result(self):
        """测试解析双重编码的 result 字段"""
        parsed = {"result": '{"summary": "内层摘要", "data": {"key": "value"}}'}
        result = _try_parse_double_encoded(parsed)
        assert result is not None
        assert result["summary"] == "内层摘要"

    def test_no_result_field_returns_none(self):
        """测试没有 result 字段时返回 None"""
        parsed = {"summary": "直接摘要", "data": {}}
        result = _try_parse_double_encoded(parsed)
        assert result is None

    def test_result_not_json_string_returns_none(self):
        """测试 result 不是 JSON 字符串时返回 None"""
        parsed = {"result": "普通文本"}
        result = _try_parse_double_encoded(parsed)
        assert result is None

    def test_non_dict_input_returns_none(self):
        """测试非字典输入返回 None"""
        assert _try_parse_double_encoded([1, 2, 3]) is None
        assert _try_parse_double_encoded("string") is None
        assert _try_parse_double_encoded(None) is None


class TestExtractStructuredOutput:
    """extract_structured_output 测试"""

    def test_direct_json_parsing(self):
        """测试直接 JSON 解析"""
        content = (
            '{"summary": "直接解析", "data": {"key": "value"}, "narrative": "描述"}'
        )
        result = extract_structured_output(content)
        assert result["summary"] == "直接解析"
        assert result["data"]["key"] == "value"
        assert result["narrative"] == "描述"

    def test_json_with_markdown_wrapper(self):
        """测试带 markdown 包装的 JSON"""
        content = '```json\n{"summary": "markdown包装", "data": null}\n```'
        result = extract_structured_output(content)
        assert result["summary"] == "markdown包装"

    def test_json_with_prefix_text(self):
        """测试带前缀文字的 JSON"""
        content = (
            '以下是分析结果：\n{"summary": "前缀文字测试", "data": {"result": "ok"}}'
        )
        result = extract_structured_output(content)
        assert result["summary"] == "前缀文字测试"
        assert result["data"]["result"] == "ok"

    def test_json_with_suffix_text(self):
        """测试带后缀文字的 JSON"""
        content = '{"summary": "后缀测试", "data": {}}\n\n希望以上内容对您有帮助！'
        result = extract_structured_output(content)
        assert result["summary"] == "后缀测试"

    def test_nested_json_in_text(self):
        """测试嵌套在文本中的 JSON"""
        content = """好的，我已经完成了分析。以下是结果：

{"summary": "威瑞森通信 (VZ) 股票数据采集完成", "data": {"ticker": "VZ", "price": 47.5}, "narrative": "已完成数据采集", "highlights": ["数据完整", "价格稳定"]}

如果您需要更多信息，请告诉我。"""
        result = extract_structured_output(content)
        assert "威瑞森通信" in result["summary"]
        assert result["data"]["ticker"] == "VZ"
        assert result["narrative"] == "已完成数据采集"

    def test_double_encoded_json(self):
        """测试双重编码的 JSON"""
        inner_json = '{"summary": "内层数据", "data": {"nested": true}}'
        content = '{"result": "' + inner_json.replace('"', '\\"') + '"}'
        result = extract_structured_output(content)
        assert result["summary"] == "内层数据"
        assert result["data"]["nested"] is True

    def test_fallback_for_unparseable_content(self):
        """测试无法解析时的兜底处理"""
        content = "这是一段无法解析为 JSON 的普通文本内容"
        result = extract_structured_output(content)
        assert result["summary"] == "这是一段无法解析为 JSON 的普通文本内容"[:200]
        assert result["data"]["raw_content"] == content

    def test_empty_content(self):
        """测试空内容"""
        result = extract_structured_output("")
        assert result["summary"] == "无输出"
        assert result["data"] is None

    def test_old_format_compatibility(self):
        """测试旧格式兼容性（没有 summary/data 字段）"""
        content = '{"result": "操作完成", "status": "success"}'
        result = extract_structured_output(content)
        assert result["summary"] == "操作完成"
        assert result["data"]["result"] == "操作完成"

    def test_summary_cleanup_markdown(self):
        """测试 summary 清洗（移除 markdown 标记）"""
        content = '{"summary": "```正常摘要", "data": null, "narrative": "描述内容"}'
        result = extract_structured_output(content)
        # summary 以 ``` 开头时应该被清洗
        assert not result["summary"].startswith("```")

    def test_complex_nested_structure(self):
        """测试复杂嵌套结构"""
        content = """```json
{
  "summary": "已完成威瑞森通信 (VZ) 股票的候选数据采集，整合了6个月历史日线价格、关键价位支撑阻力、技术指标及机构目标价信息。",
  "narrative": "我们为威瑞森通信 (VZ) 收集了2025年12月至2026年2月共约3个月的完整日线行情数据。",
  "data": {
    "ticker": "VZ",
    "historical_data": [
      {"date": "2026-02-05", "close": 47.32},
      {"date": "2026-02-04", "close": 47.15}
    ],
    "target_prices": {
      "median": 48.5,
      "high": 52.0,
      "low": 44.0
    }
  },
  "highlights": [
    "EV/EBITDA约7.4x",
    "自由现金流收益率达11.7%"
  ]
}
```"""
        result = extract_structured_output(content)
        assert "威瑞森通信" in result["summary"]
        assert result["data"]["ticker"] == "VZ"
        assert len(result["data"]["historical_data"]) == 2
        assert result["highlights"][0] == "EV/EBITDA约7.4x"


class TestEdgeCases:
    """边缘情况测试"""

    def test_json_with_unicode(self):
        """测试包含 Unicode 字符的 JSON"""
        content = '{"summary": "包含中文和emoji😀", "data": {"中文键": "中文值"}}'
        result = extract_structured_output(content)
        assert "中文" in result["summary"]
        assert result["data"]["中文键"] == "中文值"

    def test_json_with_newlines_in_values(self):
        """测试值中包含换行符的 JSON"""
        content = '{"summary": "第一行\\n第二行", "data": null}'
        result = extract_structured_output(content)
        assert result["summary"] == "第一行\n第二行"

    def test_deeply_nested_json(self):
        """测试深层嵌套的 JSON"""
        content = '{"summary": "深层嵌套", "data": {"level1": {"level2": {"level3": "value"}}}}'
        result = extract_structured_output(content)
        assert result["data"]["level1"]["level2"]["level3"] == "value"

    def test_json_with_array_data(self):
        """测试 data 为数组的情况"""
        content = '{"summary": "数组数据", "data": [1, 2, 3, "test"]}'
        result = extract_structured_output(content)
        assert result["data"] == [1, 2, 3, "test"]

    def test_only_summary_field(self):
        """测试只有 summary 字段"""
        content = '{"summary": "只有摘要"}'
        result = extract_structured_output(content)
        assert result["summary"] == "只有摘要"
        assert result["data"] is None

    def test_only_data_field(self):
        """测试只有 data 字段"""
        content = '{"data": {"key": "value"}}'
        result = extract_structured_output(content)
        assert result["summary"] == ""  # 空 summary
        assert result["data"]["key"] == "value"

    def test_non_dict_parsed_result(self):
        """测试解析结果不是字典的情况"""
        content = "[1, 2, 3]"
        result = extract_structured_output(content)
        assert result["data"] == [1, 2, 3]
        assert "[1, 2, 3]" in result["summary"]
