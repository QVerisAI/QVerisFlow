"""
工具参数验证测试

测试 ToolParameterValidator 的各项功能。
"""

import pytest
from src.tools.validation import (
    ToolParameterValidator,
    ToolValidationError,
    validate_tool_params,
)


class TestToolParameterValidator:
    """ToolParameterValidator 测试"""

    def test_validate_required_fields(self, tool_validator):
        """测试必需字段验证"""
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
            },
            "required": ["name"],
        }

        # 有效参数
        is_valid, errors = tool_validator.validate(
            {"name": "Alice", "age": 30}, schema, "test_tool"
        )
        assert is_valid
        assert len(errors) == 0

        # 缺少必需字段
        is_valid, errors = tool_validator.validate({"age": 30}, schema, "test_tool")
        assert not is_valid
        assert len(errors) > 0

    def test_validate_type_checking(self, tool_validator):
        """测试类型检查"""
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
                "score": {"type": "number"},
                "active": {"type": "boolean"},
            },
        }

        # 正确类型
        is_valid, errors = tool_validator.validate(
            {"name": "Alice", "age": 30, "score": 95.5, "active": True},
            schema,
            "test_tool",
        )
        assert is_valid

        # 错误类型
        is_valid, errors = tool_validator.validate(
            {"name": "Alice", "age": "thirty"},  # age 应该是整数
            schema,
            "test_tool",
        )
        assert not is_valid

    def test_validate_string_constraints(self, tool_validator):
        """测试字符串约束"""
        schema = {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "minLength": 3,
                    "maxLength": 10,
                },
            },
        }

        # 有效长度
        is_valid, _ = tool_validator.validate({"code": "ABC"}, schema, "test_tool")
        assert is_valid

        # 太短
        is_valid, errors = tool_validator.validate({"code": "AB"}, schema, "test_tool")
        assert not is_valid

        # 太长
        is_valid, errors = tool_validator.validate(
            {"code": "ABCDEFGHIJK"}, schema, "test_tool"
        )
        assert not is_valid

    def test_validate_enum(self, tool_validator):
        """测试枚举值验证"""
        schema = {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["pending", "active", "completed"],
                },
            },
        }

        # 有效枚举值
        is_valid, _ = tool_validator.validate({"status": "active"}, schema, "test_tool")
        assert is_valid

        # 无效枚举值
        is_valid, errors = tool_validator.validate(
            {"status": "invalid"}, schema, "test_tool"
        )
        assert not is_valid

    def test_validate_numeric_constraints(self, tool_validator):
        """测试数值约束"""
        schema = {
            "type": "object",
            "properties": {
                "score": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 100,
                },
            },
        }

        # 有效范围
        is_valid, _ = tool_validator.validate({"score": 50}, schema, "test_tool")
        assert is_valid

        # 低于最小值
        is_valid, errors = tool_validator.validate({"score": -1}, schema, "test_tool")
        assert not is_valid

        # 高于最大值
        is_valid, errors = tool_validator.validate({"score": 101}, schema, "test_tool")
        assert not is_valid

    def test_validate_nested_objects(self, tool_validator):
        """测试嵌套对象验证"""
        schema = {
            "type": "object",
            "properties": {
                "user": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "profile": {
                            "type": "object",
                            "properties": {
                                "bio": {"type": "string"},
                            },
                        },
                    },
                    "required": ["name"],
                },
            },
        }

        # 有效嵌套
        is_valid, _ = tool_validator.validate(
            {"user": {"name": "Alice", "profile": {"bio": "Hello"}}},
            schema,
            "test_tool",
        )
        assert is_valid

        # 缺少嵌套必需字段
        is_valid, errors = tool_validator.validate(
            {"user": {"profile": {"bio": "Hello"}}},
            schema,
            "test_tool",
        )
        assert not is_valid

    def test_validate_arrays(self, tool_validator):
        """测试数组验证"""
        schema = {
            "type": "object",
            "properties": {
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "maxItems": 5,
                },
            },
        }

        # 有效数组
        is_valid, _ = tool_validator.validate(
            {"tags": ["python", "ai"]}, schema, "test_tool"
        )
        assert is_valid

        # 空数组（低于 minItems）
        is_valid, errors = tool_validator.validate({"tags": []}, schema, "test_tool")
        assert not is_valid

    def test_type_coercion(self):
        """测试类型自动转换"""
        validator = ToolParameterValidator(coerce_types=True)

        schema = {
            "type": "object",
            "properties": {
                "count": {"type": "integer"},
                "price": {"type": "number"},
                "active": {"type": "boolean"},
            },
        }

        # 字符串数字自动转换
        params = validator._coerce_types(
            {"count": "42", "price": "19.99", "active": "true"}, schema
        )

        assert params["count"] == 42
        assert params["price"] == 19.99
        assert params["active"] is True

    def test_validate_and_raise(self, tool_validator):
        """测试验证失败抛出异常"""
        schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        }

        # 验证通过 - 使用有效数据
        result = tool_validator.validate_and_raise({"name": "test"}, schema, "test_tool")
        assert result["name"] == "test"
        
        # 验证失败 - 使用无效数据（缺少必填字段）应该抛出异常
        with pytest.raises(ToolValidationError) as exc_info:
            tool_validator.validate_and_raise({}, schema, "test_tool")

        assert "test_tool" in str(exc_info.value)


class TestConvenienceFunctions:
    """便捷函数测试"""

    def test_validate_tool_params_function(self):
        """测试 validate_tool_params 便捷函数"""
        schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        }

        is_valid, errors = validate_tool_params({"name": "test"}, schema, "test_tool")
        assert is_valid
