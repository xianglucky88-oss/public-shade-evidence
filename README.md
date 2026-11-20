# 街道遮阴与公共空间数据

主子方向为数据分析与数据应用。规划团队用现场阴影抽查、街道空间用途和景观变动记录来核对公共遮阴。仓库产出候车与步行空间的覆盖数据、施工期间的遮阴服务日历和树木及建筑的遮阴贡献。可以使用几个街段的合成几何、已知阴影范围和模拟观测。

这是可运行的最小数据基线，只实现下表列明的能力。几何用平面矩形和已排序步行段表示，不推算太阳位置。巡查数据来自离线清单，不读取照片本身。

| 数据链 | 基线能力 | 离线样例 | 可核验结果 |
|---|---|---|---|
| `queue-coverage` | 按已同步的矩形阴影和实际候车队列范围计算荫蔽比例。 | [输入](examples/queue-coverage.json) | [结果](tests/expected/queue-coverage.json) |
| `walk-exposure` | 沿已排列的步行段合并连续曝晒，未观测段不当作曝晒或遮阴。 | [输入](examples/walk-exposure.json) | [结果](tests/expected/walk-exposure.json) |
| `photo-evidence` | 摄取已导出的巡查照片清单，在同观察点同观察时刻内选最后核准的复拍。 | [输入](examples/photo-evidence.json) | [结果](tests/expected/photo-evidence.json) |
| `construction-service` | 按施工日历核对停用后的服务点是否有验收开放的临时遮棚，并可按出发时段核对步行接续与到站队列遮阴。 | [输入](examples/construction-service.json)、[接续](examples/construction-service-routes.json) | [结果](tests/expected/construction-service.json)、[接续](tests/expected/construction-service-routes.json) |
| `shade-contributions` | 按已划分的不相交矩形观察单元汇总树、建筑和共用遮阴。 | [输入](examples/shade-contributions.json) | [结果](tests/expected/shade-contributions.json) |

## 运行

在仓库根目录使用 Python 3.11 及以上版本，无需安装运行依赖：

```sh
python3 -m public_shade_evidence queue-coverage examples/queue-coverage.json
python3 -m public_shade_evidence queue-coverage examples/queue-coverage.json --sqlite facts.sqlite
python3 -m public_shade_evidence construction-service examples/construction-service-routes.json
python3 -m unittest discover -s tests -v
```

每个输入文件包含 `records` 数组，记录的 `id` 在批内唯一。各数据链校验自己的业务字段，输出按 `fact_id` 标识的事实。起止范围若无另行说明均为左闭右开；日期、深度、金额和持续时间等单位由字段标明。

## 施工服务日历的接续判定

`construction-service` 的原有按天核对保持不变：`temporary_shelters` 的验收标记与开放日决定 `closure_days` 和 `service_gap_days`。记录若同时给出 `routes` 与 `departures`，还会按高峰出发时段生成 `peak_calendar`：

- **走行**：每条线路按 `segments` 的 `walk_min` 依序累计，乘客到达下一路段的时刻即时进入该段；只比较按给定走行时间连续走完的情况。路段可直接写在 `segments` 里，也可在记录顶层用 `segments` 列出、由线路按 id 引用。进入路段时未开放（`not_yet_open`），或路段在走完之前就到开放终点（`segment_closed`，走完时刻等于开放终点仍算走得通），这趟就不通，不把等路重开算成接续。进场时刻已晚于全部开放时段也记为 `segment_closed`。开放时段可写成 `accessible_from`/`accessible_to`，也可写成 `accessible_windows` 的多段时间。
- **连续暴晒**：`observations` 是沿途的分时观测，只取乘客实际经过的那一段；相邻路段首尾相接的暴晒合并计算，遇到遮阴或未观测即中断。超过 `max_sun_exposure_min` 记为 `exposure_exceeded`。
- **到站遮阴**：`shadows` 按乘客到达时刻取当时生效的实测阴影，可写成带 `from`/`to` 的时段，也可写成 `at`/`slot` 的抽样时刻（顺延到下一次抽样或棚的关门时刻）。`queue` 可写成棚下矩形加伸出棚外的队尾多块矩形；阴影重叠处只算一次，队尾没遮到的部分仍计入分母。低于 `min_queue_shade`（可按棚在 `temporary_shelters` 里覆盖）记为 `queue_shade_low`。棚的验收、按天开放窗口（`service_day` 缺省时只核对当天钟点）和 `open_time`/`close_time` 也会核对。
- **缺测**：路段记录带 `"missing": true`、缺关键字段或整个缺失，记为 `segment_missing`/`segment_incomplete`/`segments_missing`；线路没写终点棚记为 `shelter_missing`；行程中某个时段没有观测记为 `shade_unobserved`；到站 `queue` 缺测或为空、`shadows` 缺测、或到达时刻刚好没有生效的实测阴影，分别记为 `queue_missing`/`queue_shadow_missing`/`queue_shadow_unobserved`。缺测不等于走不通，但要指明卡在哪一段。
- **结论**：`reachable`（有线路证据完整且通行、暴晒、队列遮阴三项均达标）、`service_gap`（所有线路都明确走不通）、`unverified`（没有线路走通，但仍有线路没能核实）。只有 `service_gap` 会进入 `service_gap_slots`，缺测的时段单独列在 `unverified_slots`。`changes` 给出相邻出发时段结论变化的位置，`from_reason`/`to_reason` 说明原因在 `route`（路上）、`arrival`（到站后）还是两者兼有。

加上 `--sqlite` 时，`runs` 表保存规范化的来源 JSON 与 SHA-256，`facts` 表保存同一批次的事实。原样重放不新增事实；写入失败回滚整批。既有数据库不会被自动改写为不同版本的处理结果。JSON 接口和入库只是数据处理的运行入口，不是仓库的业务主体。
