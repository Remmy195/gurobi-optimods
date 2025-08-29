"""
Contains the plotting API for OPF.

- solution_plot: plot case solution using plotly, highlighting switched off branches
- violation_plot: plot case solution, highlighting violations

"""

import math
import tempfile, os, subprocess
from numbers import Number
from gurobi_optimods.opf import converters, grbgraphical


def solution_plot(
    case,
    coords=None,
    solution,
    width=1200,
    height=900,
    keep_obj=True
):
    """
    Reads the given case and returns a plotly figure object. Ideally the
    solution has been computed by the ``solve_opf`` function.
    Generates coords via Graphviz sfdp if coords is None.

    Parameters
    ----------
    case : dict
        Dictionary holding case data
    coords : dict | None
        Optional {bus_i: (lat, lon)}. If None, will auto-generate.
    solution: dict
        Dictionary holding solution data following the MATPOWER notation as
        returned by the ``solve_opf`` function
    width, height : int
        Figure size in pixels.
    keep_obj : bool
        Whether to keep the "OBJ ..." annotation.
    Returns
    -------
    plotly.graph_objects.Figure
        A plotly figure object displaying the solution. The plot can be
        displaged by calling ``figure.show()``.
    """

    # Populate the alldata dictionary with case data
    alldata = converters.convert_case_to_internal_format(case)

    # Special settings for graphics
    alldata["graphical"] = {}
    alldata["graphical"]["numfeatures"] = 0

    if coords = None:
        coords = _get_coords(case, coords)
    
    # Map given coordinate data to network data
    converters.grbmap_coords_from_dict(alldata, coords)

    # Generate a plotly figure object representing the given solution for the network
    fig = grbgraphical.generate_solution_figure(alldata, solution)

    # copy the objective value
    obj_text = None
    for a in getattr(fig.layout, "annotations", []):
        if isinstance(a.text, str) and a.text.strip().startswith("OBJ"):
            obj_text = a.text.strip()
            break
    _restyle_annotations(fig, obj_text if keep_obj else None)

    # optimize plot
    fig.update_layout(width=width, height=height,
                      margin=dict(l=20, r=20, t=20, b=20),
                      paper_bgcolor="white", plot_bgcolor="white")
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    fig.update_yaxes(scaleanchor="x", scaleratio=1)

    _tune_traces(fig)
    
    return fig


def violation_plot(case, coords, violations):
    """
    Reads the given case and returns a plotly figure object of provided
    violations. Ideally the violations have been computed by the
    ``compute_violations`` function

    Parameters
    ----------
    case : dict
        Dictionary holding case data
    coords : dict
        Dictionary holding bus coordinates
    violations : dict
        Dictionary holding case data following the MATPOWER notation with
        additional violations fields as returned by the ``compute_violations``
        function

    Returns
    -------
    plotly.graph_objects.Figure
        A plotly figure object highlighting violations in the solution. The
        plot can be displaged by calling ``figure.show()``.
    """

    # Populate the alldata dictionary with case data
    alldata = converters.convert_case_to_internal_format(case)

    # Special settings for graphics
    alldata["graphical"] = {}
    alldata["graphical"]["numfeatures"] = 0

    # Map given coordinate data to network data
    converters.grbmap_coords_from_dict(alldata, coords)

    # Generate a plotly figure object representing the given violations for the network
    fig = grbgraphical.generate_violations_figure(alldata, violations)

    return fig




