![Airway-Route-Finder](https://socialify.git.ci/gtxzsxxk/Airway-Route-Finder/image?description=1&font=KoHo&forks=1&issues=1&language=1&logo=https%3A%2F%2Fs3.ax1x.com%2F2020%2F12%2F30%2FrX9Ayt.png&owner=1&pattern=Overlapping%20Hexagons&pulls=1&stargazers=1&theme=Light)
# <center>Airway-Route-Finder</center>
--------------------------------------------
# ~I'm going to rewrite it in golang one day~ Nomore golang I say. I love python. !!!!!!!!!!!!!!
# Airway-Route-Finder
#### 在线演示 by one user : https://route.hkyfly.com/
#### 如何上手急用
1. 克隆当前分支
2. 配置config.py
3. 运行`python3 webFinder.py`
4. 高枕无忧
5. 下面的简介并不适用于当前版本。但上面4步是`TOTALLY RELIABLE`
#### 简介
RouteFinderLib是由Python编写的开源航路查询库。<br>
使用dijkstra算法和aerosoft的导航数据。navRTE_as.dat是预烘焙好的航路数据文件。版本是1805。<br>
RouteFinderLib.py是库的代码。routefinder.py是库的调用demo。packData.py用来烘焙航路数据，便于快速加载图。<br>
使用RouteFinderLib，必须先让RouteFinderLib（以下简称RFL）读取数据。<br>
读取数据可以通过ReadASData()来读取。<br>
读取后的整个图维护在nodeList中，因此在packData.py中，我使用pickle库将nodeList对象序列化到二进制文件navRTE_as.dat中。<br>
所以这个方式，使读取数据快速高效。执行ReadASData函数在我的机器上需要6分钟。<br>
然而读取已经“烘焙”过的navRTE_as.dat文件，只需要几百毫秒。<br>
你可以通过packData.py，随时烘焙更新后的导航数据。<br>
		RFL中dijkstra算法的执行，只需要3步：<br>
		1、使nodeList维护整张图（读取“烘焙”的文件或者从0开始建立图）。<br>
		2、设置RFL内的起始点。<br>
		3、获取起点与中点的IID。<br>
IID是点在nodeList的下标。使用IID表示点是为了迅速的找点。<br>
在dijkstra中寻找点，如果用名称一个一个搜是非常耗时间而且不准确的（有同名冲突点，因此我引入了点的hashcode）。<br>
读出出度指向的下一个点，直接使用IID访问，提高了dijkstra执行效率。<br>
<br>
