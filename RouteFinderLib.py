import math
import time
import heapq
import config
import json
import os

# IID is the index of the node in nodeList

ASDATA_PATH = config.LOCAL_ASDATA_PATH


class Edge:
    nfrom = 0  # IID
    nend = 0  # IID
    dist = 0
    name = ""
    toinstantnode = None
    color = (0, 0, 0)

    def __init__(self, nodefrom, node_end, name, r, g, b):
        self.nfrom = nodefrom.iid
        self.nend = node_end.iid
        self.name = name
        self.color = (r, g, b)
        # self.toinstantnode = node_end


class Node:
    iid = 0
    name = ""
    px = 0.0
    py = 0.0
    nextList = None

    def __init__(self, name, x, y, objself):
        self.iid = objself.nodeList.__len__()
        self.name = name
        self.px = x
        self.py = y
        self.nextList = []
        self.nextList.clear()

    def gethash(self):
        return CalcNodeHash(self.px, self.py)


def CalcNodeHash(x, y):
    return int(abs(int(x)*int(y)))


class searchingNode:
    # name = 0 fixed
    name = ""
    iid = 0
    route = ""
    dist = 0
    # route = "" fixed
    routelist = []  # (edgename,routename,iid)

    # objself is a RTFCALC object,and name should be a string.I fix this bug.
    def __init__(self, node, objself):
        self.iid = node.iid
        self.name = node.name
        self.route = str(objself.startNode.name)


""" Global Math Methods """
PI = 3.1415926535898
EARTH_RADIUS = 6378.137


def rad(x):
    return x * PI / 180.0


def GetDistance_KM(lat1, lon1, lat2, lon2):
    radLat1 = rad(lat1)
    radLat2 = rad(lat2)
    a = radLat1 - radLat2
    b = rad(lon1) - rad(lon2)
    s = 2 * math.asin(math.sqrt(math.pow(math.sin(a / 2), 2)
                                + math.cos(radLat1) * math.cos(radLat2) * math.pow(math.sin(b / 2), 2)))
    s = s*EARTH_RADIUS
    return s


class RouteInformation:
    total_time = ""
    route = ""
    distance = ""
    # 航点信息：[名称，纬度，经度]
    nodeinformation = []
    # 进离场信息
    DepArrProc = {}
    airportName=[]

    def __init__(self, sttime: str, route: str, dist: str, listobj: list, DepArrProc: dict,airportName:list):
        self.total_time = sttime
        self.route = route
        self.distance = dist
        self.nodeinformation = listobj
        self.DepArrProc = DepArrProc
        self.airportName=airportName

    def GetJSON(self):
        dict_temp = {}
        dict_temp["data_version"]=config.NAVDAT_CYCLE
        dict_temp['total_time'] = self.total_time
        dict_temp['route'] = self.route
        dict_temp['distance'] = self.distance
        dict_temp['nodeinformation'] = self.nodeinformation
        dict_temp['DepArrProc'] = self.DepArrProc
        dict_temp['airportName'] = self.airportName
        return json.dumps(dict_temp)


airport_maps = {}  # {'ICAO':'alldata'}


