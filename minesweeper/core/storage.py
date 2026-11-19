"""配置与历史战绩的读写（从旧版 mine.py 末尾的 read_config / log_function_call 拆出）。

这一层只碰文件系统，不碰 Qt，方便用临时目录做单元测试。
"""

import json
import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

#: 旧版 mine.py 的默认配置（注意：16x16 配 99 雷，非常密集，但这是历史默认值）
DEFAULT_CONFIG = {"rows": 16, "cols": 16, "mines": 99}

#: 界面允许的范围，与 SettingsDialog 的 spinbox 范围一致
MIN_ROWS, MAX_ROWS = 9, 24
MIN_COLS, MAX_COLS = 9, 30
MIN_MINES, MAX_MINES = 10, 668


def is_valid_config(config: Any) -> bool:
    """校验配置是否合法（与旧版 read_config 的校验条件完全一致）。"""
    if not isinstance(config, dict):
        return False
    try:
        rows = config["rows"]
        cols = config["cols"]
        mines = config["mines"]
    except KeyError:
        return False
    if not all(isinstance(v, int) and not isinstance(v, bool) for v in (rows, cols, mines)):
        return False
    return (
        MIN_ROWS <= rows <= MAX_ROWS
        and MIN_COLS <= cols <= MAX_COLS
        and MIN_MINES <= mines <= MAX_MINES
    )


def load_config(path: str, default: Optional[Dict[str, int]] = None) -> Dict[str, int]:
    """读取配置；文件缺失、JSON 损坏或内容非法时写入并返回默认配置。"""
    default = dict(DEFAULT_CONFIG if default is None else default)

    try:
        with open(path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except FileNotFoundError:
        logger.warning("配置文件 %s 不存在，使用默认配置 %s", path, default)
        save_config(path, default)
        return default
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("配置文件 %s 读取失败（%s），使用默认配置", path, exc)
        save_config(path, default)
        return default

    if not is_valid_config(config):
        logger.warning("配置文件 %s 内容非法，使用默认配置", path)
        save_config(path, default)
        return default

    return {"rows": config["rows"], "cols": config["cols"], "mines": config["mines"]}


def save_config(path: str, config: Dict[str, int]) -> None:
    """把配置写入磁盘（UTF-8、4 空格缩进，与旧版一致）。"""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4, ensure_ascii=False)


def config_key(config: Dict[str, int]) -> str:
    """生成 results.json 里的分组键，例如 ``"16_16_99"``。"""
    return "{}_{}_{}".format(config["rows"], config["cols"], config["mines"])


def load_results(path: str) -> Dict[str, Any]:
    """读取历史战绩；文件缺失或损坏时返回空字典（旧版行为）。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def append_result(path: str, key: str, record: Dict[str, Any]) -> Dict[str, Any]:
    """追加一条战绩并写回磁盘。

    :return: 写入后的完整数据（方便测试断言）
    """
    data = load_results(path)
    if key in data:
        data[key].append(record)
    else:
        data[key] = [record]

    directory = os.path.dirname(os.path.abspath(path))
    if not os.path.isdir(directory):
        os.makedirs(directory, exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return data
