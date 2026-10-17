#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 MatrixArkAI
"""Every copy guard in this tree matches on the function NAME. A renamed copy is invisible to all of them.

`test_an_unreachable_module_does_not_hold_a_diverged_copy` collects definitions by name and compares
the bodies of same-named pairs. `test_there_is_one_copy_of_each_helper` does the same. Both are the
right shape for a copied function that kept its name, and neither can see a copy that was renamed --
which is the usual way a copy is made, because renaming is what stops a reader noticing.

This asks the question without reading names at all:

  1. give each STATEMENT a signature built from structure, attribute names and literals, with local
     variable and argument names abstracted away, so a renamed copy still matches and two unrelated
     `for` loops still do not;
  2. a function body is a sequence of those signatures, and a copy is that sequence appearing as a
     contiguous run inside another function -- which also catches a body that was INLINED into a
     larger function rather than copied as a function;
  3. verify every signature-level candidate by fully normalising both sides, so a signature
     collision cannot produce a false report;
  4. keep only the pairs whose two names DIFFER, because the same-name ones are already covered.

WHAT IT FINDS TODAY, and why it is worth a ratchet: five pairs, three of them with BOTH holders
reachable from production. Those three are two live copies each, identical as of this commit, watched
by nothing. They are exactly the setup where a fix lands on one copy and the other keeps the bug.

WHAT IT DOES NOT FIND, stated because the omission is the honest limit of the method: a copy that was
edited after being taken. `matrixark_mcp_recovery` inlines a third copy of the pipeline-task fold
under local names, and this scan does not report it, because that copy ranks three statuses where the
original ranks eight -- it is a VARIANT, not a copy. Exact structural equality is what makes the scan
cheap (under five seconds over 4,279 functions) and precise enough to ratchet; near-copy detection is
a different instrument and would need a similarity threshold and a way to argue about it.

This file changes no behaviour. It records a count.
"""
from __future__ import annotations

import ast
import functools
import pathlib
import unittest
from collections import defaultdict

TOOLS = pathlib.Path(__file__).resolve().parent

#: A run shorter than this matches everywhere -- two guard clauses and a return are not a copy.
MIN_STATEMENTS = 5

#: Renamed copy pairs on this commit. Raise it only with a sentence saying why the new copy is
#: right; lower it when one is consolidated away.
#:
#: The five, and the three that matter:
#:   codex_hook.is_synthetic_hook_text / http._hook_text_is_synthetic          BOTH REACHABLE
#:   core.ordered_normalized_role_list / context_pack._ordered_normalized_roles BOTH REACHABLE
#:   temporal_append.materialize_appended_records_locked
#:       / temporal_direct_write._materialize_appended_records_locked          BOTH REACHABLE
#:   direct_cache.placement_candidate_records_from_cache_or_load
#:       / temporal_direct_read._placement_candidate_records_from_cache_or_load one reachable
#:   session_runtime._append_records inlined in its own append_session_commit_task_progress
RECORDED_RENAMED_COPIES = 5

#: Floor for the scan itself, not for the group it produces. A scan that silently stopped parsing
#: would report zero copies and satisfy the ratchet forever.
MINIMUM_FUNCTIONS_SCANNED = 3000

#: Fields holding a NAME rather than structure. Skipping them is what makes the scan name-blind.
_NAME_FIELDS = {
    ("Name", "id"), ("arg", "arg"), ("alias", "asname"), ("alias", "name"),
    ("FunctionDef", "name"), ("AsyncFunctionDef", "name"), ("ClassDef", "name"),
    ("Global", "names"), ("Nonlocal", "names"),
}


def _signature(node: ast.AST) -> str:
    """Structure, attribute names and literals; local names abstracted away."""
    parts: list[str] = []

    def walk(item) -> None:
        if isinstance(item, ast.AST):
            cls = type(item).__name__
            parts.append(cls)
            for field, value in ast.iter_fields(item):
                if (cls, field) in _NAME_FIELDS:
                    continue
                parts.append(field)
                walk(value)
        elif isinstance(item, list):
            parts.append("[")
            for element in item:
                walk(element)
            parts.append("]")
        else:
            parts.append(repr(item))

    walk(node)
    return "".join(parts)


