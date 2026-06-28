from openRouterFinder.core.graph import (
    Edge,
    Node,
    SearchingNode,
    great_circle_distance_km,
    heuristic_km,
)


def test_great_circle_distance():
    # Distance between Beijing (PEK) and Shanghai (PVG) ~1067 km
    dist = great_circle_distance_km(40.0799, 116.6031, 31.1443, 121.8083)
    assert 1000 < dist < 1200


def test_heuristic_same_point():
    assert heuristic_km(0.0, 0.0, 0.0, 0.0) == 0.0


def test_node_slots():
    n = Node(iid=0, name="TEST", px=30.0, py=120.0)
    assert n.name == "TEST"
    assert n.next_list == []


def test_searching_node_isolation():
    """SearchingNode route_list must not be shared between instances."""
    a = SearchingNode(iid=0, name="A")
    b = SearchingNode(iid=1, name="B")
    a.route_list.append(("E1", "B", 1))
    assert b.route_list == []
    assert a.route_list == [("E1", "B", 1)]


def test_edge_creation():
    e = Edge(nfrom=0, nend=1, name="W56")
    assert e.nfrom == 0
    assert e.nend == 1
