# -*- coding: utf-8 -*-
"""Client Discovery Harness — core.

Pure logic only: entities, evidence invariants, provider contracts, and the assembly point.
Nothing in this package reads a file, reads an environment variable, opens a socket, or writes
a log line. ``tests/test_core_purity.py`` enforces that, and ``tests/test_core_standalone.py``
checks that the package still works with the adapters and reference app removed.

Read ``HARNESS.md`` before changing anything here.
"""

__version__ = "0.1.0-alpha.1"
