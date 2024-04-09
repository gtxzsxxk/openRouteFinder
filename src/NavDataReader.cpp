//
// Created by hanyuan on 2024/4/6.
//

#include "NavDataReader.h"
#include "AirportProcedure.h"
#include <iostream>
#include <chrono>
#include <sstream>

std::string NavDataReader::getFileFullPath(const std::string &RelaPath) {
    return DataPath + RelaPath;
}

NavDataReader::NavDataReader(std::string DataPath) : DataPath(std::move(DataPath)) {
    /* Read Cycle Information */
    std::ifstream input(getFileFullPath(DATA_PATH_CYCLE_INFO), std::ios_base::in);
    if (!input.is_open()) {
        std::cerr << "Failed to open cycle file." << std::endl;
        return;
    }

    std::string buffer;
    std::getline(input, buffer);
    DataProvider = getStringFromRegex(buffer, "^([A-Za-z]*) cycle\\s*:\\s*[0-9]*$");
    DataCycle = getStringFromRegex(buffer, "^AIRAC cycle\\s*:\\s*([0-9]*)$");
    std::getline(input, buffer);
    DataRevision = getStringFromRegex(buffer, "^.*:\\s*(.*)$");
    std::getline(input, buffer);
    DataValidRange = getStringFromRegex(buffer, "^Valid\\s*\\(from/to\\)\\s*:\\s*(.*)$");
    printCycleInformation();
}

void NavDataReader::printCycleInformation() {
    std::cout << "NavData Path: \t" << DataPath << std::endl;
    std::cout << "NavData Type: \t" << DataProvider << std::endl;
    std::cout << "NavData Cycle: \t" << DataCycle << std::endl;
    std::cout << "NavData Revision: \t" << DataRevision << std::endl;
    std::cout << "NavData Valid Range: \t" << DataValidRange << std::endl;
}

std::string NavDataReader::getStringFromRegex(const std::string &Source, const std::string &RegexStr) {
    auto reg = std::regex(RegexStr);
    std::smatch match;
    if (std::regex_search(Source, match, reg) && match.size() >= 2) {
        return match[1];
    }
    return {};
}

void NavDataReader::readNavaids() {
    std::ifstream input(getFileFullPath(DATA_PATH_NAVAIDS), std::ios_base::in);
    if (!input.is_open()) {
        std::cerr << "Failed to open navaid file." << std::endl;
        return;
    }
    Navaids.clear();
    std::cout << "Loading Navaids ..." << std::endl;
    while (!input.eof()) {
        std::string buffer;
        std::getline(input, buffer);
        int failed = 0;
        auto node = NavaidInformation(buffer, failed);
        auto key = NavaidInformation::toUniqueKey(node);
        if (!failed) {
            if (Navaids.count(key)) {
                if (node.getNavaidType() == NAVAID_CODE_LLZ) {
                    Navaids[key] = node;
                }
            } else {
                Navaids[key] = node;
            }
        }
    }
}

