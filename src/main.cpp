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
    while (true) {
        std::string departure, arrival, sidChoose, starChoose;

        std::cout << "Departure ICAO: ";
        std::cin >> departure;
        std::cout << "Specify SID (0 to ignore): ";
        std::cin >> sidChoose;

        std::cout << "Arrival ICAO: ";
        std::cin >> arrival;
        std::cout << "Specify STAR (0 to ignore): ";
        std::cin >> starChoose;

        t1 = std::chrono::steady_clock::now();
        auto results = routeFinder.calculateBetweenAirports(departure, arrival, sidChoose, starChoose);
        t2 = std::chrono::steady_clock::now();
        std::cout << "Results: " << std::get<0>(results) << std::endl;
        dr_us = std::chrono::duration<double, std::milli>(t2 - t1).count();
        std::cout << "Time: " << dr_us << " (ms)" << std::endl;
        std::cout << "Possible SID: ";
        for (auto const &sid: std::get<1>(results)) {
            std::cout << sid->getIdentifier() << " ";
        }
        std::cout << std::endl;
        std::cout << "Possible STAR: ";
        for (auto const &star: std::get<2>(results)) {
            std::cout << star->getIdentifier() << " ";
        }
        std::cout << std::endl;
    }
    return 0;
}
