//
// Created by hanyuan on 2024/4/8.
//

#include "RouteResult.h"

RouteResult::RouteResult(NavaidCompare *RouteEnd) {
    while (RouteEnd) {
        FullRouteNodes.push_back(*RouteEnd);
        RouteEnd = RouteEnd->ComeFrom;
    }
    std::reverse(FullRouteNodes.begin(), FullRouteNodes.end());
    setPrefixAndEncode("DCT", "");
}

void RouteResult::setPrefixAndEncode(const std::string &StartPrefix, const std::string &EndPrefix) {
    EncodeRouteNodes.clear();

    if (!StartPrefix.empty()) {
        (*FullRouteNodes.begin()).ViaEdge = StartPrefix;
    }

    if (!EndPrefix.empty()) {
        (*(FullRouteNodes.end() - 1)).ViaEdge = EndPrefix;
    }

    std::string LastViaAirway;
    for (long i = FullRouteNodes.size() - 1; i >= 0; i--) {
        if (LastViaAirway != FullRouteNodes[i].ViaEdge) {
            EncodeRouteNodes.push_back(FullRouteNodes[i]);
        }
        LastViaAirway = FullRouteNodes[i].ViaEdge;
    }

    std::reverse(EncodeRouteNodes.begin(), EncodeRouteNodes.end());
}

std::string RouteResult::toString() const {
    std::string Route;
    for (const auto &WayPoint: EncodeRouteNodes) {
        Route += WayPoint.ViaEdge + " " + WayPoint.getIdentifier() + " ";
    }

    return Route;
}

std::ostream &operator<<(std::ostream &Out, const RouteResult &Result) {
    Out << Result.toString() << std::endl;
    return Out;
}
