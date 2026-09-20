# -*- coding: utf-8 -*-
"""Search adapters.

``manual`` returns only material a person supplied, and is the default: it is the honest
choice for a tool whose findings must be traceable, and the only one that works where outbound
web access is not allowed.

``brave`` is the first that reaches an external index. It sends the query to a third party, so
wiring it is a deployment decision rather than a default — see ``docs/privacy.md`` section 4-3.
"""