class _Abstract(ast.NodeTransformer):
    """Rename locals to positional placeholders so a renamed copy normalises identically."""

    def __init__(self) -> None:
        self._mapping: dict[str, str] = {}

    def _placeholder(self, key: str) -> str:
        if key not in self._mapping:
            self._mapping[key] = "v%d" % len(self._mapping)
        return self._mapping[key]

    def visit_Name(self, node: ast.Name):
        return ast.copy_location(ast.Name(id=self._placeholder(node.id), ctx=node.ctx), node)

    def visit_arg(self, node: ast.arg):
        return ast.copy_location(ast.arg(arg=self._placeholder(node.arg), annotation=None), node)


def _normalised(statements: list[ast.stmt]) -> str:
    module = ast.Module(body=[ast.parse(ast.unparse(s)).body[0] for s in statements],
                        type_ignores=[])
    abstracted = _Abstract().visit(module)
    ast.fix_missing_locations(abstracted)
    return ast.unparse(abstracted)


def _body(node) -> list[ast.stmt]:
    """The body without its docstring -- a shared docstring is not evidence of a copy."""
    return [s for s in node.body
            if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))]


@functools.lru_cache(maxsize=1)
def _functions() -> dict[tuple[str, str, int], ast.AST]:
    found: dict[tuple[str, str, int], ast.AST] = {}
    for path in sorted(TOOLS.glob("*.py")):
        if path.name.startswith("test_"):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                found[(path.stem, node.name, node.lineno)] = node
    return found


@functools.lru_cache(maxsize=1)
def _renamed_copies():
    """(pairs, functions_scanned, candidates_verified).

    `pairs` maps an unordered {(module, name), (module, name)} to the run length.
    """
    functions = _functions()
    signatures = {key: [_signature(s) for s in _body(node)] for key, node in functions.items()}

    starting_at = defaultdict(list)
    for key, sequence in signatures.items():
        for index, item in enumerate(sequence):
            starting_at[item].append((key, index))

    pairs: dict[frozenset, int] = {}
    verified = 0
    for key, sequence in signatures.items():
        if len(sequence) < MIN_STATEMENTS:
            continue
        for other, start in starting_at.get(sequence[0], []):
            if other == key:
                continue
            other_sequence = signatures[other]
            if start + len(sequence) > len(other_sequence):
                continue
            if other_sequence[start:start + len(sequence)] != sequence:
                continue
            verified += 1
            try:
                if _normalised(_body(functions[key])) != _normalised(
                        _body(functions[other])[start:start + len(sequence)]):
                    continue
            except Exception:
                continue
            if key[1] == other[1]:
                continue                  # same name: the existing guards already see it
            pairs[frozenset([(key[0], key[1]), (other[0], other[1])])] = len(sequence)
    return pairs, len(functions), verified


def _describe(pairs) -> str:
    out = []
    for pair in sorted(pairs, key=sorted):
        (first_module, first_name), (second_module, second_name) = sorted(pair)
        out.append("%s.%s == %s.%s" % (first_module, first_name, second_module, second_name))
    return "; ".join(out)


