import os
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent.parent
#Global Settings.If finished deployments,just reset the items below.
SET_NAVDAT_PATH=os.path.join(BASE_DIR,"routefinder/navRTE_as_v110_2006.dat")
SET_APDAT_PATH=os.path.join(BASE_DIR,"routefinder/apData_as_v110_2006.dat")
LOCAL_ASDATA_PATH="E:\\Microsoft Flight Simulator X\\aerosoft\\Airbus X Extended\\Navigraph"
NAVDAT_CYCLE="Aerosoft Airbus Extended v110 2006"

#Website functions.
YourBingMapsKey="Write Your own Key"
BackstageKey="Set your own key"