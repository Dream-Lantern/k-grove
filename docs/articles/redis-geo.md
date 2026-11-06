---
id: redis-geo
title: 第十章 GEO 与地理位置查询
description: "Redis GEO 保存成员位置，并按给定中心和范围检索附近成员。使用时先确定经纬度和单位，再选择范围、排序与返回数量。"
date: '2026-10-25'
updated: '2026-10-28'
category: distributed-systems
type: explanation
tags:
  - redis
draft: false
source:
  kind: study-notes
  note: 个人学习整理；来源、适用版本与验证边界见正文。日期为本站首次发布日期。
collection: redis
series: redis-learning
order: 10
---

# 第十章 GEO 与地理位置查询

查找附近商店时，Redis GEO（Geospatial，地理空间索引）可以保存成员位置，再按中心和范围检索。先确定经纬度和单位，再选择范围、排序与返回数量；它不能直接替代完整 GIS（Geographic Information System，地理信息系统）、道路规划和高精度测距。

以下 `redis` 代码块是可在 `redis-cli` 交互环境输入的 Redis 命令，均未实际运行。坐标和结果是教学示意；假定在独立学习实例上从不存在的 `demo:places` 开始，按顺序执行且无并发修改。实现以 Redis Open Source 7.2.0 为参照；基础 GEO 命令自 3.2.0 起提供，GEOSEARCH / GEOSEARCHSTORE 自 6.2.0 起提供。

## 1. 经纬度顺序与单位

新增示例坐标是教学数据，不代表实际用户位置；未运行：

```redis
GEOADD demo:places 116.40 39.90 place-a 116.42 39.91 place-b
GEOPOS demo:places place-a place-b
GEODIST demo:places place-a place-b km
```

GEOADD 参数按经度、纬度排列；GEOPOS 与 GEODIST 通过键名定位索引，再指定成员。解释距离时同时记录单位，区分米与千米。

