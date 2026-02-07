"""
JSON 响应优化工具

提供统一的 JSON 响应清洗和优化功能，被 llm_client 和 agent_graph 共同使用。
"""

import json
import logging
import re
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def optimize_json_response(content: str) -> Optional[str]:
    """
    优化 JSON 响应，尝试修复常见的 JSON 格式问题

    实现了多种优化策略:
    1. 移除前缀和后缀（```json、解释文字等）
    2. 提取 JSON 对象边界
    3. 处理双重编码 {"result": "JSON字符串"}
    4. 修复引号问题
    5. 截断到最后一个完整对象
    6. 修复截断的字符串值
    7. 修复截断的数组内容

    Args:
        content: 原始响应内容

    Returns:
        优化后的 JSON 字符串，如果无法优化则返回 None
    """
    if not content:
        return None

    # 策略 1: 移除可能的前缀和后缀
    optimized = content.strip()

    # 移除常见的 markdown 代码块标记
    if optimized.startswith("```json"):
        optimized = optimized[7:]
    elif optimized.startswith("```"):
        optimized = optimized[3:]

    if optimized.endswith("```"):
        optimized = optimized[:-3]

    optimized = optimized.strip()

    # 移除可能的解释文字（在 JSON 之前）
    first_brace = optimized.find("{")
    if first_brace > 0:
        prefix = optimized[:first_brace].strip()
        if prefix and len(prefix) < 200:
            if any(
                keyword in prefix.lower()
                for keyword in [
                    "json",
                    "结果",
                    "输出",
                    "分析",
                    "here",
                    "following",
                    "below",
                ]
            ):
                optimized = optimized[first_brace:]

    # 移除可能的解释文字（在 JSON 之后）
    last_brace = optimized.rfind("}")
    if last_brace > 0 and last_brace < len(optimized) - 1:
        suffix = optimized[last_brace + 1 :].strip()
        if suffix and len(suffix) < 200:
            if any(
                keyword in suffix.lower()
                for keyword in [
                    "希望",
                    "以上",
                    "注意",
                    "说明",
                    "hope",
                    "above",
                    "note",
                ]
            ):
                optimized = optimized[: last_brace + 1]

    optimized = optimized.strip()

    # 尝试解析
    try:
        json.loads(optimized)
        logger.debug("✅ JSON 优化成功：移除前缀/后缀")
        return optimized
    except json.JSONDecodeError:
        pass

    # 策略 2: 尝试找到 JSON 对象边界
    json_start = optimized.find("{")
    json_end = optimized.rfind("}")

    if json_start != -1 and json_end != -1 and json_end > json_start:
        json_content = optimized[json_start : json_end + 1]
        try:
            json.loads(json_content)
            logger.debug("✅ JSON 优化成功：提取 JSON 对象")
            return json_content
        except json.JSONDecodeError:
            pass

    # 策略 3: 尝试修复常见的 JSON 格式问题
    try:
        fixed_content = optimized
        # 修复键名
        fixed_content = re.sub(
            r"([{,]\s*)([a-zA-Z_][a-zA-Z0-9_]*)\s*:", r'\1"\2":', fixed_content
        )
        # 修复值
        fixed_content = re.sub(
            r":\s*([a-zA-Z_][a-zA-Z0-9_]*)(?=\s*[,}])", r': "\1"', fixed_content
        )

        json.loads(fixed_content)
        logger.debug("✅ JSON 优化成功：修复引号问题")
        return fixed_content
    except json.JSONDecodeError:
        pass

    # 策略 4: 尝试截断到最后一个完整的 JSON 对象
    try:
        brace_count = 0
        last_complete_pos = -1

        for i in range(len(optimized) - 1, -1, -1):
            if optimized[i] == "}":
                brace_count += 1
            elif optimized[i] == "{":
                brace_count -= 1
                if brace_count == 0:
                    last_complete_pos = i
                    break

        if last_complete_pos != -1:
            truncated = optimized[last_complete_pos:]
            json.loads(truncated)
            logger.debug("✅ JSON 优化成功：截断到完整对象")
            return truncated
    except json.JSONDecodeError:
        pass

    # 策略 5: 尝试修复截断的字符串值
    try:
        fixed_content = optimized

        # 检查是否在字符串中（未闭合的引号）
        in_string = False
        escape_next = False
        last_quote_pos = -1

        for i, char in enumerate(fixed_content):
            if escape_next:
                escape_next = False
                continue
            if char == "\\":
                escape_next = True
                continue
            if char == '"':
                if not in_string:
                    in_string = True
                    last_quote_pos = i
                else:
                    in_string = False
                    last_quote_pos = -1

        # 如果字符串未闭合，尝试闭合它
        if in_string and last_quote_pos != -1:
            string_start = last_quote_pos
            for i in range(string_start + 1, len(fixed_content)):
                if fixed_content[i] in [",", ":", "}", "]", "\n"]:
                    fixed_content = fixed_content[:i] + '"' + fixed_content[i:]
                    break
            else:
                fixed_content = fixed_content + '"'

        # 尝试关闭未完成的数组或对象
        open_braces = fixed_content.count("{") - fixed_content.count("}")
        open_brackets = fixed_content.count("[") - fixed_content.count("]")

        if open_braces > 0:
            last_comma = fixed_content.rfind(",")
            last_colon = fixed_content.rfind(":")

            if last_colon > last_comma:
                after_colon = fixed_content[last_colon + 1 :].strip()
                if after_colon and not after_colon.endswith(
                    ('"', "}", "]", "true", "false", "null")
                ):
                    if last_comma != -1:
                        fixed_content = fixed_content[:last_comma] + "}"
                    else:
                        fixed_content = fixed_content[:last_colon] + ": null}"
                else:
                    fixed_content = fixed_content + "}" * open_braces
            else:
                fixed_content = fixed_content + "}" * open_braces

        if open_brackets > 0:
            fixed_content = fixed_content + "]" * open_brackets

        json.loads(fixed_content)
        logger.debug("✅ JSON 优化成功：修复截断的字符串/对象")
        return fixed_content
    except (json.JSONDecodeError, IndexError, ValueError):
        pass

    # 策略 6: 尝试提取并修复数组内容
    try:
        array_patterns = [
            r'"items"\s*:\s*\[',
            r'"results"\s*:\s*\[',
            r'"data"\s*:\s*\[',
            r'"list"\s*:\s*\[',
        ]

        for pattern in array_patterns:
            array_match = re.search(pattern, optimized)
            if array_match:
                array_start = array_match.end() - 1
                bracket_count = 0
                array_end = -1

                for i in range(array_start, len(optimized)):
                    if optimized[i] == "[":
                        bracket_count += 1
                    elif optimized[i] == "]":
                        bracket_count -= 1
                        if bracket_count == 0:
                            array_end = i
                            break

                if array_end == -1:
                    brace_count = 0
                    last_obj_end = -1
                    for i in range(len(optimized) - 1, array_start, -1):
                        if optimized[i] == "}":
                            brace_count += 1
                        elif optimized[i] == "{":
                            brace_count -= 1
                            if brace_count == 0:
                                last_obj_end = i
                                break

                    if last_obj_end != -1:
                        before_array = optimized[:array_start]
                        array_content = optimized[array_start : last_obj_end + 1]
                        fixed_content = before_array + array_content + "]}"
                        try:
                            json.loads(fixed_content)
                            logger.debug("✅ JSON 优化成功：修复截断的数组")
                            return fixed_content
                        except json.JSONDecodeError:
                            continue
    except (json.JSONDecodeError, IndexError, ValueError):
        pass

    # 记录失败信息以便调试
    content_preview = content[:500] if len(content) > 500 else content
    logger.warning("⚠️ JSON 优化失败：无法修复 JSON 格式")
    logger.debug(f"响应内容预览（前500字符）: {content_preview}")
    if len(content) > 500:
        logger.debug(f"响应内容预览（后500字符）: {content[-500:]}")
    return None


