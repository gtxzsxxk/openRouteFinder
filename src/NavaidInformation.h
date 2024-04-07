//
// Created by hanyuan on 2024/4/7.
//

#ifndef OPENROUTEFINDER_NAVAIDINFORMATION_H
#define OPENROUTEFINDER_NAVAIDINFORMATION_H

#include <string>

enum NAVAID_CODE {
    NAVAID_CODE_NDB = 2,
    NAVAID_CODE_VOR_VORTAC_VORDME,
    NAVAID_CODE_LLZ,
    NAVAID_CODE_LLZ_LDA_SDF,
    NAVAID_CODE_GS,
    NAVAID_CODE_OM,
    NAVAID_CODE_MM,
    NAVAID_CODE_IM,
    NAVAID_CODE_DME = 12,
    NAVAID_CODE_STANDALONE_DME_OR_NDB
};

enum NAVAID_FREQ_UNIT {
    FREQ_KHZ,
    FREQ_MHZ
};

class NavaidInformation {
    NAVAID_CODE Type;
    double Latitude;
    double Longitude;
    int Elevation;
    int Freq;
    std::string Identifier;
    std::string ICAO;
    std::string RegionCode;
    std::string FullName;
public:
    NavaidInformation(const std::string &Line, int &Failed);
};


#endif //OPENROUTEFINDER_NAVAIDINFORMATION_H
