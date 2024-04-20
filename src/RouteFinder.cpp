//
// Created by hanyuan on 2024/4/7.
//

#include "RouteFinder.h"
#include <queue>
#include <vector>
#include <sstream>

enum HISTORY_DATA_TYPE {
    HISTORY_TYPE_DOUBLE,
    HISTORY_TYPE_BOOL,
    HISTORY_TYPE_POINTER,
    HISTORY_TYPE_STRING,
};

struct WriteHistory {
    void *Pointer;
    HISTORY_DATA_TYPE DataType;
    char Data[16];
};

/* double, bool 类型直接存值，pointer 类型存存导航台地址的地址，这个地址不会悬垂；但是对于字符串类型， */
/* 由于 Data 不是一个 std::string 对象，所以没有办法赋值构造，只能存原来的 c 风格的 string */
template<class T>
static void historyAppend(std::vector<WriteHistory> &History, T *Address) {
    WriteHistory Record{};
    Record.Pointer = Address;
    if constexpr (std::is_same<T, double>::value) {
        Record.DataType = HISTORY_TYPE_DOUBLE;
    } else if constexpr (std::is_same<T, bool>::value) {
        Record.DataType = HISTORY_TYPE_BOOL;
    } else if constexpr (std::is_same<T, NavaidCompare *>::value) {
        Record.DataType = HISTORY_TYPE_POINTER;
    } else if constexpr (std::is_same<T, std::string>::value) {
        Record.DataType = HISTORY_TYPE_STRING;
        auto StringData = *Address;
        auto StorePointer = Record.Data;
        auto Length = StringData.size();
        memcpy(StorePointer, Address->c_str(), Length);
        *(StorePointer + Length) = 0;
        History.push_back(Record);
        return;
    } else {
        throw std::bad_cast();
    }

    auto StorePointer = reinterpret_cast<decltype(Address)>(Record.Data);
    *StorePointer = *Address;
    History.push_back(Record);
}

static void historyRestore(WriteHistory &Record) {
    if (Record.DataType == HISTORY_TYPE_DOUBLE) {
        auto ReadPointer = reinterpret_cast<double *>(Record.Data);
        auto RestorePointer = reinterpret_cast<double *>(Record.Pointer);
        *RestorePointer = *ReadPointer;
    } else if (Record.DataType == HISTORY_TYPE_BOOL) {
        auto ReadPointer = reinterpret_cast<bool *>(Record.Data);
        auto RestorePointer = reinterpret_cast<bool *>(Record.Pointer);
        *RestorePointer = *ReadPointer;
    } else if (Record.DataType == HISTORY_TYPE_POINTER) {
        auto ReadPointer = reinterpret_cast<NavaidCompare **>(Record.Data);
        auto RestorePointer = reinterpret_cast<NavaidCompare **>(Record.Pointer);
        *RestorePointer = *ReadPointer;
    } else if (Record.DataType == HISTORY_TYPE_STRING) {
        auto ReadPointer = reinterpret_cast<char *>(Record.Data);
        auto RestorePointer = reinterpret_cast<std::string *>(Record.Pointer);
        *RestorePointer = std::string(ReadPointer);
    } else {
        throw std::bad_cast();
    }
}

RouteResult
RouteFinder::calculateShortestRoute(const NavaidInformation &Start, const NavaidInformation &End,
                                    AIRWAY_TYPE AirwayType) {

    std::vector<WriteHistory> LocalHistory;

    auto realStartNode = getNavaidFromCacheByKey(Start);
    auto realEndNode = getNavaidFromCacheByKey(End);

    if (!realStartNode) {
        return {realEndNode};
    }

    if (!realEndNode) {
        return {};
    }

    historyAppend(LocalHistory, &realStartNode->DistanceToStart);
    realStartNode->DistanceToStart = 0;

    std::priority_queue<NavaidCompare *, std::vector<NavaidCompare *>, NavaidCompare> q;
    q.push(realStartNode);

    while (!q.empty()) {
        auto currentNode = q.top();
        q.pop();
        if (currentNode->isEqualTo(realEndNode)) {
            break;
        }

        if (currentNode->ShortestDiscovered) {
            continue;
        }
        historyAppend(LocalHistory, &currentNode->ShortestDiscovered);
        currentNode->ShortestDiscovered = true;

        for (const auto &Edge: currentNode->getEdges()) {
            if (Edge.AirwayType != AirwayType && Edge.AirwayType != AIRWAY_DONTCARE) {
                continue;
            }
            auto nextNode = &NavCompareCache[Edge.NextNavaidCacheIndex];
            auto newDistance = (*currentNode) * (*nextNode);
            if (currentNode->DistanceToStart + newDistance < nextNode->DistanceToStart) {
                historyAppend(LocalHistory, &nextNode->DistanceToStart);
                nextNode->DistanceToStart = currentNode->DistanceToStart + newDistance;
                historyAppend(LocalHistory, &nextNode->ComeFrom);
                nextNode->ComeFrom = currentNode;
                historyAppend(LocalHistory, &nextNode->ViaEdge);
                nextNode->ViaEdge = Edge.Name;
                q.push(nextNode);
            }
        }
    }


    auto ResultObject = RouteResult(realEndNode);

    for (long i = LocalHistory.size() - 1; i >= 0; i--) {
        historyRestore(LocalHistory[i]);
    }

    return std::move(ResultObject);
}

