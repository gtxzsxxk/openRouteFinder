//
// Created by hanyuan on 2024/4/7.
//

#include "RouteFinder.h"
#include <queue>
#include <map>
#include <vector>

class NavaidCompare : public NavaidInformation {
public:
    double DistanceToStart;
    bool Visited;
    NavaidCompare *from = nullptr;
    std::string Path;

    NavaidCompare() = default;

    explicit NavaidCompare(const NavaidInformation &NavInfo) : NavaidInformation(NavInfo) {
        DistanceToStart = 0xffffffff;
        Visited = false;
    }

    bool operator<(const NavaidCompare &NavCmp) const {
        return DistanceToStart > NavCmp.DistanceToStart;
    }

    bool operator()(NavaidCompare * &lhs, NavaidCompare * &rhs) {
        return lhs->DistanceToStart > rhs->DistanceToStart;
    }

    static NavaidCompare *getNavaidCompareFromMap(std::map<std::string, NavaidCompare> &Map, const std::string &Key) {
        if (Map.count(Key)) {
            return &Map[Key];
        }
        return nullptr;
    }
};

std::vector<NavaidInformation>
RouteFinder::calculateShortestRoute(const NavaidInformation &Start, const NavaidInformation &End) {
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
//    for(const auto& Edge : realStartNode->getEdges()) {
//        auto nextNode = NavaidCompare::getNavaidCompareFromMap(NavCompares, Edge.NextNavaidKey);
//        nextNode->DistanceToStart = static_cast<NavaidInformation>(*realStartNode) * static_cast<NavaidInformation>(*nextNode);
//        nextNode->from = realStartNode;
//    }

    std::priority_queue<NavaidCompare *, std::vector<NavaidCompare *>, NavaidCompare> q;
    q.push(realStartNode);

    while (!q.empty()) {
        auto currentNode = q.top();
        q.pop();

        if (currentNode->Visited) {
            continue;
        }
        currentNode->Visited = true;

        for (const auto &Edge: currentNode->getEdges()) {
            if (Edge.AirwayType != AirwayType && Edge.AirwayType != AIRWAY_DONTCARE) {
                continue;
            }
            auto nextNode = NavaidCompare::getNavaidCompareFromMap(NavCompares, Edge.NextNavaidKey);
            auto newDistance = static_cast<NavaidInformation>(*currentNode) * static_cast<NavaidInformation>(*nextNode);
            if (currentNode->DistanceToStart + newDistance < nextNode->DistanceToStart) {
                nextNode->DistanceToStart = currentNode->DistanceToStart + newDistance;
                nextNode->from = currentNode;
                nextNode->Path = currentNode->Path + Edge.Name + " " + nextNode->getIdentifier() + "\n";
                q.push(nextNode);
            }
        }
    }

    return {};
}
