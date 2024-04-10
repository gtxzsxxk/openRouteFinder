//
// Created by hanyuan on 2024/4/9.
//

#ifndef OPENROUTEFINDER_AIRPORTPROCEDURE_H
#define OPENROUTEFINDER_AIRPORTPROCEDURE_H

#include "NavaidInformation.h"
#include "NavaidCompare.h"
#include "NavDataReader.h"

#include <iostream>
#include <string>
#include <vector>

enum AIRPORT_PROCEDURE_TYPE {
    AIRPORT_PROCEDURE_SID,
    AIRPORT_PROCEDURE_STAR
};

class Runway {
public:
    std::string RunwayName;
    std::string Latitude;
    std::string Longitude;
    int FreqILS;
    std::string Information;
};

class NavDataReader;

class AirportProcedure: public NavaidCompare {
public:
    AirportProcedure() = delete;
    AirportProcedure(const std::string &ICAO);

    std::string ProcedureIdentifier;
    AIRPORT_PROCEDURE_TYPE ProcedureType;
    std::vector<std::string> RunwayNames;
    std::vector<Runway> RunwayVector;
    std::vector<const NavaidInformation *> ProcedureNodes;

    friend std::ostream &operator<<(std::ostream &oStream, const AirportProcedure &Procedure);
};

void AirportProcedureReadSIDSTAR(const std::string &ICAO, const std::string &Line,
                                 std::vector<AirportProcedure> &ProcedureVector,
                                 const NavDataReader &Reader);

void AirportProcedureReadRunways(const std::string &Line,
                                 std::vector<AirportProcedure> &ProcedureVector,
                                 const NavDataReader &Reader);

#endif //OPENROUTEFINDER_AIRPORTPROCEDURE_H
