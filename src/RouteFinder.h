//
// Created by hanyuan on 2024/4/7.
//

#ifndef OPENROUTEFINDER_ROUTEFINDER_H
#define OPENROUTEFINDER_ROUTEFINDER_H

#include "NavaidInformation.h"
#include "NavDataReader.h"
#include <iostream>
#include <map>
#include <string>
#include <vector>
#include <algorithm>

class NavaidCompare : public NavaidInformation {
public:
    double DistanceToStart;
    bool ShortestDiscovered;
    NavaidCompare *ComeFrom = nullptr;
    std::string ViaEdge = "DCT";

    /* Debug Only */
    std::string Path;

    NavaidCompare() = default;

    explicit NavaidCompare(const NavaidInformation &NavInfo) : NavaidInformation(NavInfo) {
        DistanceToStart = 0xffffffff;
        ShortestDiscovered = false;
    }

    bool operator<(const NavaidCompare &NavCmp) const {
        return DistanceToStart > NavCmp.DistanceToStart;
    }

    bool operator()(NavaidCompare *&lhs, NavaidCompare *&rhs) {
        return lhs->DistanceToStart > rhs->DistanceToStart;
    }

    static NavaidCompare *getNavaidCompareFromMap(std::map<std::string, NavaidCompare> &Map, const std::string &Key) {
        if (Map.count(Key)) {
            return &Map[Key];
        }
        return nullptr;
    }
};

class RouteResult {
    std::vector<NavaidCompare> RouteNodes;
public:
    RouteResult(NavaidCompare *RouteEnd) {
        while (RouteEnd) {
            RouteNodes.push_back(*RouteEnd);
            RouteEnd = RouteEnd->ComeFrom;
        }
        std::reverse(RouteNodes.begin(), RouteNodes.end());
        setPrefix("DCT", "");
    }

    void setPrefix(const std::string &StartPrefix, const std::string &EndPrefix) {
        if (!StartPrefix.empty()) {
            (*RouteNodes.begin()).ViaEdge = StartPrefix;
        }

        if (!EndPrefix.empty()) {
            (*(RouteNodes.end() - 1)).ViaEdge = EndPrefix;
        }
    }

    std::string toString() const {
        std::string Route;
        for (const auto &WayPoint: RouteNodes) {
            Route += WayPoint.ViaEdge + " " + WayPoint.getIdentifier() + " ";
        }

        return Route;
    }

    friend std::ostream &operator<<(std::ostream &Out, const RouteResult &Result) {
        Out << Result.toString() << std::endl;
        return Out;
    }
};

class RouteFinder {
    const std::map<std::string, NavaidInformation> &Nodes;
    const NavDataReader &DataReader;

public:

    RouteFinder() = delete;

    explicit RouteFinder(const NavDataReader &Reader) : Nodes(Reader.getNavaids()), DataReader(Reader) {};

    RouteResult calculateShortestRoute(const NavaidInformation &Start,
                                       const NavaidInformation &End,
                                       AIRWAY_TYPE AirwayType = AIRWAY_HIGH);
};


#endif //OPENROUTEFINDER_ROUTEFINDER_H
