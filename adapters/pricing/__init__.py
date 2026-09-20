# -*- coding: utf-8 -*-
"""Pricing hand-off adapters.

``file`` exchanges JSON documents with ``pricing-harness-public`` on disk. There is no
in-process adapter and there cannot be a straightforward one: both repositories use a
top-level package named ``core``, so importing that harness's Python here would collide with
this one (ARCHITECTURE.md section 6).
"""
