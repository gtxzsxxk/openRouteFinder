import threading
import time
import RouteFinderLib
import pickle
import socket
import validcode
import random
import config
import traceback
import requests
import json
import metarKeeper


class RouteRequest:
    validnum = 0
    address = None

    def __init__(self, addr):
        self.validnum = random.randint(1000, 9999)
        self.address = addr


requestList = []
threadNumber_statistic = 0
logStringRedirect = ""
visitIpaddr = []  # In fact I never intend to record Ip addr and just do it for PV statistics
visitTime = []
rteGroup = []


def LogPrint(astr, serious=0):
    global logStringRedirect
    if serious > 0:
        logStringRedirect = astr+"\r\n"+logStringRedirect
    print(astr)

# http://whois.pconline.com.cn/ip.jsp?ip=


def IPGET(ip):
    url = "http://whois.pconline.com.cn/ip.jsp?ip="+ip
    r = requests.get(url)
    return r.text


def HttpResponse(sock: socket.socket, dat: str):
    head = "HTTP/1.1 200 OK\r\nContent-Type:text/html\r\nServer: shinoyasan/AirwayRouteFinder\r\nAccess-Control-Allow-Origin: *\r\n\r\n"
    total = head+dat
    sock.send(bytes(total, "utf-8"))


def getHtmlLog():
    global logStringRedirect
    formatStr = "<!DOCTYPE html><html><head><meta http-equiv=\"Content-Type\" content=\"text/html; charset=utf-8\" /></head><body>"
    # </body></html>
    formatStr = formatStr+"<h3>Total Page Visit:" + \
        str(visitIpaddr.__len__())+"</h3>"
    formatStr = formatStr + \
        "<h3>Online Threads(non statistic):" + \
        str(len(threading.enumerate()))+"</h3>"
    formatStr = formatStr+"<hr>"
    index = 0
    for i in visitIpaddr:
        formatStr = formatStr+"<p>"+i+"&nbsp;&nbsp;&nbsp;&nbsp;"+IPGET(i)\
            + "&nbsp;&nbsp;&nbsp;&nbsp;"+visitTime[index]+"</p>"
        index = index+1
    formatStr = formatStr+"<hr>"
    for i in rteGroup:
        formatStr = formatStr+"<p>"+i+"</p>"
    formatStr = formatStr+"<hr>"
    for i in logStringRedirect.split('\r\n'):
        formatStr = formatStr+"<p>"+i+"</p>"
    formatStr = formatStr+"</body></html>"
    return formatStr


