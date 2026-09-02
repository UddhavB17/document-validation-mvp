"""Document field extraction by family.

Public callers should import ``extract_fields`` from ``services.field_extractor``
(the compatibility facade). Submodules here are internal implementation layers.
"""

from services.extraction.dispatcher import extract_fields

__all__ = ["extract_fields"]
