"""Optional native accelerator for the component enumeration.

The pure Python reference lives in :mod:`minesweeper.solver.frontier`
(``_enumerate_component``).  Building ``frontier_native`` (see ``native/``)
swaps only that inner search for a C++ version; the constraint model, the
total-mine convolution and every probability are still computed in Python, so
the results are bit-identical -- the native module returns exact integers.
"""

from typing import Dict, List, Optional, Sequence, Tuple

try:  # pragma: no cover - the import simply fails when the module was not built
    import frontier_native as _native
except Exception:  # ImportError, but also a broken 32/64-bit .pyd raises OSError
    _native = None


Position = Tuple[int, int]


def available() -> bool:
    """True when the compiled accelerator can be used."""
    return _native is not None


def describe() -> str:
    """Short human readable description, used by the benchmark output and logs."""
    return "native" if _native is not None else "python"


def enumerate_component(cells: Sequence[Position],
                        constraints: Sequence,
                        limit: int) -> Optional[Tuple[Dict[int, int], Dict[Position, Dict[int, int]]]]:
    """Enumerate one component through the native module.

    ``constraints`` are ``frontier.Constraint`` objects (``positions`` and
    ``required`` attributes) expressed in component-local cell indices by this
    function.

    Returns ``(ways, cell_ways)`` exactly like the Python implementation, or
    ``None`` when the node budget was exceeded.  An empty ``ways`` means the
    constraints contradict each other.
    """
    if _native is None:  # pragma: no cover - callers check available() first
        return None

    index = {position: offset for offset, position in enumerate(cells)}
    positions: List[int] = []
    offsets: List[int] = [0]
    required: List[int] = []
    for constraint in constraints:
        for position in constraint.positions:
            positions.append(index[position])
        offsets.append(len(positions))
        required.append(constraint.required)

    outcome = _native.enumerate_component(
        len(cells), len(constraints), positions, offsets, required, limit
    )
    if outcome is None:
        return None

    ways_flat, cell_ways_flat, _nodes = outcome
    ways = {count: ways_flat[count] for count in range(len(ways_flat)) if ways_flat[count]}

    stride = len(cells) + 1
    cell_ways: Dict[Position, Dict[int, int]] = {}
    for offset, position in enumerate(cells):
        base = offset * stride
        counter = {
            count: cell_ways_flat[base + count]
            for count in range(stride)
            if cell_ways_flat[base + count]
        }
        cell_ways[position] = counter
    return ways, cell_ways
