//
// Created by hanyuan on 2024/4/9.
//

#ifndef OPENROUTEFINDER_AIRPORTPROCEDURE_H
#define OPENROUTEFINDER_AIRPORTPROCEDURE_H
#include "NavaidInformation.h"

#include <string>
#include <vector>

enum AIRPORT_PROCEDURE_TYPE {
    AIRPORT_PROCEDURE_SID,
    AIRPORT_PROCEDURE_STAR
};

class Runway {
    double Latitude;
    double Longitude;
    int FreqILS;
    int Heading;
    std::string Information;
};

class AirportProcedure {
public:
    std::string ProcedureIdentifier;
    AIRPORT_PROCEDURE_TYPE ProcedureType;
    std::string Runway;
    std::vector<const NavaidInformation*> ProcedureNodes;
};


#endif //OPENROUTEFINDER_AIRPORTPROCEDURE_H