void NavDataReader::readAirways() {
    char fromNavaidBuffer[16];
    char toNavaidBuffer[16];
    char fromRegionBuffer[5];
    char toRegionBuffer[5];
    char airwayNameBuffer[128];
    int fromType, toType;
    char direction;
    int airwayType;

    std::ifstream input(getFileFullPath(DATA_PATH_AIRWAY), std::ios_base::in);
    if (!input.is_open()) {
        std::cerr << "Failed to open airway file." << std::endl;
        return;
    }
    std::cout << "Loading Airways ..." << std::endl;
    while (!input.eof()) {
        std::string buffer;
        std::getline(input, buffer);

        auto airway = Airway();

        int result = sscanf(buffer.c_str(), "%s %s %d %s %s %d %c %d %d %d %s", fromNavaidBuffer,
                            fromRegionBuffer, &fromType, toNavaidBuffer, toRegionBuffer,
                            &toType, &direction, &airwayType, &airway.AirwayBaseHeight,
                            &airway.AirwayTopHeight, airwayNameBuffer);

        if (result != 11) {
            continue;
        }

        airway.AirwayType = (AIRWAY_TYPE) airwayType;
        auto airwayStream = std::stringstream(airwayNameBuffer);
        std::string airwayName;
        while (std::getline(airwayStream, airwayName, '-')) {
            airway.Name = airwayName;

            auto *fromNavaid = getNodeFromNavaidsOrFixesCache(fromNavaidBuffer, fromRegionBuffer, fromType);
            auto *toNavaid = getNodeFromNavaidsOrFixesCache(toNavaidBuffer, toRegionBuffer, toType);
            if (!fromNavaid || !toNavaid) {
                std::cerr << "Failed to read airways" << std::endl;
                return;
            }

            if (fromType == NAVAID_CODE_FIX && !Navaids.count(NavaidInformation::toUniqueKey(*fromNavaid))) {
                Navaids[NavaidInformation::toUniqueKey(*fromNavaid)] = *fromNavaid;
            }

            if (toType == NAVAID_CODE_FIX && !Navaids.count(NavaidInformation::toUniqueKey(*toNavaid))) {
                Navaids[NavaidInformation::toUniqueKey(*toNavaid)] = *toNavaid;
            }

            if (direction == 'N') {
                /* 添加顺向的航路 */
                airway.NextNavaidName = std::string(toNavaidBuffer);
                airway.NextNavaidKey = NavaidInformation::toUniqueKey(toNavaidBuffer, toRegionBuffer);
                fromNavaid->addAirway(airway);

                /* 添加反向的航路 */
                auto airwayReversed = airway;
                airwayReversed.NextNavaidName = std::string(fromNavaidBuffer);
                airwayReversed.NextNavaidKey = NavaidInformation::toUniqueKey(fromNavaidBuffer, fromRegionBuffer);
                toNavaid->addAirway(airwayReversed);
            } else if (direction == 'F') {
                /* 添加顺向的航路 */
                airway.NextNavaidName = std::string(toNavaidBuffer);
                airway.NextNavaidKey = NavaidInformation::toUniqueKey(toNavaidBuffer, toRegionBuffer);
                fromNavaid->addAirway(airway);
            } else if (direction == 'B') {
                /* 添加反向的航路 */
                auto airwayReversed = airway;
                airwayReversed.NextNavaidName = std::string(fromNavaidBuffer);
                airwayReversed.NextNavaidKey = NavaidInformation::toUniqueKey(fromNavaidBuffer, fromRegionBuffer);
                toNavaid->addAirway(airwayReversed);
            } else {
                std::cerr << "Airway rule mismatched" << std::endl;
                return;
            }
        }
    }
}

void NavDataReader::cacheFixes() {
    std::ifstream input(getFileFullPath(DATA_PATH_FIXES), std::ios_base::in);
    if (!input.is_open()) {
        std::cerr << "Failed to open fixes file." << std::endl;
        return;
    }
    std::cout << "Caching Fixes ..." << std::endl;
    while (!input.eof()) {
        std::string buffer;
        std::getline(input, buffer);
        double dr_us;
        auto t1 = std::chrono::steady_clock::now();
        auto t2 = std::chrono::steady_clock::now();
        int failed = 0;
        auto node = NavaidInformation(buffer, failed, true);
        if (!failed) {
            FixesCache[NavaidInformation::toUniqueKey(node)] = node;
        }

        dr_us = std::chrono::duration<double, std::micro>(t2 - t1).count();
    }
}

const NavaidInformation *
NavDataReader::getNodeFromNavaidsOrFixesCache(const std::string &Identifier, const std::string &RegionCode,
                                              int NavType) {
    /* 在Navaids找，没有就从缓存里取 */
    const NavaidInformation *desiredNavaid = nullptr;
    auto key = NavaidInformation::toUniqueKey(Identifier, RegionCode);
    if(NavType == NAVAID_DONTCARE) {
        if (Navaids.count(key)) {
            return &Navaids[key];
        }
        if (FixesCache.count(key)) {
            return &FixesCache[key];
        }
        return nullptr;
    }

    if (NavType != NAVAID_CODE_FIX || Navaids.count(key)) {

        if (Navaids.count(key)) {
            desiredNavaid = &Navaids[key];
        } else {
            std::cerr << "Unable to locate Navaid " << Identifier << " @ " << RegionCode << std::endl;
        }
    } else {
        /* 从FIXES缓存里读。不能把FIXES直接全部加入总点集，这只会大大的降低效率。 */
        if (FixesCache.count(key)) {
            desiredNavaid = &FixesCache[key];
        } else {
            std::cerr << "Unable to locate Fixes " << Identifier << " @ " << RegionCode << std::endl;
        }
    }

    return desiredNavaid;
}

