/* Native accelerator for the frontier component enumeration.
 *
 * The pure Python reference lives in minesweeper/solver/frontier.py
 * (_enumerate_component).  It walks the search tree at roughly 5 us per node,
 * which is fine for the common case but takes seconds on the rare "one huge
 * connected frontier" position.  The same walk in C++ runs 30-100x faster, so
 * the exact solver can stay exact instead of falling back to the window solver.
 *
 * Exposed function:
 *
 *     enumerate_component(n_cells, positions_flat, offsets, required, limit)
 *         -> (ways, cell_ways, nodes) or None when the node budget is exceeded
 *
 *   positions_flat  flat list of cell indices, one block per constraint
 *   offsets         len(required) + 1, constraint i owns
 *                   positions_flat[offsets[i] : offsets[i + 1]]
 *   required        number of mines each constraint must contain
 *   limit           node budget; None is returned once it is exceeded
 *
 *   ways[k]                 number of legal layouts with exactly k mines
 *   cell_ways[i * (n + 1) + k]
 *                           number of those layouts that place a mine on
 *                           cell i (only cells inside a constraint can be 1)
 *
 * Counts stay exact: they are accumulated in unsigned __int128 (a component
 * never has more than 128 cells, so C(n, k) always fits) and handed to Python
 * as real ints, which keeps the probability arithmetic bit-identical to the
 * pure Python version.
 */

#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <cstdint>
#include <cstring>
#include <string>
#include <vector>

namespace {

/* MSVC has no __int128, and the only operations we need are "add one" and
 * "print as decimal", so a portable 128 bit counter is a few lines.
 * A component never has more than 128 cells: C(n, k) < 2^128 always holds. */
struct Count {
    uint64_t low = 0;
    uint64_t high = 0;

