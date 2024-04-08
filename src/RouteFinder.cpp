//
// Created by hanyuan on 2024/4/7.
//

#include "RouteFinder.h"
#include <queue>
#include <vector>

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

template<class T>
static void historyAppend(std::vector<WriteHistory> &History, T *Address) {
    WriteHistory Record{};
    Record.Pointer = Address;
    if (std::is_same<T, double>::value) {
        Record.DataType = HISTORY_TYPE_DOUBLE;
    } else if (std::is_same<T, bool>::value) {
        Record.DataType = HISTORY_TYPE_BOOL;
    } else if (std::is_same<T, NavaidCompare *>::value) {
        Record.DataType = HISTORY_TYPE_POINTER;
    } else {
        throw "No matched history type!";
    }

    auto StorePointer = reinterpret_cast<decltype(Address)>(Record.Data);
    *StorePointer = *Address;
    History.push_back(Record);
}

/* 其它都是传存变量地址的变量的地址，这里直接传字符串的地址 */
static void historyAppend(std::vector<WriteHistory> &History, std::string *Address) {
    WriteHistory Record{};
    Record.Pointer = Address;
    Record.DataType = HISTORY_TYPE_STRING;

    auto StringData = *Address;

    auto StorePointer = reinterpret_cast<char *>(Record.Data);
    auto Length = StringData.size();
    for (auto i = 0; i < Length; i++) {
        *(StorePointer + i) = StringData[i];
    }
    *(StorePointer + Length) = 0;
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
        throw "No matched history type!";
    }
}

RouteResult
RouteFinder::calculateShortestRoute(const NavaidInformation &Start, const NavaidInformation &End,
                                    AIRWAY_TYPE AirwayType) {

    std::vector<WriteHistory> LocalHistory;

    auto &NavCompares = NavCompareSourceData;

    auto realStartNode = NavaidCompare::getNavaidCompareFromMap(NavCompares, NavaidInformation::toUniqueKey(Start));
    auto realEndNode = NavaidCompare::getNavaidCompareFromMap(NavCompares, NavaidInformation::toUniqueKey(End));

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

        if (NavaidInformation::toUniqueKey(*static_cast<NavaidInformation *>(currentNode)) ==
            NavaidInformation::toUniqueKey(*static_cast<NavaidInformation *>(realEndNode))) {
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
            auto nextNode = NavaidCompare::getNavaidCompareFromMap(NavCompares, Edge.NextNavaidKey);
            auto newDistance = *static_cast<NavaidInformation *>(currentNode) *
                               *static_cast<NavaidInformation *>(nextNode);
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
