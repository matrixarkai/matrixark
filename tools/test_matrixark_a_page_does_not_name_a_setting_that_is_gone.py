#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 MatrixArkAI
"""No portal page names a setting the registry no longer offers.

A page that names a key nothing supplies does not fail. It renders its empty state, which reads as
"this build does not have that setting" -- and when the behaviour behind the key is still running,
that is a lie told quietly.

It happened. The one-box page named six settings, three for how a candidate is scored and three
for what bounds a retrieve. A later change culled the registry from 256 settings to 143 and took
all six with it, on the reasoning that they were internal knobs nobody should be turning. That
reasoning was right. What nobody checked was that a page was reading them, so both panels began
saying "This build offers none of them." while the profile went on deciding every result and the
caps went on cutting every retrieve.

Those two panels no longer ask the registry at all -- they ask what a retrieve applies, which is
the question they were always for. This guard is for the next one: any page that names a setting
by key is making a claim about the registry, and the registry is allowed to change under it.

**What this does not check** is the harder direction -- a page asking the registry a question the
registry cannot answer, as those panels were doing even while every key still resolved. A key that
exists is not a key that means what the page says it means. See
test_matrixark_the_page_reports_what_a_retrieve_applies for the one case where that was run down.
"""
from __future__ import annotations

import io
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import matrixark_gateway_config as cfg  # noqa: E402

TOOLS = os.path.dirname(os.path.abspath(__file__))
PORTAL = os.path.join(TOOLS, "portal")

# A key as the portal writes one: a dotted lower-case name in double quotes.
_KEY = re.compile(r'"([a-z][a-z0-9_]*\.[a-z][a-z0-9_.]*)"')


def _sources() -> list:
    out = [os.path.join(PORTAL, "build_portal_pages.py")]
    out += [os.path.join(PORTAL, name) for name in sorted(os.listdir(PORTAL))
            if name.endswith(".html")]
    return out


def _named() -> dict:
    """Setting keys the portal names, to the files naming them.

    Group matched EXACTLY rather than by prefix. `key.startswith(GROUPS)` also accepts
    ``ingestion_portal.html``, which does start with a group name, and a sweep whose findings are
    mostly its own file names trains you to skim its output.
    """
    groups = {key.split(".")[0] for key in cfg.SETTINGS_BY_KEY}
    found: dict = {}
    for path in _sources():
        with io.open(path, encoding="utf-8") as handle:
            text = handle.read()
        for match in _KEY.finditer(text):
            key = match.group(1)
            if key.split(".")[0] in groups:
                found.setdefault(key, set()).add(os.path.basename(path))
    return found


class APageDoesNotNameASettingThatIsGoneTest(unittest.TestCase):

    def test_every_key_a_page_names_is_one_the_registry_offers(self) -> None:
        named = _named()
        missing = {key: sorted(files) for key, files in named.items()
                   if key not in cfg.SETTINGS_BY_KEY}
        self.assertEqual({}, missing,
                         "these keys are named by a page and absent from the registry, so the "
                         "panel that reads them renders an empty state rather than an error: %r"
                         % missing)

    def test_the_sweep_found_keys_to_check(self) -> None:
        """The vacuity guard, and the one that matters most here.

        The assertion above passes perfectly over an empty set, and an empty set is what a change
        to how keys are spelled produces -- the pattern stops matching, the sweep finds nothing,
        and the guard goes green for the rest of its life. Asserted against a floor rather than an
        exact count so that culling a setting a page names is a failure of the test above, not of
        this one.
        """
        named = _named()
        self.assertGreaterEqual(
            len(named), 3,
            "the key pattern matched %d keys across %d files; it has probably stopped matching "
            "how the portal writes a setting key, and this guard is now vacuous"
            % (len(named), len(_sources())))

    def test_there_are_pages_to_sweep(self) -> None:
        """The other way to sweep nothing: read the wrong directory."""
        pages = [p for p in _sources() if p.endswith(".html")]
        self.assertGreaterEqual(len(pages), 7, "found %r" % pages)

    def test_the_registry_is_not_empty(self) -> None:
        """And the third: compare against an empty registry and every key is 'offered'."""
        self.assertGreaterEqual(len(cfg.SETTINGS_BY_KEY), 50,
                                "the registry looks empty, so the comparison above is vacuous")


if __name__ == "__main__":
    unittest.main()
