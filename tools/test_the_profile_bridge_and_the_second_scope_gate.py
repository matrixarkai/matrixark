#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 MatrixArkAI
"""A retrieve sets up the profile bridge, asks for it to be honoured, then drops what it admitted.

Inside one request, `_LocalAdapterRetrieveMixin.retrieve`:

  1. sets `retrieval_scope["_allow_profile_bridge"]` from the cross-session policy;
  2. calls `self.retrieval_records(scope=retrieval_scope, ...)`, whose gate
     `session_scope_allows_record` honours that flag through `profile_bridge_scope_matches` and
     admits profile records that the cross-session clause would otherwise reject;
  3. re-filters those same records with its OWN gate, `session_scope_allows_retrieval_record`,
     which has no bridge clause.

So under `session_scope="only"` the bridge admits a record and the next filter drops it. The bridge
exists for nothing else: `profile_bridge_scope_matches` returns False unless the record IS a profile
record, which is exactly the set the clause after it rejects.

IT IS LIVE, NOT LATENT. `build_cross_session_policy` does not disable itself under "only" -- its
`cross_session_allowed` is true for a profile-memory query, a feature-memory query, any of seven
cross-session question types, or an explicit request, none of which require "prefer". So a
session-only request can and does carry `_allow_profile_bridge`.

WHAT THIS FILE DOES NOT DO. It does not add the bridge clause to the second gate. That would make
`retrieve` MORE permissive -- surfacing cross-session profile records in the one mode a caller may
have chosen precisely for isolation -- and what `session_scope="only"` promises is a product
question, not something a test should settle. The two readings are:

  * the second gate is missing a clause the module honours in three other places, and should honour
    it here too;
  * or "only" means only, the bridge in `retrieval_records` is the anomaly, and the second gate is
    the one stating the intended rule.

This file records the divergence and its blast radius so that choosing between those is a decision
rather than something nobody knows about. It changes no behaviour.

HOW THE GATES ARE REACHED. Both are nested inside mixin methods and cannot be imported, so they are
lifted out of the source by AST and run against stubs. The comparison stays honest because BOTH gates
get the SAME stubs: any disagreement is attributable to the gate bodies, not to what was handed to
them. The stubs deliberately do not model `recovered_scope_for_query` fully -- they do not need to,
because the question is whether the two gates differ, not what either returns in absolute terms.
"""
from __future__ import annotations

import ast
import pathlib
import unittest

TOOLS = pathlib.Path(__file__).resolve().parent

RETRIEVAL_MODULE = TOOLS / "matrixark_local_adapter_retrieval.py"
RETRIEVE_MODULE = TOOLS / "matrixark_local_adapter_retrieve.py"

#: Sites in the retrieve module that DO honour the flag. The count is the evidence that the missing
#: clause is an omission rather than a policy: the module knows about the bridge everywhere else.
MINIMUM_BRIDGE_AWARE_SITES_IN_RETRIEVE = 3