class RTFCALC:

    nodeList = []
    edgeRGB_dic = {}
    startNode: Node = None
    pstartNode: searchingNode = None

    """
    储存进离场信息。
    {‘进离场点名称':[ '程序名称','使用跑道',['点名称',纬度，经度] ] }
    """
    DepArrProc = {}

    # 机场名称
    airportName=[]

    """ For Data Read Only """
    nodeReadCnt = 0
    edgecnt = 0
    datlen = 0
    """ End Of Data Read """

    # 计算两个点之间的距离，传入的是两个点在nodeList中的下标值
    def CalcDist(self, iid1, iid2):
        nodeinstant1 = self.nodeList[iid1]
        nodeinstant2 = self.nodeList[iid2]
        px1 = nodeinstant1.px
        px2 = nodeinstant2.px
        py1 = nodeinstant1.py
        py2 = nodeinstant2.py
        return GetDistance_KM(px1, py1, px2, py2)

    # 执行Dijkstra函数，计算航路。start是起始点的下标，end同上。
    def Dijkstra(self, start, end):
        timestart = time.time()
        allNodeDist = []
        for i in self.nodeList:
            allNodeDist.append(99999999.9)
        self.pstartNode = searchingNode(self.nodeList[start], self)

        queue = []
        # 优先队列优化dijkstra
        # 在队列内插入起始点
        heapq.heappush(queue, (0.0, id(self.pstartNode), self.pstartNode))
        targetNode = None
        while queue.__len__() != 0:
            currentNode = heapq.heappop(queue)[2]
            tempcurrnode = self.nodeList[currentNode.iid]

            # 如果当前出队列的点是目标点
            if tempcurrnode.iid == end:
                # 添加结果
                if targetNode is None:
                    targetNode = currentNode
                # 判断当前点是否为最优解
                else:
                    if targetNode.dist > currentNode.dist:
                        targetNode = currentNode

            # 访问与这个点连接的其他点，进行遍历操作
            for n in tempcurrnode.nextList:
                # 获得搜索点数据结构对象
                nextNode = searchingNode(self.nodeList[n.nend], self)
                # 添加起点到当前点的航路字符串
                nextNode.route = currentNode.route + \
                    " "+n.name+" "+self.nodeList[n.nend].name
                #       边名                 航点名
                # 复制当前点的路径到这个新点的路径list中
                nextNode.routelist = list(currentNode.routelist)
                # 并添加新点
                nextNode.routelist.append(
                    (n.name, self.nodeList[n.nend].name, n.nend))
                # 计算距离
                nextNode.dist = currentNode.dist + \
                    self.CalcDist(currentNode.iid, self.nodeList[n.nend].iid)
                # 松弛点
                if allNodeDist[nextNode.iid] > nextNode.dist:
                    allNodeDist[nextNode.iid] = nextNode.dist
                    heapq.heappush(
                        queue, (nextNode.dist, id(nextNode), nextNode))
        time_end = time.time()
        # 获取航路计算时间
        time_total = (time_end-timestart)
        sttime = "%.2f" % (time_total)
        print("Dijkstra Function: %s s" % (sttime))
        # 航路计算结果对象
        routeObj = None
        if targetNode is None:
            print("No result.")
            routeObj = RouteInformation(sttime, "No result.", "0.00 km", None)
        else:
            # 航路距离
            distStr = "%.2f km" % targetNode.dist
            # 合并同一条航线上的航点
            routeTotal = self.SortRoute(targetNode.routelist)
            print(routeTotal, targetNode.dist)
            nodesinfor = self.getEveryNodeInforList(targetNode.routelist)
            # 创建查询结果对象
            routeObj = RouteInformation(
                sttime, routeTotal, distStr, nodesinfor, self.DepArrProc,self.airportName)

        # 转化为JSON数据输出
        return routeObj.GetJSON()

    def FindNodeByNAME(self, name, x, y):
        for j in self.nodeList:
            if j.name == name and j.gethash() == CalcNodeHash(x, y):
                return j
        return None

    def FindNodeByNAME_NonHash(self, name):
        ans = []
        for j in self.nodeList:
            if j.name == name:
                ans.append(j)
        return ans

    def getEveryNodeInforList(self, routelist):
        li = [[self.startNode.name, self.startNode.px, self.startNode.py]]
        for i in routelist:
            li.append([self.nodeList[i[2]].name,
                       self.nodeList[i[2]].px, self.nodeList[i[2]].py])
        return li

    def SortRoute(self, routelist):
        stack = []
        for i in routelist:
            if stack.__len__() > 0:
                if stack[stack.__len__()-1][0] == i[0]:
                    stack[stack.__len__()-1] = i
                    continue
            stack.append(i)
        answer = self.startNode.name+" "
        for i in stack:
            answer = answer+i[0]+" "+i[1]+" "
        return answer

    def ReadSIDAirport(self, ICAO):
        ICAO = ICAO.upper()
        datasource = ""
        apdat = ""
        if airport_maps.__len__() == 0:
            file = open(ASDATA_PATH+"\\proc\\"+ICAO+".txt", "r")
            datasource = file.read()
            file.seek(0)
            file.close()
            apfile = open(ASDATA_PATH+"\\Airports.txt", "r")
            apdat = apfile.readlines()
            apfile.close()
        else:
            datasource = airport_maps[ICAO]
            apdat = airport_maps["GLOBAL"]
        apLat = 0.0
        apLon = 0.0
        self.airportName=[]
        for i in apdat:
            if i.__contains__(ICAO):
                self.airportName.append(i.split(',')[2])
                apLat = float(i.split(',')[3])
                apLon = float(i.split(',')[4])
                break

        airport_node = Node(ICAO, apLat, apLon, self)
        dat_per_para = datasource.split('\n\n')
        # print(dat_per_para)
        added_nodes = []
        for i in dat_per_para:
            perline = i.split('\n')
            # print(perline)
            if perline[0].__contains__("SID,"):
                """储存进离场信息。
                {‘进离场点名称':[ '程序名称','使用跑道',['点名称',纬度，经度] ] }
                DepArrProc = {}
                """
                nextName = perline[perline.__len__()-1].split(',')[1]
                lat = float(perline[perline.__len__()-1].split(',')[2])
                lon = float(perline[perline.__len__()-1].split(',')[3])
                # print(nextName)
                tfNode = self.FindNodeByNAME(nextName, lat, lon)
                if not nextName in added_nodes:
                    if tfNode is None:
                        print("机场"+ICAO+"无法添加航点:"+nextName, lat, lon)
                        continue
                    print("机场"+ICAO+"添加航点:"+tfNode.name, lat, lon)
                    airport_node.nextList.append(
                        Edge(airport_node, tfNode, "SID", 0, 0, 0))
                    added_nodes.append(nextName)
                if tfNode is None:
                    print("机场"+ICAO+"无法添加航点,无法读取进离场程序:"+nextName, lat, lon)
                    continue
                tempnodeinfor = []
                for tt in i.split('\n'):
                    if tt.__contains__("CF,") or tt.__contains__("TF,"):
                        tempnodeinfor.append(
                            [tt.split(',')[1], float(tt.split(',')[2]), float(tt.split(',')[3])])
                proc=[perline[0].split(',')[1], perline[0].split(',')[2], tempnodeinfor]
                print("机场"+ICAO+"添加进离场程序:",proc[0])
                if not self.DepArrProc.__contains__(tfNode.name):
                    self.DepArrProc[tfNode.name] = [proc]
                else:
                    if not proc in self.DepArrProc[tfNode.name]:
                        self.DepArrProc[tfNode.name].append(proc)
        self.nodeList.append(airport_node)
        return airport_node

    def ReadSTARAirport(self, ICAO):
        ICAO = ICAO.upper()
        datasource = ""
        apdat = ""
        if airport_maps.__len__() == 0:
            file = open(ASDATA_PATH+"\\proc\\"+ICAO+".txt", "r")
            datasource = file.read()
            file.seek(0)

            file.close()

            apfile = open(ASDATA_PATH+"\\Airports.txt", "r")
            apdat = apfile.readlines()
            apfile.close()
        else:
            datasource = airport_maps[ICAO]
            apdat = airport_maps["GLOBAL"]

        apLat = 0.0
        apLon = 0.0
        for i in apdat:
            if i.__contains__(ICAO):
                self.airportName.append(i.split(',')[2])
                apLat = float(i.split(',')[3])
                apLon = float(i.split(',')[4])
                break

        airport_node = Node(ICAO, apLat, apLon, self)
        dat_per_para = datasource.split('\n\n')
        added_nodes = []
        for i in dat_per_para:
            perline = i.split('\n')
            # print(perline)
            if perline[0].__contains__("STAR,"):
                nextName = perline[1].split(',')[1]
                lat = float(perline[1].split(',')[2])
                lon = float(perline[1].split(',')[3])
                tfNode = self.FindNodeByNAME(nextName, lat, lon)
                if not nextName in added_nodes:
                    if tfNode is None:
                        print("机场"+ICAO+"无法添加航点:"+nextName, lat, lon)
                        continue
                    print("机场"+ICAO+"添加航点:"+tfNode.name, lat, lon)
                    tfNode.nextList.append(
                        Edge(tfNode,airport_node, "STAR", 0, 0, 0))
                    added_nodes.append(nextName)
                if tfNode is None:
                    print("机场"+ICAO+"无法添加航点,无法读取进离场程序:"+nextName, lat, lon)
                    continue
                tempnodeinfor = []
                for tt in i.split('\n'):
                    if tt.__contains__("CF,") or tt.__contains__("TF,"):
                        tempnodeinfor.append(
                            [tt.split(',')[1], float(tt.split(',')[2]), float(tt.split(',')[3])])
                proc=[perline[0].split(',')[1], perline[0].split(',')[2], tempnodeinfor]
                print("机场"+ICAO+"添加进离场程序:",proc[0])
                if not self.DepArrProc.__contains__(tfNode.name):
                    self.DepArrProc[tfNode.name] = [proc]
                else:
                    if not proc in self.DepArrProc[tfNode.name]:
                        self.DepArrProc[tfNode.name].append(proc)
        self.nodeList.append(airport_node)
        return airport_node

    def ReadASData(self):
        file = open(os.path.join(ASDATA_PATH, "ATS.txt"), "r")
        datlines = file.readlines()
        datlen = datlines.__len__()
        nodenamelist = []  # (nodename,hash)
        print("开始读点")
        for i in datlines:
            if i.split(',')[0] == 'S':
                nod1 = Node(i.split(',')[1], float(
                    i.split(',')[2]), float(i.split(',')[3]), self)
                nod2 = Node(i.split(',')[4], float(
                    i.split(',')[5]), float(i.split(',')[6]), self)

                set1 = (nod1.name, CalcNodeHash(nod1.px, nod1.py))
                set2 = (nod2.name, CalcNodeHash(nod2.px, nod2.py))
                if set1 not in nodenamelist:
                    self.nodeList.append(nod1)
                    nodenamelist.append(set1)
                if set2 not in nodenamelist:
                    self.nodeList.append(nod2)
                    nodenamelist.append(set2)
                self.nodeReadCnt = self.nodeReadCnt+1
                if self.nodeReadCnt % 3000 == 0:
                    self.process_bar("输入点集", self.nodeReadCnt/datlen)
        edgename = ""
        print("\r开始读边")
        for i in datlines:
            if i.split(',')[0] == 'A':
                edgename = i.split(',')[1]
                continue
            if i.split(',')[0] == 'S':
                previousNode = self.FindNodeByNAME(i.split(',')[1], float(
                    i.split(',')[2]), float(i.split(',')[3]))
                nextNode = self.FindNodeByNAME(i.split(',')[4], float(
                    i.split(',')[5]), float(i.split(',')[6]))
                previousNode.nextList.append(
                    Edge(previousNode, nextNode, edgename, 0,
                         0, 0))
            self.edgecnt = self.edgecnt+1
            if self.edgecnt % 3000 == 0:
                self.process_bar("计算航路链接", self.edgecnt/datlen)
        file.close()
        print("读入："+str(self.edgecnt)+"条边")

    def process_bar(self, name, percent, total_length=25):
        bar = ''.join(["▮"] * int(percent * total_length)) + ''
        bar = '\r' + '[' + \
            bar.ljust(total_length) + \
            ' {:0>4.1f}%|'.format(percent*100) + '100%,'+name+']'
        print(bar, end='', flush=True)
