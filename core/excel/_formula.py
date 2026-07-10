"""
core/excel/_formula.py — evaluate the simple arithmetic the user types into
Amount cells (e.g. "=2095/2.07" for a currency conversion).

openpyxl never recalculates formulas, and after it round-trips a workbook
(load with data_only=False, then save), Excel's cached formula results are
dropped for the whole file — so reading Amount via data_only=True right
after our own write returns None. These Amount formulas are always plain
numeric arithmetic (no cell references), so we evaluate them ourselves
instead of depending on a cached value that may not exist.
"""
from __future__ import annotations

import ast
import operator

_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def _eval_node(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval_node(node.left), _eval_node(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval_node(node.operand))
    raise ValueError("unsupported expression")


def amount_value(raw) -> float | None:
    """Numeric amount from a cell's raw (data_only=False) value. Handles
    plain numbers and simple '=a op b' arithmetic. Returns None for
    anything else (empty cell, cell-reference formula, array formula)."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str) and raw.startswith("="):
        try:
            tree = ast.parse(raw[1:], mode="eval")
            return float(_eval_node(tree.body))
        except Exception:
            return None
    return None