# ---------- coordinate from sfdp----------
def _coords_from_sfdp(case, seed=1234):
    """Return {bus_i: (lat, lon)} using Graphviz sfdp -Tplain."""
    alldata = converters.convert_case_to_internal_format(case)
    IDtoCount = alldata["IDtoCountmap"]                # {bus_i -> count}
    CountToID = {v: k for k, v in IDtoCount.items()}   # {count -> bus_i}

    lines = ["graph G {", 'node [shape=point, height=0, width=0, label=""];']
    for j in range(1, alldata["numbuses"] + 1):
        lines.append(f"  {j};")
    for br in alldata["branches"].values():
        lines.append(f"  {br.count_f} -- {br.count_t};")
    lines.append("}")

    with tempfile.TemporaryDirectory() as td:
        in_path = os.path.join(td, "g.gv")
        with open(in_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        out = subprocess.check_output(
            ["sfdp", "-Tplain", f"-Gseed={seed}", in_path],
            text=True
        )

    x, y = {}, {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[0] == "node":
            name = int(parts[1])
            x[name] = float(parts[2])
            y[name] = float(parts[3])

    minx, miny = min(x.values()), min(y.values())
    coords = {}
    for cnt, X in x.items():
        Y = y[cnt]
        Xn, Yn = (X - minx), (Y - miny)
        bus_i = CountToID[cnt]
        # Optimods expects (lat, lon) but later uses x=lon, y=lat
        coords[bus_i] = (Yn, Xn)
    return coords


def _coords_circle(case):
    """If sfdp is missing we make simple circle layout."""
    alldata = converters.convert_case_to_internal_format(case)
    bus_ids = sorted(alldata["IDtoCountmap"].keys())
    n = len(bus_ids)
    R = 100.0
    coords = {}
    for k, bus in enumerate(bus_ids):
        theta = 2 * math.pi * k / max(1, n)
        x = R * math.cos(theta)
        y = R * math.sin(theta)
        coords[bus] = (y, x)
    return coords


def _get_coords(case, coords):
    if coords is not None:
        return coords
    try:
        return _coords_from_sfdp(case)
    except (FileNotFoundError, subprocess.CalledProcessError):
        return _coords_circle(case)


# ---------- styling helpers ----------
def _restyle_annotations(fig, obj_text=None):
    """Replace existing annotations with a tidy block in paper coords."""
    fig.layout.annotations = ()
    lines = []
    if obj_text:
        lines.append(f"<b>{obj_text}</b>")
        lines.append("")

    # tweak labels as you like
    lines += [
        "No lines turned off",
        "",
        "<b>Bus colors</b>",
        "Black: generation ≤ 75 & load < 50",
        '<span style="color:#1f77b4">Blue</span>: generation ≤ 75 & load ≥ 50',
        '<span style="color:#9467bd">Purple</span>: generation > 75',
        '<span style="color:#ff7f0e">Orange</span>: generation > 150',
        '<span style="color:#d62728">Red</span>: generation > 500',
    ]
    txt = "<br>".join(lines)

    fig.add_annotation(
        xref="paper", yref="paper",
        x=0.02, y=0.98, xanchor="left", yanchor="top",
        text=txt, showarrow=False, align="left",
        bgcolor="rgba(255,255,255,0.90)",
        bordercolor="rgba(0,0,0,0.15)", borderwidth=1, borderpad=6,
        font=dict(size=16, color="black"),
    )


def _tune_traces(fig):
    """Gentle line+marker scaling; robust to scalar/list sizes."""
    for tr in fig.data:
        mode = getattr(tr, "mode", "") or ""

        # Edges (lines)
        if "lines" in mode and hasattr(tr, "line") and hasattr(tr.line, "width"):
            try:
                oldw = float(tr.line.width)
            except Exception:
                oldw = 1.0
            tr.line.width = min(max(0.8, oldw * 1.08), 2.2)

        # Nodes (markers)
        if "markers" in mode and hasattr(tr, "marker") and hasattr(tr.marker, "size"):
            s = tr.marker.size

            def bump(v):
                try:
                    fv = float(v)
                except (TypeError, ValueError):
                    fv = 6.0
                return min(max(6.0, fv * 1.12), 18.0)

            if isinstance(s, (list, tuple)):
                tr.marker.size = [bump(v) for v in s]
            else:
                tr.marker.size = bump(s)
