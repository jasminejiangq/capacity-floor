#!/usr/bin/env python3
"""Run the whole test suite without pytest.

    python tests/run_tests.py

Exits non-zero if anything fails, so it works as a CI step.
"""
import importlib.util
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))


def load(path):
    name = os.path.splitext(os.path.basename(path))[0]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def main():
    files = sorted(f for f in os.listdir(HERE)
                   if f.startswith("test_") and f.endswith(".py"))
    passed = failed = 0
    failures = []
    for f in files:
        mod = load(os.path.join(HERE, f))
        names = [n for n in dir(mod) if n.startswith("test_")]
        for n in names:
            fn = getattr(mod, n)
            if not callable(fn):
                continue
            try:
                fn()
                passed += 1
                print(f"  PASS  {f}::{n}")
            except Exception:
                failed += 1
                failures.append((f, n, traceback.format_exc()))
                print(f"  FAIL  {f}::{n}")
    print("-" * 60)
    for f, n, tb in failures:
        print(f"\n=== {f}::{n} ===\n{tb}")
    print(f"{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
