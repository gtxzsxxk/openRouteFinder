//
// Created by hanyuan on 2024/4/7.
//

#ifndef OPENROUTEFINDER_ROUTEFINDER_H
#define OPENROUTEFINDER_ROUTEFINDER_H
#include "NavaidInformation.h"
#include "NavDataReader.h"
#include <map>
#include <string>
#include <vector>

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


class RouteFinder {
    const std::map<std::string, NavaidInformation> &Nodes;
    const NavDataReader &DataReader;
    RouteFinder() = default;
public:
    RouteFinder(const NavDataReader &Reader) : Nodes(Reader.getNavaids()), DataReader(Reader) {};

    std::vector<NavaidInformation> calculateShortestRoute(const NavaidInformation & Start, const NavaidInformation & End);
                                       const NavaidInformation &End,
                                       AIRWAY_TYPE AirwayType = AIRWAY_HIGH);
};


#endif //OPENROUTEFINDER_ROUTEFINDER_H
