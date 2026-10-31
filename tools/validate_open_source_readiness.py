#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 MatrixArkAI
"""Validate repository-level open-source readiness files."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

# THE GOVERNANCE DOCS ARE AT THE ROOT IN THIS REPOSITORY, not under `docs/`. They were listed
# under `docs/` because this validator arrived as a copy of one written for a tree that keeps them
# there, and `read()` raises on the first missing path -- so every check below the file loop, the
# private-path scan included, had never executed here.
#
# `open_source_readiness.md` is deliberately absent rather than relocated: it does not exist in this
# repository under any path, and requiring a document that was never written here would be a gate
# that can only be satisfied by inventing one.
REQUIRED_FILES = [
    "README.md",
    "LICENSE",
    "NOTICE",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "CODE_OF_CONDUCT.md",
    ".gitignore",
    "tools/run_matrixark_context_backfill_ci_gate_ubuntu22.sh",
    "tools/verify_matrixark_context_backfill_ci_evidence.py",
]

# THE TOKENS ASSERT THE OPENNESS PROMISE, which is the thing that must not quietly disappear.
#
# They used to be another tree's prose -- "rust-main", "no brpc/thrift", "TS_RAFT_AUTH_TOKEN" -- and
# 1 of 5, 0 of 3 and 0 of 3 of them were present in this repository's own documents. A token list
# that cannot match is indistinguishable from no gate at all, so they are retargeted at sentences
# this repository actually makes, and each one is load-bearing: delete the licence line, or the
# promise that anybody may use and fork this, and the gate fails.
README_TOKENS = [
    "Apache License 2.0",
    "for anyone in the world to use, fork",
    "Issues and pull requests are welcome from everyone",
    "public and Apache-2.0",
]

# Reporting must stay PRIVATE and the advisory route must stay named. A security policy that drops
# the private channel sends the next reporter to a public issue.
SECURITY_TOKENS = [
    "privately",
    "security/advisories/new",
    "rather than\nopening a public issue or pull request",
]

# Contribution must stay open to people with no affiliation, and the inbound licence must stay
# stated -- without it a contributor has not agreed to anything.
CONTRIBUTING_TOKENS = [
    "Issues, discussion and pull requests",
    "from anyone",
    "Apache-2.0 and open to the world",
    "licensed under the Apache",
]

# THIS IS A PYTHON TREE, so the build outputs that must stay untracked are Python's. The previous
# list named a Rust target directory and three build trees that do not exist here; only `.codex/`
# overlapped, and it is kept because a tracked local agent config is checked separately below.
IGNORE_TOKENS = [
    "__pycache__/",
    "build/",
    "dist/",
    ".eggs/",
    "*.egg-info/",
    ".pytest_cache/",
]

BACKFILL_CI_GATE_TOKENS = [
    "MatrixArk context backfill CI gate for Ubuntu 22",
    "MATRIXARK_BACKFILL_CI_RECORDS",
    "MATRIXARK_BACKFILL_CI_BATCH_SIZES",
    "MATRIXARK_BACKFILL_CI_INCREMENTAL_RECORDS",
    "MATRIXARK_BACKFILL_CI_EVIDENCE_MANIFEST",
    "python3 -m py_compile",
    "python3 tools/test_matrixark_context_backfill.py",
    "python3 tools/test_matrixark_context_backfill_benchmark.py",
    "python3 tools/test_matrixark_dual_write_ingestion_benchmark.py",
    "python3 tools/test_verify_matrixark_context_backfill_ci_evidence.py",
    "python3 tools/test_validate_matrixark_context_backfill_readiness.py",
    "python3 tools/test_validate_open_source_readiness.py",
    "python3 tools/validate_open_source_readiness.py",
    "python3 tools/validate_matrixark_context_backfill_readiness.py",
    "matrixark_context_backfill_readiness.json",
    "matrixark_context_backfill_ci_evidence_manifest_v1",
    "matrixark_context_backfill_evidence_manifest",
    "verify_matrixark_context_backfill_ci_evidence.py",
    "matrixark_context_backfill_ci_evidence_verification_status",
    "os.path.relpath",
    "--require-relative-paths=1",
    "readiness_status_ok",
    "readiness_checks_all_passed",
    "readiness_required_sections_ok",
    "artifact_paths_within_dir",
    "dual_write_readiness_status_ok",
    "dual_write_manifest_schema_supported",
    "dual_write_manifest_status_ok",
    "dual_write_manifest_required_artifacts_present",
    "dual_write_manifest_artifact_paths_relative",
    "dual_write_manifest_artifact_paths_within_dir",
    "dual_write_manifest_artifact_paths_readable",
    "dual_write_manifest_artifact_sizes_match",
    "dual_write_manifest_artifact_sha256_match",
]

# Keep private account markers out of the published rule source itself.
PRIVATE_ACCOUNT_MARKER = bytes.fromhex("64656570726f757465").decode("ascii")

PRIVATE_PATH_TOKENS = [
    "C:\\Users\\",
    "/mnt/c/Users",
    "/mnt/c/Users/",
    "/root/src/",
    "Vincent Jiang",
]

FALLBACK_SCAN_SKIP_DIRS = {
    ".git",
    "target",
    "target-rust-bench",
    "build-ubuntu22",
    "output",
    "benchmark_reports",
    "thirdparty",
    "__pycache__",
}

# Names of products, toolchains and internal systems that do not belong in an
# open-source repository. Nothing else in CI has an opinion about prose, so a
# change can add hundreds of occurrences and still pass every other gate.
#
# `matrixobjectstore` is deliberately NOT here: the crate of that name is Apache-2.0
# open source and public, so its name is ordinary published API rather than a product
# name that does not belong here. validate_no_enterprise_object_store draws the line
# that still matters -- depending on that crate versus containing it, and the separate
# NATIVE implementation whose sources are not public. A blanket match would fail on
# every legitimate use of the name.
FOREIGN_VOCABULARY: list[tuple[str, str, int]] = [
    (
        "language and toolchain names",
        r"c\+\+|cplusplus|c_plus_plus|(?<![A-Za-z])cxx(?![A-Za-z])"
        r"|(?<![A-Za-z])cpp(?![A-Za-z])|(?<![A-Za-z])gtest(?![A-Za-z])",
        re.IGNORECASE,
    ),
    (
        "third-party product names",
        r"(?<![A-Za-z])(lark|feishu|wukong|bytedance|byteraft|bytestore|mtcache"
        r"|openviking|vikingmem)(?![A-Za-z])|volcano engine",
        re.IGNORECASE,
    ),
    # "abase" is a substring of "database", so it only counts on a token boundary.
    ("internal datastore name", r"(?<![A-Za-z])abase(?![A-Za-z])", re.IGNORECASE),
    # The C-FFI spelling is CIpsFoo, which a token-start-only pattern misses, and
    # this one is case-sensitive on purpose: "ips" alone is ordinary English.
    ("retired data-model name", r"(?<![A-Za-z0-9])(C?Ips[A-Z]|ips_|IPS(?![a-zA-Z]))", 0),
]

# These files carry the patterns above as fixtures or as the check itself, in the
# same way PRIVATE_PATH_FIXTURE_FILES carries the private-path patterns.
FOREIGN_VOCABULARY_FIXTURE_FILES = {
    "tools/validate_open_source_readiness.py",
}

# Source files of the NATIVE object-store implementation, which is a different tree from the
# Apache-2.0 `matrixobjectstore-rs` crate in matrixarkai/MatrixObject -- that one is public and
# Rust-only, and holds none of these basenames. A public file has no reason to name one of these:
# it cannot build them, and naming them maps out a tree that does not ship.
ENTERPRISE_NATIVE_SOURCES = [
    "objectstore.cc",
    "objectstore.h",
    "objectstore_rpc.cc",
]

# This file carries those names as the rule itself, exactly as it carries the private-path and
# vocabulary patterns below.
ENTERPRISE_SOURCE_FIXTURE_FILES = {
    "tools/validate_open_source_readiness.py",
}

PRIVATE_PATH_FIXTURE_FILES = {
    "tools/validate_open_source_readiness.py",
    "tools/validate_temporalstore_performance_execution_redaction.py",
    "tools/test_temporalstore_performance_execution_redaction.py",
}

def read(relative_path: str) -> str:
    path = ROOT / relative_path
    if not path.exists():
        raise SystemExit(f"missing required file: {relative_path}")
    return path.read_text(encoding="utf-8", errors="replace")


def require_tokens(relative_path: str, tokens: list[str]) -> None:
    text = read(relative_path)
    normalized = " ".join(text.split())
    missing = [token for token in tokens if token not in text and token not in normalized]
    if missing:
        raise SystemExit(f"{relative_path} missing tokens: {', '.join(missing)}")


def validate_package_license() -> None:
    """The licence must be declared where a PACKAGING TOOL reads it, not only in LICENSE.

    This repository ships as a Python package and has no Cargo manifest; the check it inherited
    read one, so it could never pass here. `pyproject.toml` is the equivalent position: the
    `license` field is what an index publishes and what a consumer's scanner reads, and the OSI
    classifier is what makes the licence machine-identifiable rather than merely present.
    """
    pyproject = read("pyproject.toml")
    if 'license = { text = "Apache-2.0" }' not in pyproject:
        raise SystemExit('pyproject.toml must declare license = { text = "Apache-2.0" }')
    if "License :: OSI Approved :: Apache Software License" not in pyproject:
        raise SystemExit("pyproject.toml must carry the OSI Apache classifier")


def validate_license() -> None:
    license_text = read("LICENSE")
    if "Apache License" not in license_text or "Version 2.0" not in license_text:
        raise SystemExit("LICENSE must contain Apache License 2.0 text")
    notice = read("NOTICE")
    if "MatrixArkAI contributors" not in notice:
        raise SystemExit("NOTICE must include contributor attribution")


def validate_no_tracked_local_codex_config() -> None:
    tracked = repository_files()
    local_codex_files = [path for path in tracked if path == ".codex" or path.startswith(".codex/")]
    if local_codex_files:
        raise SystemExit(
            "tracked local Codex config is not open-source safe: "
            + ", ".join(local_codex_files)
        )


def validate_no_private_paths() -> None:
    tracked = repository_files()
    offenders: list[str] = []
    for relative_path in tracked:
        if PRIVATE_ACCOUNT_MARKER in relative_path.casefold():
            offenders.append("tracked filename contains a private account marker")
        path = ROOT / relative_path
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if PRIVATE_ACCOUNT_MARKER in text.casefold():
            offenders.append(f"{relative_path}: private account marker")
        if relative_path in PRIVATE_PATH_FIXTURE_FILES:
            continue
        for token in PRIVATE_PATH_TOKENS:
            if token in text:
                offenders.append(f"{relative_path}: {token}")
                break
    if offenders:
        raise SystemExit(
            "tracked files contain local/private path markers:\n" + "\n".join(offenders[:50])
        )


def validate_no_enterprise_object_store() -> None:
    """Fail if this repository CONTAINS an object store rather than depending on one.

    The ``matrixobjectstore-rs`` crate is Apache-2.0 open source and public, in
    matrixarkai/MatrixObject, with its own openness gate. Depending on it by public git
    revision is ordinary -- exactly how the cache and consensus crates are taken -- and is
    no longer refused here. The two checks that rejected a dependency were written while
    that crate had no public source, and they would turn this gate red the moment one was
    declared, which is what happened in TemporalStore.

    What is still refused:

    * ``crates/matrixobject/`` tracked here, or a Cargo.toml naming it by path or as a
      workspace member -- vendoring a copy of another repository's crate duplicates its
      source instead of depending on it, which is wrong however open that crate is;
    * a ``src/bin/`` executable that speaks the object-store wire protocol -- that is the
      store itself rather than a client of it; and
    * naming a source file of the NATIVE implementation, which is a separate tree and is
      not public. That rule is unaffected by the Rust crate being open.

    DEPEND versus CONTAIN is the distinction that survives the crate becoming public.
    """
    tracked = repository_files()
    offenders: list[str] = []

    if any(p == "crates/matrixobject" or p.startswith("crates/matrixobject/") for p in tracked):
        offenders.append(
            "crates/matrixobject/ is tracked -- depend on the published crate instead of "
            "vendoring a copy of it here"
        )

    for relative_path in tracked:
        if not relative_path.endswith("Cargo.toml"):
            continue
        path = ROOT / relative_path
        if not path.is_file():
            continue
        for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "crates/matrixobject" in line:
                offenders.append(
                    f"{relative_path}: references crates/matrixobject (workspace member or path dep)"
                )
            # A DEPENDENCY ON THE OBJECT-STORE CRATE IS NO LONGER AN OFFENCE. Two checks
            # here rejected one -- a `matrixobjectstore-rs = ...` line and a
            # `dep:matrixobjectstore` feature entry -- and both were written while that
            # crate had no public source. It is Apache-2.0 and public now, pinned by git
            # revision beside the cache and consensus crates, so those checks only served
            # to turn this gate red when the dependency was declared. What remains refused
            # is CONTAINING the store, checked above and below.

    # A standalone executable that SPEAKS the object-store wire protocol is the store itself,
    # whatever it is named. The sanctioned open-source surface is the feature-gated bridge and
    # its clients -- never a binary that serves objects. This is the hole the 20260817 sync
    # slipped through: the checks above look only for the crate directory and the Cargo
    # dependency, so a src/bin/ server imported clean and shipped for two days.
    for relative_path in tracked:
        if not (relative_path.endswith(".rs") and "/src/bin/" in relative_path):
            continue
        path = ROOT / relative_path
        if not path.is_file():
            continue
        if "MORP1" in path.read_text(encoding="utf-8", errors="replace"):
            offenders.append(
                f"{relative_path}: a src/bin/ executable speaks the object-store wire "
                "protocol -- that is the store itself rather than a client of it"
            )

    # A tracked file that names the enterprise implementation's OWN SOURCE FILES documents that
    # tree inside a public repository, which is the same disclosure as shipping it. The checks above
    # look for the crate, the Cargo dependency and a server binary -- all of them things that COMPILE
    # -- so a script that merely reads those sources passes every one of them. One did, naming three
    # of them by path, until it was removed in the change that added this rule.
    for relative_path in tracked:
        if relative_path in ENTERPRISE_SOURCE_FIXTURE_FILES:
            continue
        path = ROOT / relative_path
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for basename in ENTERPRISE_NATIVE_SOURCES:
            if basename in text:
                offenders.append(
                    f"{relative_path}: names {basename}, a source file of the native "
                    "object store -- that tree is not public and must not be described here"
                )
                break

    if offenders:
        raise SystemExit(
            "this repository must DEPEND on the object store, not CONTAIN it:\n"
            + "\n".join(offenders[:50])
        )


def validate_no_foreign_vocabulary() -> None:
    """Fails if a tracked file names a product, toolchain or internal system.

    Scanning the whole tree rather than a diff, so that a name cannot arrive by
    a route the diff check misses -- a rename, a merge, a file added before the
    check existed.
    """
    tracked = [path for path in repository_files() if path not in FOREIGN_VOCABULARY_FIXTURE_FILES]
    skipped = len(repository_files()) - len(tracked)
    if skipped != len(FOREIGN_VOCABULARY_FIXTURE_FILES):
        # A renamed fixture would silently stop being skipped, or worse, a typo
        # here would skip nothing and the scan would fail on its own patterns.
        raise SystemExit(
            f"expected to skip {len(FOREIGN_VOCABULARY_FIXTURE_FILES)} vocabulary "
            f"fixture file(s), skipped {skipped}"
        )
    if not tracked:
        raise SystemExit("no tracked files to scan for vocabulary")

    offenders: list[str] = []
    for relative_path in tracked:
        path = ROOT / relative_path
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for label, pattern, flags in FOREIGN_VOCABULARY:
            for match in re.finditer(pattern, text, flags):
                line = text.count("\n", 0, match.start()) + 1
                offenders.append(f"{relative_path}:{line}: {label}: {match.group(0)!r}")
                break

    if offenders:
        raise SystemExit(
            "names that must not appear in this repository "
            "(use the project's own vocabulary):\n" + "\n".join(offenders[:50])
        )


def repository_files() -> list[str]:
    try:
        return subprocess.run(
            ["git", "ls-files"],
            cwd=ROOT,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
        ).stdout.splitlines()
    except (FileNotFoundError, subprocess.CalledProcessError):
        files: list[str] = []
        for directory, dirnames, filenames in os.walk(ROOT):
            dirnames[:] = [
                dirname for dirname in dirnames if dirname not in FALLBACK_SCAN_SKIP_DIRS
            ]
            for filename in filenames:
                path = Path(directory) / filename
                files.append(path.relative_to(ROOT).as_posix())
        return sorted(files)


def main() -> int:
    for path in REQUIRED_FILES:
        read(path)
    validate_package_license()
    validate_license()
    validate_no_tracked_local_codex_config()
    validate_no_private_paths()
    validate_no_enterprise_object_store()
    validate_no_foreign_vocabulary()
    require_tokens("README.md", README_TOKENS)
    require_tokens("SECURITY.md", SECURITY_TOKENS)
    require_tokens("CONTRIBUTING.md", CONTRIBUTING_TOKENS)
    require_tokens(".gitignore", IGNORE_TOKENS)
    require_tokens(
        "tools/run_matrixark_context_backfill_ci_gate_ubuntu22.sh",
        BACKFILL_CI_GATE_TOKENS,
    )
    report = {
        "status": "ok",
        "required_files": REQUIRED_FILES,
        "license": "Apache-2.0",
        "open_source_ready": True,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
