//
// Created by hanyuan on 2024/4/7.
//

#ifndef OPENROUTEFINDER_ROUTEFINDER_H
#define OPENROUTEFINDER_ROUTEFINDER_H

#include "NavaidInformation.h"
#include "NavaidCompare.h"
#include "NavDataReader.h"
#include "RouteResult.h"
#include <iostream>
#include <map>
#include <set>
#include <string>
#include <vector>
#include <algorithm>

class RouteFinder {
    std::map<std::string, NavaidCompare> NavCompareSourceData;
    std::vector<NavaidCompare> NavCompareCache;
    const NavDataReader &DataReader;

    NavaidCompare *getNavaidFromCacheByKey(const std::string &Key);

    NavaidCompare *getNavaidFromCacheByKey(const NavaidInformation &Node);

public:

    RouteFinder() = delete;

    explicit RouteFinder(const NavDataReader &Reader);

    RouteResult calculateShortestRoute(const NavaidInformation &Start,
                                       const NavaidInformation &End,
                                       AIRWAY_TYPE AirwayType = AIRWAY_HIGH);

    std::tuple<std::string,
            AirportProcedure, AirportProcedure,
            std::vector<const NavaidInformation *>,
            std::vector<const NavaidInformation *>>
    calculateBetweenAirports(const std::string &Departure, const std::string &Arrival,
                             const std::string &SpecifySID, const std::string &SpecifySTAR);
};


#endif //OPENROUTEFINDER_ROUTEFINDER_H
