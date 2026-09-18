# -*- coding: utf-8 -*-
"""Storage adapters.

``null`` is the default and keeps nothing. ``memory`` keeps data for the life of the process so
one stage can see the previous stage's output. A real database adapter (``sqlite``) arrives in
Phase 8 together with the dashboard that needs to query it.
"""
