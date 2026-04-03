from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Iterable, Set


@dataclass(frozen=True)
class AnalysisResult:
    ok: bool
    message: str


class StaticCodeAnalyzer:
    def __init__(self, safe_imports: Iterable[str]) -> None:
        self._safe_imports: Set[str] = set(safe_imports)

    def analyze(self, code: str) -> AnalysisResult:
        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            return AnalysisResult(False, f"Syntax error: {exc}")

        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if not self._is_import_allowed(node):
                    return AnalysisResult(False, "Disallowed import detected.")
            if isinstance(node, ast.Call) and self._is_dangerous_call(node):
                return AnalysisResult(False, "Disallowed call detected.")
        return AnalysisResult(True, "ok")

    def _is_import_allowed(self, node: ast.AST) -> bool:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] not in self._safe_imports:
                    return False
        if isinstance(node, ast.ImportFrom):
            if node.module and node.module.split(".")[0] not in self._safe_imports:
                return False
        return True

    @staticmethod
    def _is_dangerous_call(node: ast.Call) -> bool:
        if isinstance(node.func, ast.Name):
            return node.func.id in {"exec", "eval", "__import__", "open", "compile"}
        if isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name):
                return node.func.value.id in {"os", "sys", "subprocess", "socket"}
        return False
