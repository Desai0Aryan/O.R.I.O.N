"""A safe calculator (no eval of arbitrary code)."""
import ast
import math
import operator as op

_BIN = {ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul, ast.Div: op.truediv, ast.FloorDiv: op.floordiv,
        ast.Mod: op.mod, ast.Pow: op.pow}
_UN = {ast.UAdd: op.pos, ast.USub: op.neg}
_FN = {"sqrt": math.sqrt, "sin": math.sin, "cos": math.cos, "tan": math.tan, "asin": math.asin, "acos": math.acos,
       "atan": math.atan, "log": math.log, "ln": math.log, "log10": math.log10, "log2": math.log2, "exp": math.exp,
       "abs": abs, "round": round, "min": min, "max": max, "floor": math.floor, "ceil": math.ceil,
       "factorial": math.factorial, "radians": math.radians, "degrees": math.degrees}
_CONST = {"pi": math.pi, "e": math.e, "tau": math.tau}


def _ev(n):
    if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
        return n.value
    if isinstance(n, ast.BinOp) and type(n.op) in _BIN:
        a, b = _ev(n.left), _ev(n.right)
        if isinstance(n.op, ast.Pow) and abs(b) > 1000:
            raise ValueError("exponent too large")
        return _BIN[type(n.op)](a, b)
    if isinstance(n, ast.UnaryOp) and type(n.op) in _UN:
        return _UN[type(n.op)](_ev(n.operand))
    if isinstance(n, ast.Name) and n.id in _CONST:
        return _CONST[n.id]
    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in _FN and not n.keywords:
        args = [_ev(a) for a in n.args]
        if n.func.id == "factorial" and (not args or args[0] > 500):
            raise ValueError("too large")
        return _FN[n.func.id](*args)
    raise ValueError("unsupported expression")


def calculate(expression):
    expr = str(expression).replace("^", "**").replace("×", "*").replace("÷", "/").replace(",", "")
    if len(expr) > 200:
        raise ValueError("expression too long")
    v = _ev(ast.parse(expr.strip(), mode="eval").body)
    return {"expression": expression, "result": round(v, 10) if isinstance(v, float) else v}


def register(agent):
    agent.register("calculate", calculate,
                   "calculate(expression: str) - exact arithmetic and math (+ - * / ** %, sqrt, log, sin, pi...). Use it instead of mental maths")
