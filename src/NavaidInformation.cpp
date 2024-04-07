//
// Created by hanyuan on 2024/4/7.
//

#include "NavaidInformation.h"
#include <sstream>
#include <regex>
#include <chrono>

NavaidInformation::NavaidInformation(const std::string &Line) {
    /* 12  48.364333333   17.198027778     2357    11600    25      0.000  MLC ENRT LZ CMELE (MALACKY) TACAN DME */
    auto t1=std::chrono::steady_clock::now();
    std::stringstream stream(Line);
    int typeCode;
    [[gnu::unused]] double unusedClass;
    stream >> typeCode;
    Type = (NAVAID_CODE) typeCode;
    stream >> Latitude;
    stream >> Longitude;
    stream >> Elevation;
    stream >> Freq;
    stream >> typeCode;
    stream >> unusedClass;
    stream >> Identifier;
    stream >> ICAO;
    stream >> RegionCode;
    std::getline(stream, FullName);
    auto t2=std::chrono::steady_clock::now();
    auto dr_us=std::chrono::duration<double,std::micro>(t2-t1).count();
}

bool NavaidInformation::validNavaidLine(const std::string &Line) {
    static const std::regex reg(
            R"(^[0-9]+\s*[0-9]+\.*[0-9]+\s*[0-9]+\.*[0-9]+\s*[0-9]+\s*[0-9]+\s*[0-9]+\s*[0-9]+\.*[0-9]+\s*\w+\s*\w+\s*\w+\s*.*$)");
    return std::regex_match(Line, reg);
}
