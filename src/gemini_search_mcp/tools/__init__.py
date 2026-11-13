"""Framework-free tool logic for ``search`` and ``analyze_url`` (ADR 0009).

The ``tools`` layer holds the tool contracts from ADR 0003 and ADR 0004 and the
tool errors from ADR 0007. Per the ADR 0009 import table it may import only the
standard library and the sibling layers ``provider``, ``urlpolicy`` and
``config``; it never imports ``fastmcp``, ``pydantic`` or ``google.genai``.

- :mod:`gemini_search_mcp.tools.errors`: the shared tool error type.
- :mod:`gemini_search_mcp.tools.search`: input/output models, their JSON
  schemas and the domain logic of ``search``.
"""
