//
// Created by hanyuan on 2024/4/7.
//

#include "NavaidInformation.h"
#include <cstdio>

NavaidInformation::NavaidInformation(const std::string &Line, int &Failed) {
    /* 12  48.364333333   17.198027778     2357    11600    25      0.000  MLC ENRT LZ CMELE (MALACKY) TACAN DME */
    int typeCode;
    [[gnu::unused]] char unusedData[16];
    [[gnu::unused]] double unusedClass;
    char ICAOBuffer[16];
    char IdentifierBuffer[16];
    char RegionCodeBuffer[16];
    char FullNameBuffer[32];

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
}