def _lift(name: str, path: pathlib.Path) -> str:
    """Source of a nested function, decorators stripped, so it can be executed standalone."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            node.decorator_list = []
            return ast.unparse(node)
    raise AssertionError(
        "%s is no longer defined in %s. If it was renamed or moved this file must be re-pointed; "
        "if it was deleted, say which of the two readings in the docstring was chosen."
        % (name, path.name))


def _session_scope_mode(scope: dict) -> str:
    return str(scope.get("session_scope") or "prefer").strip().lower()


def _recovered_scope_for_query(record: dict, query_scope: dict) -> dict:
    return record.get("scope") or {}


def _gates():
    """(gate in retrieval_records, gate in retrieve, the bridge matcher), all sharing stubs."""
    namespace = {
        "Json": dict,
        "session_scope_mode": _session_scope_mode,
        "recovered_scope_for_query": _recovered_scope_for_query,
        "scope_from_node_path": lambda node_path: {},
        "parse_scope_key": lambda key: {},
    }
    for name, path in (("profile_bridge_scope_matches", RETRIEVAL_MODULE),
                       ("session_scope_allows_record", RETRIEVAL_MODULE),
                       ("session_scope_allows_retrieval_record", RETRIEVE_MODULE)):
        exec(compile(_lift(name, path), "<lifted %s>" % name, "exec"), namespace)
    return (namespace["session_scope_allows_record"],
            namespace["session_scope_allows_retrieval_record"],
            namespace["profile_bridge_scope_matches"])


SESSION_ONLY = {
    "session_scope": "only",
    "session_id": "session-now",
    "tenant_id": "acme",
    "user_id": "dana",
    "_allow_profile_bridge": True,
}

#: A cross-session profile record -- the only thing the bridge is for.
PROFILE_RECORD = {
    "record_type": "context_entity",
    "memory_scope": "cross_session_profile",
    "session_continuity": "cross_session",
    "scope": {"tenant_id": "acme", "user_id": "dana", "session_id": "session-earlier"},
    "node_path": ["profile:long_term_memory", "dana"],
}
OTHER_SESSION_RECORD = {
    "record_type": "context_event",
    "memory_scope": "session",
    "scope": {"tenant_id": "acme", "user_id": "dana", "session_id": "session-earlier"},
}
THIS_SESSION_RECORD = {
    "record_type": "context_event",
    "memory_scope": "session",
    "scope": {"tenant_id": "acme", "user_id": "dana", "session_id": "session-now"},
}


class TheProfileBridgeAndTheSecondScopeGate(unittest.TestCase):

    def test_both_gates_are_still_there_and_agree_on_ordinary_records(self):
        """The floor and the control in one.

        If the two gates disagreed about everything, the specific disagreement below would say
        nothing about the bridge. They agree on both ordinary cases.
        """
        in_records, in_retrieve, _bridge = _gates()
        for label, record in (("from another session", OTHER_SESSION_RECORD),
                              ("from this session", THIS_SESSION_RECORD)):
            self.assertEqual(
                in_records(record, SESSION_ONLY), in_retrieve(record, SESSION_ONLY),
                "the two gates now disagree on an ordinary record %s, so they differ by more than "
                "the bridge clause and this file no longer isolates it" % label)

    def test_the_bridge_admits_a_profile_record_and_the_second_gate_drops_it(self):
        """The finding."""
        in_records, in_retrieve, _bridge = _gates()
        self.assertTrue(
            in_records(PROFILE_RECORD, SESSION_ONLY),
            "retrieval_records no longer admits a bridged profile record, so the bridge has "
            "stopped working on its own side and this divergence has become something else")
        self.assertFalse(
            in_retrieve(PROFILE_RECORD, SESSION_ONLY),
            "retrieve now admits the bridged profile record too -- the gates agree, and if the "
            "bridge clause was added deliberately this file should be replaced with one asserting "
            "the new rule")

    def test_the_flag_is_what_causes_the_disagreement(self):
        """The other direction. Without the flag the two gates agree, so the flag is the cause."""
        in_records, in_retrieve, _bridge = _gates()
        without_flag = {**SESSION_ONLY, "_allow_profile_bridge": False}
        self.assertEqual(
            in_records(PROFILE_RECORD, without_flag), in_retrieve(PROFILE_RECORD, without_flag),
            "the gates disagree on a profile record even with the bridge switched off, so the "
            "difference is no longer the bridge clause")
        self.assertFalse(
            in_records(PROFILE_RECORD, without_flag),
            "retrieval_records admits the profile record with the bridge off, so the bridge is no "
            "longer what admits it")

    def test_the_blast_radius_is_session_scope_only(self):
        """What is NOT affected, asserted rather than assumed.

        Both gates return True immediately unless the mode is "only", and `prefer` is the default,
        so an ordinary request never reaches the divergence. This bounds the finding.
        """
        in_records, in_retrieve, _bridge = _gates()
        for mode in ("prefer", "", "allow"):
            scope = {**SESSION_ONLY, "session_scope": mode}
            self.assertEqual(
                in_records(PROFILE_RECORD, scope), in_retrieve(PROFILE_RECORD, scope),
                "the two gates now disagree under session_scope=%r as well, so the finding is no "
                "longer confined to session-only requests and is much wider than recorded" % mode)

    def test_the_bridge_only_ever_matches_a_profile_record(self):
        """Why the dropped record is precisely the one the bridge exists for.

        If the matcher admitted ordinary records too, the second gate dropping them would be a
        different and smaller story.
        """
        _in_records, _in_retrieve, bridge = _gates()
        self.assertTrue(
            bridge(PROFILE_RECORD, SESSION_ONLY),
            "the bridge matcher no longer matches a cross-session profile record, which is the "
            "only thing it was written to match")
        self.assertFalse(
            bridge(OTHER_SESSION_RECORD, SESSION_ONLY),
            "the bridge matcher now admits an ordinary cross-session record, which would widen "
            "session-only mode far beyond profile records")

    def test_the_retrieve_module_honours_the_flag_everywhere_else(self):
        """The evidence that the missing clause is an omission rather than a stated policy.

        If this count ever falls to zero, the module has stopped knowing about the bridge at all and
        the second reading in the docstring -- that "only" means only -- has become the tree's
        actual position, which is a different situation from the one recorded here.
        """
        source = RETRIEVE_MODULE.read_text(encoding="utf-8")
        reads = source.count('retrieval_scope.get("_allow_profile_bridge")')
        self.assertGreaterEqual(
            reads, MINIMUM_BRIDGE_AWARE_SITES_IN_RETRIEVE,
            "the retrieve module now reads _allow_profile_bridge at only %d site(s), down from %d. "
            "The recorded finding rests on the module honouring the flag everywhere except in its "
            "own scope gate; if it has stopped honouring it generally, re-read the finding before "
            "acting on it" % (reads, MINIMUM_BRIDGE_AWARE_SITES_IN_RETRIEVE))
        self.assertIn(
            '_allow_profile_bridge', source,
            "the retrieve module no longer sets or reads the bridge flag at all")


if __name__ == "__main__":
    unittest.main()