预期 GEOADD 返回新增成员数 `2`，GEOPOS 返回两个成员的坐标，GEODIST 返回以 km 为单位的近似距离。坐标经过编码，读回值可能与输入有细微差异；本次未测量，不给出虚构的小数结果。[GEOPOS](https://redis.io/docs/latest/commands/geopos/) · [GEODIST](https://redis.io/docs/latest/commands/geodist/)

GEOADD 接受经度 `[-180, 180]`、纬度 `[-85.05112878, 85.05112878]`；纬度不是一般地理意义下的完整 ±90°。越界会报错，不能把任意平面坐标直接当经纬度。参数先经度、后纬度；返回距离也不是实际道路通行距离。[GEOADD 坐标范围](https://redis.io/docs/latest/commands/geoadd/)

Redis GEO 使用 Haversine Formula（半正矢公式）计算球面上的距离近似。地球并非完美球体，编码也有精度限制；结果接近地理直线距离，不包含道路、绕行和交通条件，不应直接用于精确导航或收费里程计算。[GEOADD 距离模型说明](https://redis.io/docs/latest/commands/geoadd/)

## 2. Redis 6.2+ 的 GEOSEARCH

Redis Open Source 6.2.0 起的 GEOSEARCH 可以分别选择查询中心和范围形状：

| 参数       | 含义与用途                             |
| ---------- | -------------------------------------- |
| FROMMEMBER | 用已有成员的位置作中心，适合“店铺周边” |
| FROMLONLAT | 用指定经纬度作中心，适合实时用户位置   |
| BYRADIUS   | 圆形范围，参数是半径                   |
| BYBOX      | 矩形范围，参数依次是宽度、高度         |

查询先根据中心和形状确定覆盖网格，再从有序索引的相应分数区间取候选，最后按真实坐标与范围条件过滤；不是把编码前缀匹配结果直接作为精确命中。旧 GEORADIUS 系列可作为历史接口认识。[GEOSEARCH 参数](https://redis.io/docs/latest/commands/geosearch/) · [7.2.0 搜索实现](https://raw.githubusercontent.com/redis/redis/7.2.0/src/geo.c)

```redis
GEOSEARCH demo:places FROMMEMBER place-a BYRADIUS 5 km ASC COUNT 10 WITHDIST
GEOSEARCH demo:places FROMLONLAT 116.40 39.90 BYRADIUS 5 km ASC WITHDIST
GEOSEARCH demo:places FROMLONLAT 116.40 39.90 BYBOX 5 3 km ASC WITHCOORD
```

接续本节初始化，前两条查询五千米半径内的成员；第三条查询宽五千米、高三千米的矩形。示例两点都在这些范围内，预期返回 place-a、place-b；ASC 按距离从近到远，DESC 则从远到近，WITHDIST 附带所选单位的距离，WITHCOORD 附带坐标。没有实测距离或坐标输出。

```redis
GEOSEARCH demo:places FROMLONLAT 116.40 39.90 BYRADIUS 5 km COUNT 10
GEOSEARCH demo:places FROMLONLAT 116.40 39.90 BYRADIUS 5 km ASC COUNT 10
GEOSEARCH demo:places FROMLONLAT 116.40 39.90 BYRADIUS 5 km COUNT 10 ANY
```

三条都最多返回 10 个成员，现有数据只有两点，不会凭空凑满 10 个。COUNT 限制返回数量，不保证只扫描这么多候选。以 7.2.0 为准，不带 ANY 且省略排序的 COUNT 会按 ASC 选最近结果，所以前两条在此规则下等价；ANY 允许找到足够结果后提前停止，可能减少搜索工作，但不保证全局最近。ANY 可与排序选项组合；7.2.0 会对提前找到的结果再排序，仍不能恢复全局最优保证。要分别判断返回数量、候选扫描量和排序要求。[官方 COUNT ANY 语义](https://redis.io/docs/latest/commands/geosearch/) · [7.2.0 提前停止与排序](https://raw.githubusercontent.com/redis/redis/7.2.0/src/geo.c)

GEOSEARCHSTORE 把结果写入目标有序集合。下面是单行 Redis 命令，不使用 Shell 的反斜杠续行：

```redis
GEOSEARCHSTORE demo:nearby demo:places FROMLONLAT 116.40 39.90 BYRADIUS 5 km ASC COUNT 10 STOREDIST
```

第一个键是目标、第二个是源。示例预期写入两个成员并返回 `2`，源 `demo:places` 不变；目标已存在会被结果覆盖，没有匹配结果时旧目标会被删除。默认保存地理编码 score；STOREDIST 改为保存距查询中心的距离，本例单位为 km，因此这个结果不能再当作原 GEO 索引使用。目标与源设为同一个键也会覆盖源，应避免误用。Cluster 部署还要求两键同槽，本节键名示例仅供独立实例使用。[GEOSEARCHSTORE](https://redis.io/docs/latest/commands/geosearchstore/) · [7.2.0 目标覆盖实现](https://raw.githubusercontent.com/redis/redis/7.2.0/src/geo.c)

## 3. 有序集合索引、位置编码与成员删除 {#_3-底层与删除}

GEO 基于 Sorted Set（有序集合，Zset），不是另造一套完全独立的底层结构。Geohash（地理哈希）通过反复划分经纬度范围、交错两维的比特，把二维网格映射成一维编码。Redis 使用 52-bit（二进制位）编码值作为 score（分数），名称作为 member（成员），因此能复用 Zset 的排序与分数范围检索能力：

```text
经度、纬度 → 范围划分与比特交错 → 52-bit 地理编码
           → Zset score + member（地点名称）
```

编码顺序有助于定位候选网格，不等于距离顺序；查询还要检查邻近网格并过滤。52-bit 整数可由 Zset 的双精度 score 精确保存，基础见 [第 7 章：Sorted Set](/articles/redis-sorted-sets.html)。ZREM 能删除 GEO 成员，正因为它操作的是这个有序集合；随意用 ZADD 改 score 会破坏位置编码的含义。[GEOADD 存储原理](https://redis.io/docs/latest/commands/geoadd/) · [7.2.0 编码写入](https://raw.githubusercontent.com/redis/redis/7.2.0/src/geo.c)

GEOHASH 返回标准的 11 字符 Geohash 编码字符串，不是 Zset 对象，也不能把它等同于内部 52-bit 数值的直接文本形式。Geohash 长度通常越长，所指网格越小；该命令本身并不提供自定义长度选项。相邻网格可能跨越编码前缀边界，位置接近不保证前缀相同，不能仅按字符串前缀判断精确距离。[GEOHASH](https://redis.io/docs/latest/commands/geohash/)

## 4. 一个键的容量与热点

把全国所有动态位置放进一个键，可能带来大量更新与范围查询工作，也让 Cluster 无法把该键内部成员直接拆分。

按城市或区域分桶可以分散负载，但也需要处理边界查询与跨桶聚合。分桶范围应根据实际查询模式确定，不能机械地按行政区切分。

```text
全国位置索引 → 北京桶 / 上海桶 / 天津桶 / 深圳桶
```

这是分桶思路，不是自动分片命令。临近区域边界的查询可能同时访问多个桶，应用需要合并、去重并统一排序。Redis Cluster 不会自动把同一个 Zset 内的成员拆到不同节点；分桶要结合半径和实际热点分布。

| 命令      | 官方复杂度特点                                                           |
| --------- | ------------------------------------------------------------------------ |
| GEOADD    | 每个成员 O(log N)，N 为索引总成员数                                      |
| GEOPOS    | 每个请求成员 O(1)                                                        |
| GEODIST   | O(1)                                                                     |
| GEOHASH   | 每个请求成员 O(1)                                                        |
| GEOSEARCH | O(C + log R)，C 为覆盖形状的网格对齐包围框内成员数，R 为实际形状内成员数 |
| ZREM      | 每个成员 O(log N)，N 为索引总成员数                                      |

这里将 GEOSEARCH 官方公式的变量重新命名为 C、R，避免与其他行的 N 混淆；C、R 都不是索引总数。命中区域密集、返回量大或需要排序时，成本仍可能很高，COUNT 也不直接限定 C。[GEOADD](https://redis.io/docs/latest/commands/geoadd/) · [GEOPOS](https://redis.io/docs/latest/commands/geopos/) · [GEODIST](https://redis.io/docs/latest/commands/geodist/) · [GEOHASH](https://redis.io/docs/latest/commands/geohash/) · [GEOSEARCH](https://redis.io/docs/latest/commands/geosearch/) · [ZREM](https://redis.io/docs/latest/commands/zrem/)

位置数据还涉及隐私、保留时长和授权。键级 TTL（Time to Live，生存时间）到期会影响整个索引；GEO 成员不是 Hash field（哈希字段），不能因为 Redis Open Source 7.4.0 有 HEXPIRE 就推断它也有相同的成员 TTL。

## 5. 检索结果的业务验收

至少验证坐标顺序、边界区域、距离单位、相同坐标、多成员更新和结果截断。若结果用于收费、导航或安全范围，应采用满足业务精度要求的地理方案。

| 场景                         | 是否适合直接使用 Redis GEO         |
| ---------------------------- | ---------------------------------- |
| 附近餐厅、商店、社交用户检索 | 适合做候选位置查询                 |
| 精确道路导航                 | 不适合直接替代道路与路线模型       |
| 收费里程计算                 | 不建议直接使用球面距离作为收费依据 |
| 高精度地理测绘               | 不适合替代专业 GIS                 |

本章没有地图、路线或性能测试，不把近似地理检索写成精确测距承诺。

[返回本册目录](/collections/redis/)
