//
// Created by hanyuan on 2024/4/9.
//

#include "AirportProcedure.h"
#include <map>
#include <algorithm>

void AirportProcedureReadSIDSTAR(const std::string &ICAO, const std::string &Line,
                                 std::vector<AirportProcedure> &ProcedureVector,
                                 const NavDataReader &Reader) {
    const size_t startIndexSID = 10;
    const size_t startIndexSTAR = 11;

    static std::string runway;
    static std::string nodeIdentifier;
    static std::string nodeRegion;

    static std::string LastProcedure;
    static std::string LastLine;
    static size_t LastIndex;
    static decltype(AirportProcedure::ProcedureType) LastProcedureType;
    static decltype(AirportProcedure::ProcedureNodes) nodesEachProcedure;
    static decltype(AirportProcedure::RunwayNames) runways;

    size_t startIndex;

    if (ICAO == "CLEAR") {
        nodesEachProcedure.clear();
        LastProcedure.clear();
        runways.clear();
        return;
    }

    if (Line[0] == 'S' && Line[1] == 'I') {
        startIndex = startIndexSID;
    } else if (Line[0] == 'S' && Line[1] == 'T') {
        startIndex = startIndexSTAR;
    } else {
        return;
    }

    auto procedure = Line.substr(startIndex, Line.find(',', startIndex) - startIndex);

    if (procedure != LastProcedure && !LastProcedure.empty()) {
        auto procedureObject = AirportProcedure(ICAO);
        procedureObject.ProcedureIdentifier = LastProcedure;
        procedureObject.ProcedureType = LastProcedureType;
        std::sort(runways.begin(), runways.end());
        runways.erase(unique(runways.begin(), runways.end()), runways.end());
        procedureObject.RunwayNames = runways;
        procedureObject.ProcedureNodes = nodesEachProcedure;

        /* Only append if the procedure is RNAV */
        /* TODO: 改为没有点采用非RNAV的策略，如TNCM */
        if(LastLine[LastIndex - 2] != '2') {
            ProcedureVector.push_back(procedureObject);
        }

        nodesEachProcedure.clear();
        LastProcedure.clear();
        LastLine.clear();
        runways.clear();
    }

    if (Line[0] != 'S') {
        return;
    }

    auto runwayMatchPos = startIndex + procedure.size() + 1;
    runway = Line.substr(runwayMatchPos, Line.find(',', runwayMatchPos) - runwayMatchPos);
    auto nodeMatchPos = runwayMatchPos + runway.size() + 1;
    nodeIdentifier = Line.substr(nodeMatchPos, Line.find(',', nodeMatchPos) - nodeMatchPos);
    auto nodeRegionMatchPos = nodeMatchPos + nodeIdentifier.size() + 1;
    nodeRegion = Line.substr(nodeRegionMatchPos, Line.find(',', nodeRegionMatchPos) - nodeRegionMatchPos);

    if (nodeIdentifier == " ") {
        return;
    }

    if (runway != " ") {
        if (runway[runway.size() - 1] == 'B') {
            runway[runway.size() - 1] = 'L';
            runways.push_back(runway);
            runway[runway.size() - 1] = 'R';
            runways.push_back(runway);
        } else {
            runways.push_back(runway);
        }
    }

    auto nodePointer = Reader.getNodeFromNavaidsOrFixesCache(nodeIdentifier, nodeRegion, NAVAID_DONTCARE);

    /* 这里的点不必加入世界地图，因为进离场点一定包含在世界地图 */

    if (procedure == LastProcedure || LastProcedure.empty()) {
        nodesEachProcedure.push_back(nodePointer);
    }

    LastProcedure = procedure;
    LastIndex = startIndex;
    LastLine = Line;
    if (Line[0] == 'S' && Line[1] == 'I') {
        LastProcedureType = AIRPORT_PROCEDURE_SID;
    } else if (Line[0] == 'S' && Line[1] == 'T') {
        LastProcedureType = AIRPORT_PROCEDURE_STAR;
    }
}

