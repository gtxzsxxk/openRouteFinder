#include "NavDataReader.h"
#include "RouteFinder.h"
#include <iostream>
#include <chrono>

int main() {
    auto reader = NavDataReader("../tests/navdata/");
    auto t1 = std::chrono::steady_clock::now();
    reader.readNavaids();
    auto t2 = std::chrono::steady_clock::now();
    auto dr_us = std::chrono::duration<double, std::micro>(t2 - t1).count();

    t1 = std::chrono::steady_clock::now();
    reader.cacheFixes();
    t2 = std::chrono::steady_clock::now();
    dr_us = std::chrono::duration<double, std::micro>(t2 - t1).count();

    t1 = std::chrono::steady_clock::now();
    reader.readAirways();
    t2 = std::chrono::steady_clock::now();
    dr_us = std::chrono::duration<double, std::micro>(t2 - t1).count();

    auto routeFinder = RouteFinder(reader);
    while (1) {
        std::string startIdentifier, startRegionCode;
        std::string endIdentifier, endRegionCode;

        std::cout << "Start Node Identifier: ";
        std::cin >> startIdentifier;
        std::cout << "Start Node Region Code: ";
        std::cin >> startRegionCode;

        std::cout << "End Node Identifier: ";
        std::cin >> endIdentifier;
        std::cout << "End Node Region Code: ";
        std::cin >> endRegionCode;

        t1 = std::chrono::steady_clock::now();
        auto results = routeFinder.calculateShortestRoute(NavaidInformation(startIdentifier, startRegionCode),
                                                          NavaidInformation(endIdentifier, endRegionCode));
        t2 = std::chrono::steady_clock::now();
        std::cout << "Results: " << results;
        dr_us = std::chrono::duration<double, std::milli>(t2 - t1).count();
        std::cout << "Time: " << dr_us << " (ms)" << std::endl;
    }
    return 0;
}
