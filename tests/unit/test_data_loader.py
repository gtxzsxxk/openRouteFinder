from openRouterFinder.core.data_loader import NavGraph
from openRouterFinder.core.graph import Node


def test_nav_graph_node_index():
    nodes = [
        Node(iid=0, name="P1", px=30.0, py=120.0),
        Node(iid=1, name="P2", px=31.0, py=121.0),
    ]
    graph = NavGraph(nodes, {}, "TEST")
    found = graph.find_node("P1", 30.0, 120.0)
    assert found is not None
    assert found.iid == 0


def test_nav_graph_immutable():
    nodes = [Node(iid=0, name="P1", px=30.0, py=120.0)]
    graph = NavGraph(nodes, {}, "TEST")
    # node_list should be tuple
    assert isinstance(graph.node_list, tuple)