class ARenamedCopyIsStillACopy(unittest.TestCase):

    def test_the_scan_actually_reads_the_tree(self):
        """The floor, on the SCAN rather than on the group it produces.

        A scan that stopped parsing reports zero copies, which satisfies the ratchet forever.
        """
        _pairs, scanned, verified = _renamed_copies()
        self.assertGreaterEqual(
            scanned, MINIMUM_FUNCTIONS_SCANNED,
            "only %d functions were scanned, below the recorded floor of %d -- the scan is not "
            "reading the tree and every assertion below is about nothing"
            % (scanned, MINIMUM_FUNCTIONS_SCANNED))
        self.assertGreater(
            verified, 0,
            "no candidate run was ever verified, so the matcher is not matching and a copy could "
            "not be detected however many were added")

    def test_the_name_abstraction_actually_ignores_names(self):
        """A unit test of the machinery, independent of what the tree happens to contain.

        Without this, a scan that quietly LOST its name-blindness looks exactly like somebody having
        consolidated a pair -- both simply lower the count. This one fails for the first and not the
        second, so the two causes have different signatures and the remediation advice above can be
        trusted rather than guessed at.
        """
        first = ast.parse('def a(rows):\n    out = []\n    seen = set()\n    for row in rows:\n        out.append(row)\n    return out').body[0]
        second = ast.parse('def b(items):\n    kept = []\n    marked = set()\n    for item in items:\n        kept.append(item)\n    return kept').body[0]
        self.assertEqual(
            [_signature(node) for node in _body(first)],
            [_signature(node) for node in _body(second)],
            "two bodies identical but for their local names no longer produce the same signatures, "
            "so every renamed copy in the tree has just become invisible to this scan")
        self.assertEqual(
            _normalised(_body(first)), _normalised(_body(second)),
            "the verification step is no longer name-blind, so it would reject every renamed copy "
            "the signature step proposes")

        # The other direction: name-blind must not mean shape-blind.
        different_shape = ast.parse('def c(rows):\n    out = []\n    seen = set()\n    for row in rows:\n        out.insert(0, row)\n    return seen').body[0]
        self.assertNotEqual(
            _normalised(_body(first)), _normalised(_body(different_shape)),
            "two bodies that differ in what they CALL and what they return normalise identically, "
            "so this scan would report every similarly shaped loop in the tree as a copy")

    def test_the_detector_finds_some_renamed_copy(self):
        """Positive control. A detector that finds none would satisfy the ratchet forever."""
        pairs, _scanned, _verified = _renamed_copies()
        self.assertTrue(
            pairs,
            "no renamed copies found at all. Either every one was consolidated -- in which case "
            "lower RECORDED_RENAMED_COPIES to 0 and say so -- or the name-abstraction stopped "
            "working and this file now guards nothing")

    def test_a_renamed_copy_is_invisible_to_a_name_matching_scan(self):
        """Why this file exists beside the two guards that already compare copies.

        Both of those group definitions by identical name. For each pair found here, neither name is
        defined in the other's module, so no name-matching detector can pair them however it is
        pointed. Without this the file could be redundant with the existing ratchet and nobody
        would know.
        """
        pairs, _scanned, _verified = _renamed_copies()
        self.assertTrue(pairs, "no pairs to check; the positive control above explains it")
        defined_names = defaultdict(set)
        for module, name, _line in _functions():
            defined_names[module].add(name)
        visible = []
        for pair in pairs:
            (first_module, first_name), (second_module, second_name) = sorted(pair)
            if first_module == second_module:
                continue              # an inlined copy inside one module; names still differ
            if (second_name in defined_names[first_module]
                    or first_name in defined_names[second_module]):
                visible.append("%s.%s / %s.%s"
                               % (first_module, first_name, second_module, second_name))
        self.assertEqual(
            [], visible,
            "%d pair(s) could be found by matching names after all, so this scan is not the only "
            "thing covering them: %s" % (len(visible), visible))

    def test_no_new_renamed_copy_appears(self):
        """The ratchet. Reading is what costs; all a test can do is stop the pile growing."""
        pairs, _scanned, _verified = _renamed_copies()
        self.assertLessEqual(
            len(pairs), RECORDED_RENAMED_COPIES,
            "the tree now holds %d renamed copies of a function body, up from %d. A renamed copy "
            "is invisible to every guard here that matches on names, so a fix landing on one side "
            "leaves the other with the bug and nothing says so. Pairs now: %s"
            % (len(pairs), RECORDED_RENAMED_COPIES, _describe(pairs)))

    def test_the_recorded_count_has_not_silently_fallen(self):
        """The other direction. A consolidation is good news, and it should re-bank the number.

        Left alone, a number recorded above the real one is slack the next copy hides in.
        """
        pairs, _scanned, _verified = _renamed_copies()
        self.assertGreaterEqual(
            len(pairs), RECORDED_RENAMED_COPIES,
            "only %d renamed copies remain, down from the recorded %d. Two different causes look "
            "identical here: a pair was CONSOLIDATED, in which case lower RECORDED_RENAMED_COPIES "
            "to %d and say so in the commit; or the scan lost its name-blindness and stopped "
            "seeing them, in which case test_the_name_abstraction_actually_ignores_names is red "
            "too and this number must NOT be lowered. Check that one first. Pairs now: %s"
            % (len(pairs), RECORDED_RENAMED_COPIES, len(pairs), _describe(pairs)))


if __name__ == "__main__":
    unittest.main()
