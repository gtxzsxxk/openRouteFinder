//
// Created by hanyuan on 2024/4/7.
//

#include "RouteFinder.h"
#include <queue>
#include <map>
#include <vector>

RouteResult
RouteFinder::calculateShortestRoute(const NavaidInformation &Start, const NavaidInformation &End,
                                    AIRWAY_TYPE AirwayType) {
    /* 对于每一次计算，都需要拷贝Reader读取的点集 */
    std::map<std::string, NavaidCompare> NavCompares;
    for (const auto &Element: Nodes) {
        NavCompares[Element.first] = NavaidCompare(Element.second);
    }

    auto realStartNode = NavaidCompare::getNavaidCompareFromMap(NavCompares, NavaidInformation::toUniqueKey(Start));
    auto realEndNode = NavaidCompare::getNavaidCompareFromMap(NavCompares, NavaidInformation::toUniqueKey(End));

    realStartNode->DistanceToStart = 0;

    std::priority_queue<NavaidCompare *, std::vector<NavaidCompare *>, NavaidCompare> q;
    q.push(realStartNode);

    while (!q.empty()) {
        auto currentNode = q.top();
        q.pop();

        if (NavaidInformation::toUniqueKey(*static_cast<NavaidInformation *>(currentNode)) ==
            NavaidInformation::toUniqueKey(*static_cast<NavaidInformation *>(realEndNode))) {
            break;
        }
        if (currentNode->ShortestDiscovered) {
            continue;
        }
        currentNode->ShortestDiscovered = true;

        for (const auto &Edge: currentNode->getEdges()) {
            if (Edge.AirwayType != AirwayType && Edge.AirwayType != AIRWAY_DONTCARE) {
                continue;
            }
            auto nextNode = NavaidCompare::getNavaidCompareFromMap(NavCompares, Edge.NextNavaidKey);
            auto newDistance = *static_cast<NavaidInformation *>(currentNode) *
                               *static_cast<NavaidInformation *>(nextNode);
            if (currentNode->DistanceToStart + newDistance < nextNode->DistanceToStart) {
                nextNode->DistanceToStart = currentNode->DistanceToStart + newDistance;
                nextNode->ComeFrom = currentNode;
                nextNode->ViaEdge = Edge.Name;
                nextNode->Path = currentNode->Path + Edge.Name + " " + nextNode->getIdentifier() + "\n";
                q.push(nextNode);
            }
        }
    }

    return {realEndNode};
}