    void inc() { if (++low == 0) ++high; }
};

struct State {
    int n = 0;                       /* cells in the component            */
    int m = 0;                       /* constraints                      */
    std::vector<int> pos_flat;       /* constraint -> cells              */
    std::vector<int> con_start;      /* m + 1                            */
    std::vector<int> required;
    std::vector<int> cell_start;     /* n + 1                            */
    std::vector<int> cell_adj;       /* cell -> constraint ids           */
    std::vector<int8_t> assigned;    /* -1 unknown / 0 safe / 1 mine     */
    std::vector<int> rem;            /* unassigned cells per constraint  */
    std::vector<int> mines;          /* placed mines per constraint      */
    int placed = 0;
    int total = 0;
    long long nodes = 0;
    long long limit = 0;
    bool aborted = false;
    std::vector<Count> ways;         /* n + 1                            */
    std::vector<Count> cell_ways;    /* n * (n + 1)                      */
};

inline bool try_assign(State& s, int cell, int value) {
    const int start = s.cell_start[cell];
    const int stop = s.cell_start[cell + 1];
    for (int k = start; k < stop; ++k) {
        const int c = s.cell_adj[k];
        const int mines = s.mines[c] + value;
        const int rem = s.rem[c] - 1;
        if (mines > s.required[c]) return false;
        if (mines + rem < s.required[c]) return false;
        if (rem == 0 && mines != s.required[c]) return false;
    }
    for (int k = start; k < stop; ++k) {
        const int c = s.cell_adj[k];
        s.mines[c] += value;
        s.rem[c] -= 1;
    }
    s.assigned[cell] = static_cast<int8_t>(value);
    return true;
}

inline void undo_assign(State& s, int cell, int value) {
    s.assigned[cell] = -1;
    for (int k = s.cell_start[cell]; k < s.cell_start[cell + 1]; ++k) {
        const int c = s.cell_adj[k];
        s.mines[c] -= value;
        s.rem[c] += 1;
    }
}

/* Most constrained first: take a cell of the constraint with the fewest
 * undecided cells.  Same heuristic as the Python reference. */
inline int pick(const State& s) {
    int best = -1;
    int best_remaining = 0;
    for (int c = 0; c < s.m; ++c) {
        const int left = s.rem[c];
        if (left == 0) continue;
        if (best < 0 || left < best_remaining) {
            best_remaining = left;
            for (int k = s.con_start[c]; k < s.con_start[c + 1]; ++k) {
                const int cell = s.pos_flat[k];
                if (s.assigned[cell] < 0) {
                    best = cell;
                    break;
                }
            }
            if (best < 0) return -1;
        }
    }
    if (best >= 0) return best;
    /* Cells that no constraint mentions: can happen when the board is
     * inconsistent; treat them as free variables. */
    for (int cell = 0; cell < s.n; ++cell) {
        if (s.assigned[cell] < 0) return cell;
    }
    return -1;
}

void search(State& s) {
    if (s.aborted) return;
    ++s.nodes;
    if (s.nodes > s.limit) {
        s.aborted = true;
        return;
    }
    if (s.placed == s.n) {
        s.ways[s.total].inc();
        const size_t stride = static_cast<size_t>(s.n + 1);
        for (int cell = 0; cell < s.n; ++cell) {
            if (s.assigned[cell] == 1) {
                s.cell_ways[static_cast<size_t>(cell) * stride + s.total].inc();
            }
        }
        return;
    }
    const int cell = pick(s);
    if (cell < 0) return; /* should not happen: placed != n but nothing free */
    for (int value = 1; value >= 0; --value) {
        if (!try_assign(s, cell, value)) continue;
        ++s.placed;
        s.total += value;
        search(s);
        --s.placed;
        s.total -= value;
        undo_assign(s, cell, value);
        if (s.aborted) return;
    }
}

PyObject* count_to_int(Count value) {
    if (value.low == 0 && value.high == 0) return PyLong_FromLong(0);
    /* Four base-2^32 limbs, divided by ten from the most significant end. */
    uint32_t limbs[4] = {
        static_cast<uint32_t>(value.low & 0xffffffffu),
        static_cast<uint32_t>(value.low >> 32),
        static_cast<uint32_t>(value.high & 0xffffffffu),
        static_cast<uint32_t>(value.high >> 32),
    };
    char buffer[48];
    int length = 0;
    bool nonzero = true;
    while (nonzero && length < 47) {
        uint64_t remainder = 0;
        for (int i = 3; i >= 0; --i) {
            const uint64_t current = (remainder << 32) | limbs[i];
            limbs[i] = static_cast<uint32_t>(current / 10);
            remainder = current % 10;
        }
        buffer[length++] = static_cast<char>('0' + static_cast<int>(remainder));
        nonzero = (limbs[0] | limbs[1] | limbs[2] | limbs[3]) != 0;
    }
    for (int i = 0; i < length / 2; ++i) {
        const char tmp = buffer[i];
        buffer[i] = buffer[length - 1 - i];
        buffer[length - 1 - i] = tmp;
    }
    buffer[length] = '\0';
    return PyLong_FromString(buffer, nullptr, 10);
}

bool read_int_list(PyObject* object, std::vector<int>& out) {
    PyObject* fast = PySequence_Fast(object, "expected a sequence of ints");
    if (fast == nullptr) return false;
    const Py_ssize_t size = PySequence_Fast_GET_SIZE(fast);
    out.resize(static_cast<size_t>(size));
    for (Py_ssize_t i = 0; i < size; ++i) {
        const long value = PyLong_AsLong(PySequence_Fast_GET_ITEM(fast, i));
        if (value == -1 && PyErr_Occurred()) {
            Py_DECREF(fast);
            return false;
        }
        out[static_cast<size_t>(i)] = static_cast<int>(value);
    }
    Py_DECREF(fast);
    return true;
}

PyObject* py_enumerate_component(PyObject*, PyObject* args) {
    int n_cells = 0;
    int n_constraints = 0;
    PyObject* positions_obj = nullptr;
    PyObject* offsets_obj = nullptr;
    PyObject* required_obj = nullptr;
    long long limit = 0;
    if (!PyArg_ParseTuple(args, "iiOOOL", &n_cells, &n_constraints, &positions_obj,
                          &offsets_obj, &required_obj, &limit)) {
        return nullptr;
    }
    if (n_cells < 0 || n_constraints < 0) {
        PyErr_SetString(PyExc_ValueError, "negative size");
        return nullptr;
    }

    State s;
    s.n = n_cells;
    s.m = n_constraints;
    s.limit = limit;
    if (!read_int_list(positions_obj, s.pos_flat)) return nullptr;
    if (!read_int_list(offsets_obj, s.con_start)) return nullptr;
    if (!read_int_list(required_obj, s.required)) return nullptr;
    if (static_cast<int>(s.con_start.size()) != n_constraints + 1 ||
        static_cast<int>(s.required.size()) != n_constraints) {
        PyErr_SetString(PyExc_ValueError, "inconsistent constraint arrays");
        return nullptr;
    }

    s.cell_start.assign(static_cast<size_t>(n_cells) + 1, 0);
    for (int c = 0; c < n_constraints; ++c) {
        for (int k = s.con_start[c]; k < s.con_start[c + 1]; ++k) {
            const int cell = s.pos_flat[static_cast<size_t>(k)];
            if (cell < 0 || cell >= n_cells) {
                PyErr_SetString(PyExc_ValueError, "cell index out of range");
                return nullptr;
            }
            s.cell_start[static_cast<size_t>(cell) + 1] += 1;
        }
    }
    for (int cell = 0; cell < n_cells; ++cell) {
        s.cell_start[static_cast<size_t>(cell) + 1] += s.cell_start[static_cast<size_t>(cell)];
    }
    s.cell_adj.assign(s.cell_start.back(), 0);
    {
        std::vector<int> cursor(s.cell_start.begin(), s.cell_start.end() - 1);
        for (int c = 0; c < n_constraints; ++c) {
            for (int k = s.con_start[c]; k < s.con_start[c + 1]; ++k) {
                const int cell = s.pos_flat[static_cast<size_t>(k)];
                s.cell_adj[static_cast<size_t>(cursor[static_cast<size_t>(cell)]++)] = c;
            }
        }
    }

    s.assigned.assign(static_cast<size_t>(n_cells), -1);
    s.rem.resize(static_cast<size_t>(n_constraints));
    s.mines.assign(static_cast<size_t>(n_constraints), 0);
    for (int c = 0; c < n_constraints; ++c) {
        s.rem[static_cast<size_t>(c)] = s.con_start[c + 1] - s.con_start[c];
    }
    s.ways.assign(static_cast<size_t>(n_cells) + 1, Count());
    s.cell_ways.assign(static_cast<size_t>(n_cells) * static_cast<size_t>(n_cells + 1), Count());

    search(s);

    if (s.aborted) {
        Py_RETURN_NONE;
    }

    PyObject* ways = PyList_New(static_cast<Py_ssize_t>(s.n + 1));
    if (ways == nullptr) return nullptr;
    for (int k = 0; k <= s.n; ++k) {
        PyObject* item = count_to_int(s.ways[static_cast<size_t>(k)]);
        if (item == nullptr) {
            Py_DECREF(ways);
            return nullptr;
        }
        PyList_SET_ITEM(ways, k, item);
    }

    PyObject* cell_ways = PyList_New(static_cast<Py_ssize_t>(s.n) * (s.n + 1));
    if (cell_ways == nullptr) {
        Py_DECREF(ways);
        return nullptr;
    }
    const Py_ssize_t total = static_cast<Py_ssize_t>(s.n) * (s.n + 1);
    for (Py_ssize_t i = 0; i < total; ++i) {
        PyObject* item = count_to_int(s.cell_ways[static_cast<size_t>(i)]);
        if (item == nullptr) {
            Py_DECREF(ways);
            Py_DECREF(cell_ways);
            return nullptr;
        }
        PyList_SET_ITEM(cell_ways, i, item);
    }

    PyObject* nodes = PyLong_FromLongLong(s.nodes);
    if (nodes == nullptr) {
        Py_DECREF(ways);
        Py_DECREF(cell_ways);
        return nullptr;
    }
    PyObject* result = PyTuple_Pack(3, ways, cell_ways, nodes);
    Py_DECREF(ways);
    Py_DECREF(cell_ways);
    Py_DECREF(nodes);
    return result;
}

PyMethodDef methods[] = {
    {"enumerate_component", py_enumerate_component, METH_VARARGS,
     "Enumerate one frontier component (see module docstring)."},
    {nullptr, nullptr, 0, nullptr},
};

PyModuleDef module = {
    PyModuleDef_HEAD_INIT,
    "frontier_native",
    "Native accelerator for the minesweeper frontier solver.",
    -1,
    methods,
};

}  // namespace

PyMODINIT_FUNC PyInit_frontier_native(void) {
    return PyModule_Create(&module);
}


