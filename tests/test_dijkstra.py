from openRouterFinder.core.graph import Node, Edge
from openRouterFinder.core.airport import AirportConnection
from openRouterFinder.core.dijkstra import RouteEngine


def test_sort_route():
    engine = RouteEngine((), "TEST")
    route_list = [
        ("W56", "P1", 1),
        ("W56", "P2", 2),  # same airway, should merge
        ("A1", "P3", 3),
    ]
    result = engine._sort_route("ORIG", route_list)
    assert result == "ORIG W56 P2 A1 P3"


def test_build_node_info():
    engine = RouteEngine((), "TEST")
    sid = AirportConnection(
        airport_node=Node(iid=-1, name="ORIG", px=30.0, py=120.0),
        connections=[],
        procedures={},
    )
    star = AirportConnection(
        airport_node=Node(iid=-2, name="DEST", px=31.0, py=121.0),
        connections=[],
        procedures={},
    )
    info = engine._build_node_info(sid, star, [("E1", "N1", -2)])
    assert info[0] == ["ORIG", 30.0, 120.0]
    assert info[1] == ["DEST", 31.0, 121.0]


def test_route_engine_search_accepts_constraint_params():
    """RouteEngine.search should accept sid_exit and star_entry without error."""
    from openRouterFinder.core.data_loader import get_nav_graph
    from openRouterFinder.core.airport import AirportConnector

    graph = get_nav_graph()
    connector = AirportConnector(graph.airport_maps, graph._node_index)
    sid_conn = connector.build_sid("ZGHA")
    star_conn = connector.build_star("ZJSY")

    if sid_conn is None or star_conn is None:
        import pytest
        pytest.skip("Need both airports to have data")

    engine = RouteEngine(graph.node_list, graph.data_version)
    result = engine.search(
        "ZGHA", "ZJSY", sid_conn, star_conn,
        connector.get_airport_names("ZGHA") + connector.get_airport_names("ZJSY"),
        sid_exit=None,
        star_entry=None,
    )
    assert result is not None
