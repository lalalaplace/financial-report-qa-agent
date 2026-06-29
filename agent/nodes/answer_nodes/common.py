"""回答模块共享工具。"""


def _fmt_yuan_value(value: float) -> str:
    """将元值格式化为亿元显示。"""
    return f"{value / 100000000:.2f} 亿元"


def _section_numeral(index: int) -> str:
    numerals = ["一", "二", "三", "四", "五", "六", "七", "八", "九", "十"]
    return numerals[index - 1] if 1 <= index <= len(numerals) else str(index)