void AirportProcedureReadRunways(const std::string &Line,
                                 std::vector<AirportProcedure> &ProcedureVector,
                                 const NavDataReader &Reader) {
    const size_t startIndex = 4;
    static std::map<std::string, std::string> ilsNodeAndRegion;

    if (Line.empty() || Line == "CLEAR") {
        ilsNodeAndRegion.clear();
        return;
    }

    if (Line[0] == 'A') {
        auto ilsNodeCounter = 13;
        auto ilsNodeIndex = 0;
        while (ilsNodeCounter > 0) {
            if (Line[ilsNodeIndex++] == ',') {
                ilsNodeCounter--;
            }
        }
        std::string ilsName;
        while (true) {
            if (Line[ilsNodeIndex] == ',') {
                break;
            }
            ilsName += Line[ilsNodeIndex++];
        }

        if (ilsName.empty() || ilsName == " ") {
            return;
        }

        std::string ilsRegion;
        ilsNodeIndex++;
        while (true) {
            if (Line[ilsNodeIndex] == ',') {
                break;
            }
            ilsRegion += Line[ilsNodeIndex++];
        }
        ilsNodeAndRegion[ilsName] = ilsRegion;
        return;
    }
    if (Line[0] != 'R') {
        return;
    }

    auto runway = Line.substr(startIndex, Line.find(',', startIndex) - startIndex);
    if (runway[runway.size() - 1] == ' ') {
        runway = runway.substr(0, runway.size() - 1);
    }

    std::string runwayILSNode;
    size_t ilsNodeIndex = 0;
    auto counter = 5;
    while (counter > 0) {
        if (Line[ilsNodeIndex++] == ',') {
            counter--;
        }
    }
    while (true) {
        if (Line[ilsNodeIndex] == ',' || Line[ilsNodeIndex] == ' ') {
            break;
        }
        runwayILSNode += Line[ilsNodeIndex++];
    }

    auto runwayObject = Runway();
    runwayObject.RunwayName = runway;

    auto ilsPointer = Reader.getNodeFromNavaidsOrFixesCache(runwayILSNode, ilsNodeAndRegion[runwayILSNode],
                                                            NAVAID_DONTCARE);
    if (ilsPointer) {
        runwayObject.FreqILS = ilsPointer->getFreq();
        runwayObject.Information = ilsPointer->getFullName();
    } else {
        runwayObject.FreqILS = 0;
        runwayObject.Information = "N/A";
    }

    std::string lat, lon;
    auto latlonIndex = 0;
    while (true) {
        if (Line[latlonIndex++] == ';') {
            break;
        }
    }

    while (true) {
        if (Line[latlonIndex] == ',') {
            break;
        }
        lat += Line[latlonIndex++];
    }
    latlonIndex++;
    while (true) {
        if (Line[latlonIndex] == ',') {
            break;
        }
        lon += Line[latlonIndex++];
    }

    runwayObject.Latitude = lat;
    runwayObject.Longitude = lon;

    for (auto &procedure: ProcedureVector) {
        bool needPush = false;
        for (const auto &runwayName: procedure.RunwayNames) {
            if (runwayName == runway) {
                needPush = true;
                break;
            }
        }

        if (needPush) {
            procedure.RunwayVector.push_back(runwayObject);
        }
    }
}

AirportProcedure::AirportProcedure(const std::string &ICAO) {
    Type = NAVAID_DONTCARE;
    Identifier = ICAO;
    this->ICAO = ICAO;
    /* TODO: read airport name here */
    FullName = ICAO;
}

std::ostream &operator<<(std::ostream &oStream, const AirportProcedure &Procedure) {
    oStream << Procedure.ICAO << (Procedure.ProcedureType == AIRPORT_PROCEDURE_SID ? " SID " : " STAR ")
            << "Information" << std::endl;
    oStream << "Name: " << Procedure.ProcedureIdentifier << std::endl;
    oStream << "Runways: " << std::endl;
    for (const auto &runway: Procedure.RunwayVector) {
        oStream << runway.RunwayName << std::endl;
        oStream << "\t" << runway.Latitude << " " << runway.Longitude << std::endl;
        if (Procedure.ProcedureType == AIRPORT_PROCEDURE_STAR) {
            oStream << "\tILS Frequency: " << runway.FreqILS / 100 << "." << runway.FreqILS % 100 << std::endl;
            oStream << "\tInformation: " << runway.Information << std::endl;
        }
    }
    return oStream;
}