RouteFinder::RouteFinder(const NavDataReader &Reader) : DataReader(Reader) {
    int ID = 0;

    std::cout << "RouteFinder: caching data for fast airway indexing ..." << std::endl;

    for (const auto &Element: Reader.getNavaids()) {
        auto NavCompareObject = NavaidCompare(Element.second);
        NavCompareObject.ID = ID++;
        NavCompareSourceData[Element.first] = NavCompareObject;
        NavCompareCache.push_back(NavCompareObject);
    }
    for (auto &Element: NavCompareCache) {
        for (auto &Edge: Element.getEdges()) {
            auto nextNode = NavaidCompare::getNavaidCompareFromMap(NavCompareSourceData, Edge.NextNavaidKey);
            Edge.NextNavaidCacheIndex = nextNode->ID;
        }
    }

    std::cout << "RouteFinder: cache fulfilled ..." << std::endl;
}

NavaidCompare *RouteFinder::getNavaidFromCacheByKey(const std::string &Key) {
    if (NavCompareSourceData.count(Key)) {
        return &NavCompareCache[NavCompareSourceData[Key].ID];
    }
    return nullptr;
}

NavaidCompare *RouteFinder::getNavaidFromCacheByKey(const NavaidInformation &Node) {
    return getNavaidFromCacheByKey(NavaidInformation::toUniqueKey(Node));
}

std::tuple<std::string,
        AirportProcedure, AirportProcedure,
        std::vector<const NavaidInformation *>,
        std::vector<const NavaidInformation *>>
RouteFinder::calculateBetweenAirports(const std::string &Departure, const std::string &Arrival,
                                      std::string SpecifySID, std::string SpecifySTAR) {
    auto sidData = DataReader.readAirportProcedure(Departure);
    auto starData = DataReader.readAirportProcedure(Arrival);

    auto nodeCmp = [](const std::pair<const NavaidInformation *, const AirportProcedure *> &a,
                      const std::pair<const NavaidInformation *, const AirportProcedure *> &b) {
        return a.first < b.first;
    };

    std::set<std::pair<const NavaidInformation *, const AirportProcedure *>, decltype(nodeCmp)> sidNodes(nodeCmp);
    std::set<std::pair<const NavaidInformation *, const AirportProcedure *>, decltype(nodeCmp)> starNodes(nodeCmp);

    for (const auto &procedure: sidData) {
        if (procedure.ProcedureType != AIRPORT_PROCEDURE_SID) {
            continue;
        }

        auto node = procedure.ProcedureNodes[procedure.ProcedureNodes.size() - 1];
        auto pair = std::make_pair(node, &procedure);
        if (!sidNodes.count(pair)) {
            sidNodes.insert(pair);
        }
    }
    for (const auto &procedure: starData) {
        if (procedure.ProcedureType != AIRPORT_PROCEDURE_STAR) {
            continue;
        }

        auto node = procedure.ProcedureNodes[0];
        auto pair = std::make_pair(node, &procedure);
        if (!starNodes.count(pair)) {
            starNodes.insert(pair);
        }
    }

    double minDist = 0xffffffff;
    const NavaidInformation *selectedSidNode;
    const AirportProcedure *selectedSidProcedure;
    const NavaidInformation *selectedStarNode;
    const AirportProcedure *selectedStarProcedure;
    for (const auto &i: sidNodes) {
        for (const auto &j: starNodes) {
            auto dist = *(i.first) * *(j.first);
            if (dist < minDist) {
                minDist = dist;
                selectedSidNode = i.first;
                selectedSidProcedure = i.second;
                selectedStarNode = j.first;
                selectedStarProcedure = j.second;
            }
        }
    }

    if (!SpecifySID.empty()) {
        for (const auto &i: sidNodes) {
            if (i.first->getIdentifier() == SpecifySID) {
                selectedSidNode = i.first;
                selectedSidProcedure = i.second;
            }
        }
    }

    if (!SpecifySTAR.empty()) {
        for (const auto &i: starNodes) {
            if (i.first->getIdentifier() == SpecifySTAR) {
                selectedStarNode = i.first;
                selectedStarProcedure = i.second;
            }
        }
    }

    /* TODO: support return procedure information and runways if specified */
    /* TODO: make it a session */

    auto result = calculateShortestRoute(*selectedSidNode, *selectedStarNode);

    std::vector<const NavaidInformation *> sidNodesVector;
    std::vector<const NavaidInformation *> starNodesVector;
    sidNodesVector.reserve(sidNodes.size());
    starNodesVector.reserve(starNodes.size());
    for (const auto &i: sidNodes) {
        sidNodesVector.push_back(i.first);
    }
    for (const auto &i: starNodes) {
        starNodesVector.push_back(i.first);
    }

    return std::make_tuple(result.toString(Departure, Arrival),
                           *selectedSidProcedure, *selectedStarProcedure, sidNodesVector, starNodesVector);
}
