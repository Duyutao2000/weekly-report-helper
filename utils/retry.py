"""
重试工具 —— 指数退避 + 完全抖动

用于 LLM API 调用的自动重试。
"""

import random
import time
import logging
from enum import Enum
from functools import wraps

logger = logging.getLogger(__name__)


class ErrorCategory(Enum):
    """错误类别"""
    RETRYABLE = "retryable"           # 429, 5xx, 网络超时
    NON_RETRYABLE = "non_retryable"   # 400, 401, 403, 413
    UNKNOWN = "unknown"               # 未知错误，默认不重试


# 可重试的 HTTP 状态码
RETRYABLE_STATUS_CODES = frozenset({429})
RETRYABLE_STATUS_RANGES = [(500, 599)]  # 5xx 全系列

# 不可重试的 HTTP 状态码
NON_RETRYABLE_STATUS_CODES = frozenset({400, 401, 403, 413})

# 可重试的网络错误关键词
RETRYABLE_NETWORK_ERRORS = (
    "timeout", "timed out", "connection reset",
    "connection error", "connection refused",
    "too many requests", "rate limit",
)


def categorize_error(error: Exception) -> ErrorCategory:
    """
    判断错误是否值得重试。

    参数:
        error: 捕获的异常

    返回:
        ErrorCategory 枚举值
    """
    # 尝试从 OpenAI 异常中提取 HTTP 状态码
    status_code = getattr(error, "status_code", None)

    if status_code is not None:
        if status_code in RETRYABLE_STATUS_CODES:
            return ErrorCategory.RETRYABLE
        if status_code in NON_RETRYABLE_STATUS_CODES:
            return ErrorCategory.NON_RETRYABLE
        for lo, hi in RETRYABLE_STATUS_RANGES:
            if lo <= status_code <= hi:
                return ErrorCategory.RETRYABLE
        return ErrorCategory.UNKNOWN

    # 没有状态码的异常，检查错误消息
    error_msg = str(error).lower()
    for keyword in RETRYABLE_NETWORK_ERRORS:
        if keyword in error_msg:
            return ErrorCategory.RETRYABLE

    return ErrorCategory.UNKNOWN


def backoff_delay(attempt: int, base: float = 1.0, max_delay: float = 16.0) -> float:
    """
    计算指数退避 + 完全抖动后的等待时间。

    参数:
        attempt: 当前重试次数（0-based）
        base: 基础延迟秒数（默认 1s）
        max_delay: 最大延迟秒数（默认 16s）

    返回:
        等待秒数（浮点数）
    """
    delay = min(max_delay, base * (2 ** attempt))
    jittered = delay * random.random()
    return jittered


def with_retry(
    func,
    max_retries: int = 3,
    total_timeout: float = 30.0,
    base_delay: float = 1.0,
    max_delay: float = 16.0,
):
    """
    重试装饰器。

    参数:
        func: 被包装的函数
        max_retries: 最大重试次数（默认 3）
        total_timeout: 总超时秒数（默认 30s）
        base_delay: 基础延迟秒数（默认 1s）
        max_delay: 最大延迟秒数（默认 16s）

    返回:
        包装后的函数

    异常:
        RuntimeError: 重试耗尽后仍失败
        原始异常: 不可重试的错误直接抛出
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        last_error = None

        for attempt in range(max_retries + 1):  # 0..3，共 4 次（首次 + 3 次重试）
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_error = e
                elapsed = time.time() - start_time

                # 判断是否值得重试
                category = categorize_error(e)

                if category == ErrorCategory.NON_RETRYABLE:
                    logger.error(f"LLM 不可重试错误（不再重试）: {e}")
                    raise

                if category == ErrorCategory.UNKNOWN:
                    logger.warning(f"LLM 未知错误（不再重试）: {e}")
                    raise

                # 可重试，但检查剩余次数和总超时
                if attempt >= max_retries:
                    logger.error(f"LLM 重试耗尽（{max_retries}次），最后错误: {e}")
                    raise RuntimeError(f"LLM 调用失败，已重试 {max_retries} 次") from e

                if elapsed >= total_timeout:
                    logger.error(f"LLM 总超时（{total_timeout}s），最后错误: {e}")
                    raise TimeoutError(f"LLM 调用超过总超时 {total_timeout}s") from e

                delay = backoff_delay(attempt, base_delay, max_delay)
                logger.warning(
                    f"LLM 第 {attempt + 1}/{max_retries} 次重试，"
                    f"等待 {delay:.1f}s，错误: {e}"
                )
                time.sleep(delay)

        # 理论上不会到这里
        raise RuntimeError("LLM 调用失败") from last_error

    return wrapper
