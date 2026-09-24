"""Minimal `approx` so the test suite runs with zero third-party packages.

The tests are still ordinary pytest tests -- pytest collects plain
`test_*` functions without needing to be imported by them -- but they also
run under tests/run_tests.py on a machine with nothing but the standard
library and numpy.  A test suite that cannot be run is not a test suite.
"""


class approx:
    def __init__(self, expected, rel=None, abs=None):
        self.expected = expected
        self.rel = rel
        self.abs = abs

    def _tol(self):
        if self.abs is not None:
            return self.abs
        rel = self.rel if self.rel is not None else 1e-6
        return max(rel * builtins_abs(self.expected), 1e-12)

    def __eq__(self, other):
        return builtins_abs(other - self.expected) <= self._tol()

    def __req__(self, other):
        return self.__eq__(other)

    def __repr__(self):
        return f"approx({self.expected!r}, rel={self.rel}, abs={self.abs})"


builtins_abs = abs
