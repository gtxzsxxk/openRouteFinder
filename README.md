![Airway-Route-Finder](https://socialify.git.ci/gtxzsxxk/Airway-Route-Finder/image?description=1&font=KoHo&forks=1&issues=1&language=1&logo=https%3A%2F%2Fs3.ax1x.com%2F2020%2F12%2F30%2FrX9Ayt.png&owner=1&pattern=Overlapping%20Hexagons&pulls=1&stargazers=1&theme=Light)

<!-- toc -->

# Airway Route Finder (openRouteFinder)

`Airway Route Finder`是一个开源的由`Python`编写的模拟飞行航路查询工具。
本项目依赖于`airbusx_extended_v115_$(navCycle)`导航数据，使用`dijkstra`算法求解两个机场之间的最短航路（尽管它并不一定最优，并且符合真实世界的规则）。

本分支作为默认分支，是稳定的旧版分支，目前正在编写基于`c++`的新版航路查询工具(openRouteFinder)。

## 特性

- 可以静态调用我们对算法的实现，也可以直接提供航路查询的web API
- 提供了前端页面，提供了完整的航路查询网站服务
- **目前唯一的，能够允许用户选择进离场程序的，在线航路查询服务**
- **在我们的前端网页，你可以自由选择进离场程序，并且在地图上规划它们**

## 在线演示

by HKYFLY社区：https://route.hkyfly.com/

## 导航数据的预处理

本项目需要对`aerosoft`提供的导航数据进行预处理。`aerosoft`提供的导航数据是存储在我们的磁盘上，如果直接使用`dijkstra`算法进行查询，
由于涉及到IO读写，效率会非常的低。因此我们需要将存储在文件系统中的航路全部加载进内存，并且将它们进行组织，方便我们算法的处理。将`aerosoft`提供的导航数据
组织为我们的数据结构就是所谓的预处理，是一个比较耗时的过程。预处理过程由`packData.py`完成。

在使用`packData.py`预处理数据前，请先配置好`config.py`，设置好

```
LOCAL_ASDATA_PATH = "USING YOUR OWN"
```

接着，你需要执行`packData.py`
```
$ python3 packData.py
Read Airports' data?(y/n strictly):
```

预处理分为两个部分。第一个部分是预处理机场的数据，第二个部分是预处理全球航路信息。输入小写`y`，就会预处理机场数据，并且把预处理的数据输出到
`airport_$(navCycle).air`。输入小写`n`，就会预处理全球航路信息，并且把数据输出到`navidata_$(navCycle).map`。

需要注意的是，这个预处理可能会花费分钟级别的时间。

## 运行

以下步骤是在浏览器中启动航路查询：

1. 克隆当前分支
2. 配置`config.py`
3. 运行`python3 webFinder.py`，此时你可以在浏览器打开`http://127.0.0.1:9807/`来查询航路
4. 为你的服务配置反向代理（可忽略）

本项目总体上采用前后端分离的思想，后端是由`webFinder.py`提供对网络请求的响应，前端
由`static`目录下的页面来实现与用户的交互。

如果你需要调库，你不想使用web API，请参考`routefinder.py`

## 关于代码的一些解释

代码是本人在高中时期编写的，代码写的比较乱，命名也不规范，很多代码还没来得及格式化，现在也很少有时间再来维护，但是本分支不会放弃维护，仍然欢迎任何形式的贡献。

## 关于

本项目使用十分宽松的`MIT`协议，特此授予任何人免费获得本软件和相关文档文件（“软件”）副本的许可，
不受限制地处理本软件，包括但不限于使用、复制、修改、合并 、发布、分发、再许可的权利。

而且，**你不需要注明作者、来源等信息，你可以自由地使用、修改我的代码**。

## 遇到问题

请直接提issue。
