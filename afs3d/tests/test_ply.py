import numpy as np

from afs3d.ply import Mesh, read_ply, write_ply


def test_binary_roundtrip(tmp_path):
    rng = np.random.default_rng(0)
    m = Mesh(rng.normal(size=(50, 3)), rng.integers(0, 255, (50, 3)).astype(np.uint8), rng.integers(0, 50, (80, 3)))
    write_ply(tmp_path / "m.ply", m)
    b = read_ply(tmp_path / "m.ply")
    assert np.allclose(b.vertices, m.vertices, atol=1e-5)
    assert (b.colors == m.colors).all() and (b.faces == m.faces).all()


def test_ascii_with_extra_properties(tmp_path):
    txt = """ply
format ascii 1.0
element vertex 3
property float x
property float y
property float z
property float nx
property float ny
property float nz
property uchar red
property uchar green
property uchar blue
element face 1
property list uchar int vertex_indices
end_header
0 0 0 0 0 1 255 0 0
1 0 0 0 0 1 0 255 0
0 1 0 0 0 1 0 0 255
3 0 1 2
"""
    (tmp_path / "a.ply").write_text(txt)
    m = read_ply(tmp_path / "a.ply")
    assert m.vertices.shape == (3, 3) and m.faces.tolist() == [[0, 1, 2]]
    assert m.colors[1].tolist() == [0, 255, 0]
