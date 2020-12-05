from django.shortcuts import render
from django.http import HttpResponse
import airwayroutefinder.settings
import os
import routefinder.config
import routefinder.validcode
import random
import RouteFinderLib
import pickle

navRTE=open(routefinder.config.SET_NAVDAT_PATH,"rb")
PerloadNodeList=pickle.load(navRTE)
navRTE.close()

apDat=open(routefinder.config.SET_APDAT_PATH,"rb")
RouteFinderLib.airport_maps=pickle.load(apDat)
apDat.close()

# Create your views here.

def favico(request):
    file=open(os.path.join(airwayroutefinder.settings.BASE_DIR,"template/favicon.ico"),"rb")
    bytedata=file.read()
    file.close()
    return HttpResponse(bytedata,content_type='image/jpg')

def index(request):
    context={}
    context["YourBingMapsKey"]=routefinder.config.YourBingMapsKey
    return render(request,"index.html",context)

def getImage(request):
    validnum=random.randint(1111,9999)
    imageBytes=routefinder.validcode.getImageBytes(validnum,\
        os.path.join(airwayroutefinder.settings.BASE_DIR,"routefinder/NotoSansHans-Regular.ttf"))
    request.session['reqInstance']=str(validnum)
    return HttpResponse(imageBytes,content_type="image/jpg")

def getCycle(request):
    return HttpResponse(routefinder.config.NAVDAT_CYCLE)

def getRoute(request,orig,dest,valid):
    if valid!=request.session.get('reqInstance',None):
        return HttpResponse("Auth errs.")
    def SearchRoute(orig,dest):
        if RouteFinderLib.airport_maps.__contains__(orig)==False or RouteFinderLib.airport_maps.__contains__(dest)==False:
            return "查找的机场在本版本数据中不存在。"
        objsearch=RouteFinderLib.RTFCALC()
        objsearch.nodeList=PerloadNodeList
        objsearch.startNode=objsearch.ReadSIDAirport(orig)
        objsearch.endNode=objsearch.ReadSTARAirport(dest)
        ans=objsearch.Dijkstra(objsearch.startNode.iid,objsearch.endNode.iid)
        if objsearch.startNode==None or objsearch.endNode==None:
            return "算法发现Dijkstra丢失起点或终点，无法计算航路。"
        del objsearch
        return ans
    return HttpResponse(SearchRoute(orig,dest))

    