class SessionHandler(threading.Thread):
    client_socket = None
    client_addr = None
    thread_num = 0

    def run(self):
        global requestList, threadNumber_statistic, visitIpaddr, rteGroup
        try:
            requestDataBytes = self.client_socket.recv(1024)
            requestData = str(requestDataBytes, "utf-8")
            if requestData.split('\r\n').__len__() < 1:
                return
            if requestData.split('\r\n')[0].split(' ').__len__() < 2:
                return
            requestHead = requestData.split('\r\n')[0].split(' ')[1]
            self.thread_num = len(threading.enumerate())
            if self.client_addr[0] not in visitIpaddr:
                visitIpaddr.append(self.client_addr[0])
                visitTime.append(time.asctime(time.localtime(time.time())))
            LogPrint("线程({},{},开启线程统计{})==用户[{},{}]连接，请求{}   {}".format(self.name, self.thread_num, threadNumber_statistic, self.client_addr[0], self.client_addr[1], requestHead,
                                                                        time.strftime("%m-%d %H:%M:%S", time.localtime())))  # /getRoute?from=ZGHA&to=ZJSY&valid=1111
            command = requestHead.split('?')[0]
            para = ""
            if requestHead.__contains__("?"):
                para = requestHead.split('?')[1]
            if command.__contains__("/getRoute") and para.split('&').__len__() == 3:
                validcodeans = para.split('&')[2].replace("valid=", "")
                hasRequest = False
                remoteInstance = None
                for i in requestList:
                    if i.validnum == int(validcodeans):
                        hasRequest = True
                        remoteInstance = i
                        break

                if hasRequest == True:
                    ORIG = para.split('&')[0].replace("from=", "")
                    DEST = para.split('&')[1].replace("dest=", "")
                    data = SearchRoute(ORIG, DEST)
                    if data == None:
                        HttpResponse(self.client_socket, "无法解析航路或查询的数据不存在。")
                        requestList.remove(remoteInstance)
                    else:
                        touser=json.loads(data)
                        rte = touser["route"]
                        touser["weather"]=[mk.readMetar(ORIG),mk.readMetar(DEST)]
                        if rte not in rteGroup:
                            rteGroup.append(rte)
                        HttpResponse(self.client_socket, json.dumps(touser))
                        requestList.remove(remoteInstance)
                else:
                    HttpResponse(self.client_socket, "No Result.")
            elif command.__contains__("/getImage"):
                requestInstance = RouteRequest(client_address)
                imageBytes = validcode.getImageBytes(requestInstance.validnum)
                self.client_socket.send(
                    bytes("HTTP/1.1 200 OK\r\nContent-Type:image/jpeg\r\n\r\n", "utf-8")+imageBytes)
                requestList.append(requestInstance)
            elif command.__contains__("/getCycle"):
                HttpResponse(self.client_socket, config.NAVDAT_CYCLE)
            elif command.__contains__("/getlog_"+config.BackstageKey):
                HttpResponse(self.client_socket, getHtmlLog())
            elif command.__contains__("/rotaterwy"):
                angle=int(para.replace("angle=",""))
                print("Rotate",angle)
                b64=validcode.RotateImage(angle)
                HttpResponse(self.client_socket, b64)
                #self.client_socket.send(bytes("HTTP/1.1 200 OK\r\nContent-type:image/png\r\n\r\n"+b64, "utf-8"))

            elif command.__contains__("/alldatafile.zip"):
                zipfile = open("static/alldatafile.zip", "rb")
                bytdata = zipfile.read()
                zipfile.close()
                self.client_socket.send(bytes("HTTP/1.1 200 OK\r\nContent-type:application/octet-stream\r\nAccept-Ranges:bytes\r\nAccept-Length:"+str(bytdata.__len__()) +
                                              "\r\nContent-Disposition: attachment; filename=alldatafile.zip\r\n\r\n", "utf-8")+bytdata)

            elif command.__contains__("/favicon.ico"):
                favdat = open("static/favicon.ico", "rb")
                bytdata = favdat.read()
                favdat.close()
                self.client_socket.send(bytes("HTTP/1.1 200 OK\r\nContent-type:application/octet-stream\r\nAccept-Ranges:bytes\r\nAccept-Length:"+str(bytdata.__len__()) +
                                              "\r\nContent-Disposition: attachment; filename=alldatafile.zip\r\n\r\n", "utf-8")+bytdata)
            else:
                # webpagedat
                HttpResponse(self.client_socket, GetWebPageData())

        except Exception as x:
            traceback.print_exc()
            LogPrint("线程({},当前线程数{},开启线程统计{})出错:{} 尝试回收当前线程   {}".format(self.name, self.thread_num, threadNumber_statistic,
                                                                         x, time.strftime("%m-%d %H:%M:%S", time.localtime())), serious=1)  # /getRoute?from=ZGHA&to=ZJSY&valid=1111

        finally:
            self.client_socket.close()
            threadNumber_statistic = threadNumber_statistic-1
            self.thread_num = len(threading.enumerate())
            LogPrint("线程({},当前线程数{},开启线程统计{})退出 线程回收成功   {}".format(self.name, self.thread_num, threadNumber_statistic,
                                                                    time.strftime("%m-%d %H:%M:%S", time.localtime())))  # /getRoute?from=ZGHA&to=ZJSY&valid=1111
            return
        return


def GetWebPageData():
    webfile = open("static/newindex.html", "r", encoding='UTF-8')
    webpagedat = webfile.read()
    webfile.close()

    webpagedat = webpagedat.replace("{{YourBingMapsKey}}", config.YourBingMapsKey)
    return webpagedat

navRTE = open(config.SET_NAVDAT_PATH, "rb")
PerloadNodeList = pickle.load(navRTE)
navRTE.close()

apDat = open(config.SET_APDAT_PATH, "rb")
RouteFinderLib.airport_maps = pickle.load(apDat)
apDat.close()

# searched_icao_DEP=[]
# searched_icao_ARR=[]


def SearchRoute(orig, dest):
    if RouteFinderLib.airport_maps.__contains__(orig) == False or RouteFinderLib.airport_maps.__contains__(dest) == False:
        return None
    objsearch = RouteFinderLib.RTFCALC()
    objsearch.nodeList = PerloadNodeList
    objsearch.startNode = objsearch.ReadSIDAirport(orig)
    objsearch.endNode = objsearch.ReadSTARAirport(dest)
    ans = objsearch.Dijkstra(objsearch.startNode.iid, objsearch.endNode.iid)
    if objsearch.startNode == None or objsearch.endNode == None:
        return None
    del objsearch
    return ans

mk=metarKeeper.metarKeeper()
mk.start()

server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server_socket.bind(("", config.LISTEN_PORT))
server_socket.listen(128)

print("If this is your first start,make sure you have configured 'config.py'")
print("Http Client Started.Visit http://127.0.0.1:%d/ for service."%config.LISTEN_PORT)

while True:
    client_socket, client_address = server_socket.accept()
    #print("[%s, %s]用户连接" % client_address)
    ss = SessionHandler()
    ss.client_addr = client_address
    ss.client_socket = client_socket
    ss.start()
    threadNumber_statistic = threadNumber_statistic+1
