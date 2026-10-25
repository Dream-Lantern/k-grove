---
id: redis-geo
title: 第十章 GEO 与地理位置查询
description: Redis GEO 可以保存成员位置，并按附近范围查询。它适合部分位置检索需求，但不能代替完整的 GIS、路线规划和高精度地理计算。
date: '2026-10-25'
updated: '2026-10-25'
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

Redis GEO 可以保存成员位置，并按附近范围查询。它适合部分位置检索需求，但不能代替完整的 GIS、路线规划和高精度地理计算。

## 1. 经纬度顺序与单位

新增示例坐标是教学数据，不代表实际用户位置；未运行：

```redis
GEOADD demo:places 116.40 39.90 place-a 116.42 39.91 place-b
GEOPOS demo:places place-a place-b
GEODIST demo:places place-a place-b km
```

GEOADD 参数先经度，再纬度。GEOPOS 和 GEODIST 都需要键名，原文中只写 member 的格式不完整。距离单位必须明确，不能把米与千米混用。

GEOADD 接受经度 `[-180, 180]`、纬度 `[-85.05112878, 85.05112878]`；纬度不是一般地理意义下的完整 ±90°。越界会报错，不能把任意平面坐标直接当经纬度。参数先经度、后纬度；返回距离也不是实际道路通行距离。[GEOADD 坐标范围](https://redis.io/docs/latest/commands/geoadd/)

## 2. Redis 6.2+ 的 GEOSEARCH

GEOSEARCH 可按指定位置或成员位置做半径、矩形等范围检索；GEOSEARCHSTORE 用于把相应结果写入目的键。旧 GEORADIUS 系列可作为历史接口认识。[GEOSEARCH 的版本与参数](https://redis.io/docs/latest/commands/geosearch/)

```redis
GEOSEARCH demo:places FROMMEMBER place-a BYRADIUS 5 km ASC COUNT 10 WITHDIST
```

该例只用于说明“成员为中心、5 km、按距离排序、限制返回数”。COUNT 不是“数据库只检查这么多候选”的普遍保证；ANY 等选项的效率与排序/结果语义需要对应规则。

## 3. 底层与删除

经典 GEO 索引利用有序集合能力，ZREM 可以移除成员。但不要绕过地理命令任意改 score 后，还认为该成员保留了合法位置编码。

GEOHASH 返回的是相应的编码字符串，并非“返回值的数据类型是 Zset”。编码前缀相近与地理邻近有关，但受网格边界影响，不能反过来认定任意邻近地点都有同样长的公共前缀。

## 4. 一个键的容量与热点

把全国所有动态位置放进一个键，可能带来大量更新与范围查询工作，也让 Cluster 无法把该键内部成员直接拆分。

按城市或区域分桶可以分散负载，但也需要处理边界查询与跨桶聚合。分桶范围应根据实际查询模式确定，不能机械地按行政区切分。

位置数据还涉及隐私、保留时长和授权。键级 TTL 到期会影响整个索引；GEO 成员不是 Hash field，不能因为 Redis 7.4 有 HEXPIRE 就推断它也有相同的成员 TTL。

## 5. 检索结果的业务验收

至少验证坐标顺序、边界区域、距离单位、相同坐标、多成员更新和结果截断。若结果用于收费、导航或安全范围，应采用满足业务精度要求的地理方案。

本章没有地图、路线或性能测试，不把近似地理检索写成精确测距承诺。

[返回本册目录](/collections/redis/)