def _try_parse_double_encoded(parsed: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    尝试解析双重编码的 JSON
    如 {"result": "{\"summary\": ...}"} -> {summary, narrative, data, highlights}

    Args:
        parsed: 已解析的 JSON 对象

    Returns:
        如果是双重编码则返回内层对象，否则返回 None
    """
    if not isinstance(parsed, dict):
        return None

    # 检查是否有 result 字段且值是 JSON 字符串
    if "result" in parsed and isinstance(parsed.get("result"), str):
        try:
            inner = json.loads(parsed["result"])
            if isinstance(inner, dict) and ("summary" in inner or "data" in inner):
                logger.debug("✅ 成功解析双重编码的 JSON")
                return inner
        except json.JSONDecodeError:
            pass

    return None


def _try_extract_nested_structured_json(content: str) -> Optional[Dict[str, Any]]:
    """
    尝试从内容中智能提取嵌套的结构化 JSON

    当直接解析失败时，查找内容中是否存在 summary/data 等标准字段，
    并提取其所在的完整 JSON 对象。

    处理场景：
    1. 内容前有解释文字：'以下是分析结果：{"summary": ...}'
    2. 内容被markdown包裹：'```json\n{"summary": ...}\n```'
    3. 内容中有多个JSON片段，需要找到包含标准字段的那个

    Args:
        content: 原始内容

    Returns:
        如果成功提取则返回解析后的字典，否则返回 None
    """
    if not content:
        return None

    # 查找标准字段的位置
    standard_fields = ['"summary"', '"data"', '"narrative"', '"highlights"']
    field_positions = []
    for field in standard_fields:
        pos = content.find(field)
        if pos != -1:
            field_positions.append(pos)

    if not field_positions:
        return None

    # 找到最早出现的标准字段位置
    earliest_field_pos = min(field_positions)

    # 从该位置向前查找最近的 '{' 作为 JSON 起点
    json_start = content.rfind("{", 0, earliest_field_pos)
    if json_start == -1:
        return None

    # 从 json_start 开始，使用括号匹配找到完整的 JSON 对象
    brace_count = 0
    json_end = -1
    in_string = False
    escape_next = False

    for i in range(json_start, len(content)):
        char = content[i]
        if escape_next:
            escape_next = False
            continue
        if char == "\\" and in_string:
            escape_next = True
            continue
        if char == '"' and not escape_next:
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "{":
            brace_count += 1
        elif char == "}":
            brace_count -= 1
            if brace_count == 0:
                json_end = i
                break

    if json_end == -1:
        return None

    # 提取并解析 JSON
    json_str = content[json_start : json_end + 1]
    try:
        parsed = json.loads(json_str)
        if isinstance(parsed, dict) and ("summary" in parsed or "data" in parsed):
            logger.debug("✅ 成功从嵌套内容中提取结构化 JSON")
            return parsed
    except json.JSONDecodeError:
        # 尝试使用 optimize_json_response 优化后再解析
        optimized = optimize_json_response(json_str)
        if optimized:
            try:
                parsed = json.loads(optimized)
                if isinstance(parsed, dict) and (
                    "summary" in parsed or "data" in parsed
                ):
                    logger.debug("✅ 成功从嵌套内容中提取结构化 JSON（优化后）")
                    return parsed
            except json.JSONDecodeError:
                pass

    return None


def extract_structured_output(content: str) -> Dict[str, Any]:
    """
    从 LLM 输出中提取结构化输出 {summary, narrative, data, highlights}

    这是给 agent_graph._parse_response 使用的高级函数，整合了：
    1. JSON 优化（移除 markdown 标记、提取 JSON 边界等）
    2. 双重编码处理
    3. summary 清洗（移除 markdown 代码块标记）
    4. 兜底处理

    Args:
        content: LLM 原始输出内容

    Returns:
        结构化输出字典 {summary, narrative, data, highlights}
    """
    if not content:
        return {
            "summary": "无输出",
            "narrative": None,
            "data": None,
            "highlights": None,
        }

    # Step 1: 尝试直接解析
    parsed: Optional[Dict[str, Any]] = None
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        pass

    # Step 2: 如果直接解析失败，使用优化策略
    if parsed is None:
        optimized = optimize_json_response(content)
        if optimized:
            try:
                parsed = json.loads(optimized)
            except json.JSONDecodeError:
                pass

    # Step 2.5: 尝试从内容中智能提取嵌套的结构化 JSON
    if parsed is None:
        extracted = _try_extract_nested_structured_json(content)
        if extracted:
            parsed = extracted

    # Step 3: 如果仍然无法解析，返回兜底结果
    if parsed is None:
        # 从原始内容提取第一行作为 summary（排除 markdown 标记）
        first_line = ""
        for line in content.strip().split("\n"):
            line = line.strip()
            if line and not line.startswith("```"):
                first_line = line[:200]
                break
        return {
            "summary": first_line or "执行完成",
            "narrative": None,
            "data": {"raw_content": content},
            "highlights": None,
        }

    # Step 4: 如果不是字典，转为标准结构
    if not isinstance(parsed, dict):
        return {
            "summary": str(parsed)[:200] if parsed else "执行完成",
            "narrative": None,
            "data": parsed,
            "highlights": None,
        }

    # Step 5: 处理双重编码 {"result": "JSON字符串"}
    double_decoded = _try_parse_double_encoded(parsed)
    if double_decoded:
        parsed = double_decoded

    # Step 6: 检查是否有标准结构
    if "summary" in parsed or "data" in parsed:
        summary = parsed.get("summary") or ""

        # 清洗 summary：移除 markdown 代码块标记
        if isinstance(summary, str):
            summary = summary.strip()
            if summary.startswith("```"):
                # 如果 summary 就是代码块标记，尝试从 narrative 或 data 生成
                summary = ""
                if parsed.get("narrative") and isinstance(parsed["narrative"], str):
                    summary = parsed["narrative"][:100]
                elif parsed.get("data"):
                    # 从 data 中提取摘要
                    data = parsed["data"]
                    if isinstance(data, dict) and data.get("summary"):
                        summary = str(data["summary"])[:200]
                    elif isinstance(data, str):
                        summary = data[:200]
                if not summary:
                    summary = "执行完成"

        result = {
            "summary": summary,
            "narrative": parsed.get("narrative"),
            "data": parsed.get("data"),
            "highlights": parsed.get("highlights"),
        }
        # 保留 data_format 字段（供前端报告渲染判断 markdown/json）
        if "data_format" in parsed:
            result["data_format"] = parsed["data_format"]
        return result

    # Step 7: 兼容旧输出格式（没有 summary/data 字段）
    # 尝试从常见字段生成 summary
    summary = ""
    for field in ["result", "output", "content", "message"]:
        if field in parsed:
            value = parsed[field]
            if isinstance(value, str):
                summary = value[:200]
                break
            elif isinstance(value, dict) and value.get("summary"):
                summary = str(value["summary"])[:200]
                break

    if not summary:
        # 使用第一个非空字符串字段
        for key, value in parsed.items():
            if isinstance(value, str) and value.strip() and not key.startswith("_"):
                summary = value[:200]
                break

    if not summary:
        summary = "执行完成"

    result = {
        "summary": summary,
        "narrative": parsed.get("narrative"),
        "data": parsed,
        "highlights": parsed.get("highlights"),
    }
    if isinstance(parsed, dict) and "data_format" in parsed:
        result["data_format"] = parsed["data_format"]
    return result
