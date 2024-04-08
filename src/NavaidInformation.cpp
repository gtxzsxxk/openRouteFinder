//
// Created by hanyuan on 2024/4/7.
//

#include "NavaidInformation.h"
#include <cstdio>
#include <cmath>
#include <cstring>

NavaidInformation::NavaidInformation(const std::string &Line, int &Failed, bool FromFixes) {
    /* 12  48.364333333   17.198027778     2357    11600    25      0.000  MLC ENRT LZ CMELE (MALACKY) TACAN DME */

    char ICAOBuffer[16];
    char IdentifierBuffer[16];
    char RegionCodeBuffer[16];
    char FullNameBuffer[32];

    memset(ICAOBuffer, 0 ,16);
    memset(IdentifierBuffer, 0, 16);
    memset(RegionCodeBuffer, 0, 16);
    memset(FullNameBuffer, 0, 32);

    if (!FromFixes) {
        int typeCode;
        [[gnu::unused]] char unusedData[16];
        [[gnu::unused]] double unusedClass;

        int result = sscanf(Line.c_str(), "%d %lf %lf %d %d %s %lf %s %s %s %[^\\n]", &typeCode,
                            &Latitude, &Longitude, &Elevation, &Freq, unusedData, &unusedClass, IdentifierBuffer,
                            ICAOBuffer, RegionCodeBuffer, FullNameBuffer);

        if (result != 11) {
            Failed = 1;
        } else {
            Failed = 0;
        }

        Type = (NAVAID_CODE) typeCode;
        Identifier = std::string(IdentifierBuffer);
        ICAO = std::string(ICAOBuffer);
        RegionCode = std::string(RegionCodeBuffer);
        FullName = std::string(FullNameBuffer);
    } else {
        int result = sscanf(Line.c_str(), "%lf %lf %s %s %s %[^\\n]", &Latitude,
                            &Longitude, IdentifierBuffer,
                            ICAOBuffer, RegionCodeBuffer, FullNameBuffer);

        if (result != 6) {
            Failed = 1;
        } else {
            Failed = 0;
        }

        Type = NAVAID_CODE_FIX;
        Identifier = std::string(IdentifierBuffer);
        ICAO = std::string(ICAOBuffer);
        RegionCode = std::string(RegionCodeBuffer);
        FullName = std::string(FullNameBuffer);
    }
}

void NavaidInformation::addAirway(const Airway &airway) const {
    Edges.push_back(airway);
}

std::string NavaidInformation::toUniqueKey(const NavaidInformation &navaidInformation) {
    return navaidInformation.Identifier + " " + navaidInformation.RegionCode;
}

std::string NavaidInformation::toUniqueKey(const NavaidInformation *navaidInformation) {
    return navaidInformation->Identifier + " " + navaidInformation->RegionCode;
}

std::string NavaidInformation::toUniqueKey(const std::string &Identifier, const std::string &RegionCode) {
    return Identifier + " " + RegionCode;
}

const std::string &NavaidInformation::getIdentifier() const {
    return Identifier;
}

const std::string &NavaidInformation::getRegionCode() const {
    return RegionCode;
}


double NavaidInformation::operator*(const NavaidInformation &node) const {
    const auto PI = 3.1415926;
    const auto EARTH_RADIUS = 6378.137;

    auto Rad = [PI](double deg) { return deg * PI / 180.0; };
    auto radLat1 = Rad(Latitude);
    auto radLat2 = Rad(node.Latitude);
    auto a = radLat1 - radLat2;
    auto b = Rad(Longitude) - Rad(node.Longitude);
    auto s = 2 * asin(sqrt(pow(sin(a / 2), 2) + cos(radLat1) * cos(radLat2) * pow(sin(b / 2), 2)));
    s *= EARTH_RADIUS;

    return s;
}

std::vector<Airway> &NavaidInformation::getEdges() {
    return Edges;
}
