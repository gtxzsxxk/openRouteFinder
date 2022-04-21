import pickle
import RouteFinderLib
import os
import config

mode = input("Read Airports' data?(Y/N):")
cycle = input("Input Data Version:")

if mode == "Y":
    airport_data = {}
    for home, dirs, files in os.walk(os.path.join(config.LOCAL_ASDATA_PATH, "proc")):
        for filename in files:
            print(filename)
            fullpath = os.path.join(home, filename)
            file = open(fullpath, "r")
            airport_data[filename.replace(".txt", "")] = file.read()
            file.close()

    apfile = open(os.path.join(config.LOCAL_ASDATA_PATH, "Airports.txt"), "r")
    airport_data["GLOBAL"] = apfile.readlines()
    apfile.close()

    packedFile = open("airport_"+cycle+".air", "wb")
    pickle.dump(airport_data, packedFile)
    print("数据生成完毕")
    packedFile.close()

else:
    obj = RouteFinderLib.RTFCALC({}, [], None)
    obj.ReadASData(config.LOCAL_ASDATA_PATH)
    print("nodeList占用内存大小："+str(int(obj.nodeList.__sizeof__()/1024))+" KB")
    print("数据读取完毕，开始生成序列化航路文件")
    packedFile = open("navidata_"+cycle+".map", "wb")
    pickle.dump(obj.nodeList, packedFile)
    print("数据生成完毕")
    packedFile.close()

#Automatically update config.py
print('正在更新config.py配置文件')

if mode == 'Y':
    config.SET_APDAT_PATH = "airport_" + cycle + ".air"
else:
    config.SET_NAVDAT_PATH = "navidata_"+ cycle + ".map"

with open(os.path.join(config.LOCAL_ASDATA_PATH ,'Cycle.txt'),'r+') as f:
    config.NAVDAT_CYCLE = f.read()

content = '''# Global Settings.If finished deployments,just reset the items below.
# LOCAL_ASDATA_PATH should be a Navigraph data of Aerosoft.
LOCAL_ASDATA_PATH = "{}"

# Website function settings.
LISTEN_PORT = {}
METAR_UPDATE_MINUTE = {}
YourBingMapsKey = "{}"
BackstageKey = "{}"

# Settings below would be automatically updated after running the packData.py.
# There is no need to manually modify them if they are correct.
SET_NAVDAT_PATH = "{}"
SET_APDAT_PATH = "{}"
NAVDAT_CYCLE = "{}"
'''.format(config.LOCAL_ASDATA_PATH,
           config.LISTEN_PORT,
           config.METAR_UPDATE_MINUTE,
           config.YourBingMapsKey,
           config.BackstageKey,
           config.SET_NAVDAT_PATH,
           config.SET_APDAT_PATH,
           config.NAVDAT_CYCLE)

confFile = open("./config.py","w+")
confFile.write(content)
confFile.close()

print(content)
print('更新成功')

