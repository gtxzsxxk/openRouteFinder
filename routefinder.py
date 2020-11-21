import threading
import time
import RouteFinderLib
import pickle
import config

"""
==================
RouteFinderLib的调用Demo
必须先让RouteFinderLib（以下简称RFL）读取数据。
读取数据可以通过ReadASData()来读取。
读取后的整个图维护在nodeList中，因此在packData.py中，我使用pickle库将nodeList对象序列化到二进制文件navRTE_as.dat中。
所以这个方式，使读取数据快速高效。执行ReadASData函数在我的机器上需要6分钟。
然而读取已经“烘焙”过的navRTE_as.dat文件，只需要几百毫秒。
你可以通过packData.py，随时烘焙更新后的导航数据。
RFL中dijkstra算法的执行，只需要3步
1、使nodeList维护整张图（读取“烘焙”的文件或者从0开始建立图）
2、设置RFL内的起始点
3、获取起点与中点的IID
IID是点在nodeList的下标。使用IID表示点是为了迅速的找点。
在dijkstra中寻找点，如果用名称一个一个搜是非常耗时间而且不准确的（有同名冲突点，因此我引入了点的hashcode）
读出出度指向的下一个点，直接使用IID访问，提高了dijkstra执行效率。
"""

navRTE=open(config.SET_NAVDAT_PATH,"rb")
PerloadNodeList=pickle.load(navRTE)
navRTE.close()

apDat=open(config.SET_APDAT_PATH,"rb")
RouteFinderLib.airport_maps=pickle.load(apDat)
apDat.close()

def SearchRoute(orig,dest):
    objsearch=RouteFinderLib.RTFCALC()
    if RouteFinderLib.airport_maps.__contains__(orig)==False or RouteFinderLib.airport_maps.__contains__(dest)==False:
        return None
    objsearch.nodeList=PerloadNodeList
    objsearch.startNode=objsearch.ReadSIDAirport(orig)
    objsearch.endNode=objsearch.ReadSTARAirport(dest)
    ans=objsearch.Dijkstra(objsearch.startNode.iid,objsearch.endNode.iid)
    del objsearch
    return ans

navRTE=open(config.SET_NAVDAT_PATH,"rb")
RouteFinderLib.nodeList=pickle.load(navRTE)
navRTE.close()
while True:
    orig=input("请输入您的起始机场ICAO：")
    dest=input("请输入您的终止机场ICAO：")
    endNode=None
    #orig="ZGHA";dest="ZJSY"
    SearchRoute(orig,dest)