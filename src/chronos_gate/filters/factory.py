"""Build an OutputFilter from a policy OutputFilterDef."""

from __future__ import annotations

from chronos_gate.errors import PolicyError
from chronos_gate.filters.none_filter import NoneFilter
from chronos_gate.filters.protocol import OutputFilter
from chronos_gate.filters.structural_allowlist import StructuralAllowlistFilter
from chronos_gate.policy.models import OutputFilterDef


def build_filter(definition: OutputFilterDef) -> OutputFilter:
    if definition.type == "none":
        return NoneFilter()
    if definition.type == "structural_allowlist":
        if definition.schemas is None:
            raise PolicyError("structural_allowlist requires schemas")
        return StructuralAllowlistFilter(schemas=dict(definition.schemas))
    raise PolicyError(f"unsupported output filter type: {definition.type!r}")
