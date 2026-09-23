"""의존성 없는 최소 PLY 입출력 (정점 xyz/색, 삼각형 면). ASCII / binary_little_endian 지원."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

_PLY_TYPES = {
    "char": "i1", "int8": "i1", "uchar": "u1", "uint8": "u1",
    "short": "i2", "int16": "i2", "ushort": "u2", "uint16": "u2",
    "int": "i4", "int32": "i4", "uint": "u4", "uint32": "u4",
    "float": "f4", "float32": "f4", "double": "f8", "float64": "f8",
}  # fmt: skip


@dataclass
class Mesh:
    vertices: np.ndarray  # (N,3) float64
    colors: np.ndarray | None = None  # (N,3) uint8
    faces: np.ndarray | None = None  # (M,3) int64

    @property
    def n_faces(self) -> int:
        return 0 if self.faces is None else len(self.faces)


def _parse_header(f):
    if f.readline().strip() != b"ply":
        raise ValueError("PLY 파일이 아닙니다")
    fmt, elements = None, []
    while True:
        line = f.readline()
        if not line:
            raise ValueError("PLY 헤더가 끝나지 않았습니다")
        tok = line.decode("ascii", "replace").split()
        if not tok or tok[0] in ("comment", "obj_info"):
            continue
        if tok[0] == "format":
            fmt = tok[1]
        elif tok[0] == "element":
            elements.append({"name": tok[1], "count": int(tok[2]), "props": []})
        elif tok[0] == "property":
            if tok[1] == "list":
                elements[-1]["props"].append(("list", tok[4], _PLY_TYPES[tok[2]], _PLY_TYPES[tok[3]]))
            else:
                elements[-1]["props"].append(("scalar", tok[2], _PLY_TYPES[tok[1]]))
        elif tok[0] == "end_header":
            return fmt, elements


def _read_binary_element(f, el, endian):
    props = el["props"]
    if all(p[0] == "scalar" for p in props):
        dt = np.dtype([(p[1], endian + p[2]) for p in props])
        return np.frombuffer(f.read(dt.itemsize * el["count"]), dtype=dt, count=el["count"])
    # 면 요소: 리스트 길이가 모두 3(삼각형)이라고 가정한 빠른 경로
    fields = []
    for p in props:
        if p[0] == "list":
            fields += [(p[1] + "_n", endian + p[2]), (p[1], endian + p[3], (3,))]
        else:
            fields.append((p[1], endian + p[2]))
    dt = np.dtype(fields)
    data = np.frombuffer(f.read(dt.itemsize * el["count"]), dtype=dt, count=el["count"])
    list_names = [p[1] for p in props if p[0] == "list"]
    if any((data[n + "_n"] != 3).any() for n in list_names):
        raise ValueError("삼각형이 아닌 면이 있습니다 (삼각형 메쉬만 지원)")
    return data


def read_ply(path: str | Path) -> Mesh:
    with open(path, "rb") as f:
        fmt, elements = _parse_header(f)
        tables = {}
        if fmt == "ascii":
            rest = f.read().decode("ascii").split("\n")
            pos = 0
            for el in elements:
                rows = [ln.split() for ln in rest[pos : pos + el["count"]]]
                pos += el["count"]
                tables[el["name"]] = (el, rows)
        elif fmt in ("binary_little_endian", "binary_big_endian"):
            endian = "<" if fmt == "binary_little_endian" else ">"
            for el in elements:
                tables[el["name"]] = (el, _read_binary_element(f, el, endian))
        else:
            raise ValueError(f"지원하지 않는 PLY 형식: {fmt}")

    el, v = tables["vertex"]
    names = [p[1] for p in el["props"]]
    if fmt == "ascii":
        arr = np.array(v, dtype=np.float64).reshape(len(v), -1)
        col = {n: arr[:, i] for i, n in enumerate(names)}
    else:
        col = {n: v[n] for n in names}
    verts = np.stack([col["x"], col["y"], col["z"]], axis=1).astype(np.float64)
    colors = None
    if all(c in col for c in ("red", "green", "blue")):
        colors = np.stack([col["red"], col["green"], col["blue"]], axis=1)
        if colors.dtype.kind == "f" and colors.max() <= 1.0:
            colors = colors * 255
        colors = np.clip(colors, 0, 255).astype(np.uint8)

    faces = None
    if "face" in tables and tables["face"][0]["count"] > 0:
        fel, fdata = tables["face"]
        list_name = next(p[1] for p in fel["props"] if p[0] == "list")
        if fmt == "ascii":
            if any(int(r[0]) != 3 for r in fdata):
                raise ValueError("삼각형이 아닌 면이 있습니다 (삼각형 메쉬만 지원)")
            faces = np.array([r[1:4] for r in fdata], dtype=np.int64)
        else:
            faces = np.asarray(fdata[list_name], dtype=np.int64)
    return Mesh(verts, colors, faces)


def write_ply(path: str | Path, mesh: Mesh) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    n = len(mesh.vertices)
    header = ["ply", "format binary_little_endian 1.0", "comment afs3d", f"element vertex {n}",
              "property float x", "property float y", "property float z"]  # fmt: skip
    vfields = [("x", "<f4"), ("y", "<f4"), ("z", "<f4")]
    if mesh.colors is not None:
        header += ["property uchar red", "property uchar green", "property uchar blue"]
        vfields += [("red", "u1"), ("green", "u1"), ("blue", "u1")]
    if mesh.n_faces:
        header += [f"element face {mesh.n_faces}", "property list uchar int vertex_indices"]
    header.append("end_header")

    vdata = np.empty(n, dtype=vfields)
    vdata["x"], vdata["y"], vdata["z"] = mesh.vertices.T.astype(np.float32)
    if mesh.colors is not None:
        vdata["red"], vdata["green"], vdata["blue"] = mesh.colors.T
    with open(path, "wb") as f:
        f.write(("\n".join(header) + "\n").encode("ascii"))
        f.write(vdata.tobytes())
        if mesh.n_faces:
            fdata = np.empty(mesh.n_faces, dtype=[("n", "u1"), ("v", "<i4", (3,))])
            fdata["n"] = 3
            fdata["v"] = mesh.faces
            f.write(fdata.tobytes())