const NavaidInformation *
NavDataReader::getNodeFromNavaids(const std::string &Identifier, const std::string &RegionCode) const {
    auto key = NavaidInformation::toUniqueKey(Identifier, RegionCode);
    if (Navaids.count(key)) {
        return &Navaids[key];
    } else {
        std::cerr << "Unable to locate Navaid " << Identifier << " @ " << RegionCode << std::endl;
    }

    return nullptr;
}

const std::map<std::string, NavaidInformation> &NavDataReader::getNavaids() const {
    return Navaids;
}

const NavaidInformation *NavDataReader::getNodeFromNavaids(const NavaidInformation &Node) const {
    auto key = NavaidInformation::toUniqueKey(Node);
    if (Navaids.count(key)) {
        return &Navaids[key];
    } else {
        std::cerr << "Unable to locate Navaid " << Node.getIdentifier() << " @ " << Node.getRegionCode() << std::endl;
    }

    return nullptr;
}

void NavDataReader::readAirportProcedure(const std::string &ICAO) {
    const size_t startIndexSID = 10;
    const size_t startIndexSTAR = 11;
    std::string lastProcedure;
    std::vector<const NavaidInformation*> NodesEachProcedure;
    std::vector<AirportProcedure> procedureVector;

    std::string runway,nodeIdentifier,nodeRegion;

    std::ifstream input(getFileFullPath("CIFP/" + ICAO + ".dat"), std::ios_base::in);
    if (!input.is_open()) {
        std::cerr << "Failed to open Airport Procedure file." << std::endl;
        return;
    }
    std::cout << "Reading airport procedure of " << ICAO << " ..." << std::endl;
    while (!input.eof()) {
        std::string buffer;
        std::getline(input, buffer);
        if (buffer[0] == 'S') {
            if (buffer[1] == 'I') {
                /* SID */
                auto procedure = buffer.substr(startIndexSID, buffer.find(',', startIndexSID) - startIndexSID);

                if(procedure != lastProcedure && !lastProcedure.empty()) {
                    auto procedureObject = AirportProcedure();
                    procedureObject.ProcedureIdentifier = lastProcedure;
                    procedureObject.ProcedureType = AIRPORT_PROCEDURE_SID;
                    procedureObject.Runway = runway;
                    procedureObject.ProcedureNodes = NodesEachProcedure;
                    procedureVector.push_back(procedureObject);
                    NodesEachProcedure.clear();
                    lastProcedure.clear();
                }

                auto runwayMatchPos = startIndexSID + procedure.size() + 1;
                runway = buffer.substr(runwayMatchPos, buffer.find(',', runwayMatchPos) - runwayMatchPos);
                auto nodeMatchPos = runwayMatchPos + runway.size() + 1;
                nodeIdentifier = buffer.substr(nodeMatchPos, buffer.find(',', nodeMatchPos) - nodeMatchPos);
                auto nodeRegionMatchPos = nodeMatchPos + nodeIdentifier.size() + 1;
                nodeRegion = buffer.substr(nodeRegionMatchPos, buffer.find(',', nodeRegionMatchPos) - nodeRegionMatchPos);

                if(nodeIdentifier == " ") {
                    continue;
                }

                auto nodePointer = getNodeFromNavaidsOrFixesCache(nodeIdentifier, nodeRegion, NAVAID_DONTCARE);

                if(procedure == lastProcedure || lastProcedure.empty()) {
                    NodesEachProcedure.push_back(nodePointer);
                }

                lastProcedure = procedure;
            } else if (buffer[1] == 'T') {
                /* STAR */

            }
        } else if (buffer[0] == 'R') {
            /* RWY */
        }
    }
}
