# 街道遮阴与公共空间数据

主子方向为数据分析与数据应用。规划团队用现场阴影抽查、街道空间用途和景观变动记录来核对公共遮阴。仓库产出候车与步行空间的覆盖数据、施工期间的遮阴服务日历和树木及建筑的遮阴贡献。可以使用几个街段的合成几何、已知阴影范围和模拟观测。

这是可运行的最小数据基线，只实现下表列明的能力。几何用平面矩形和已排序步行段表示，不推算太阳位置。巡查数据来自离线清单，不读取照片本身。

| 数据链 | 基线能力 | 离线样例 | 可核验结果 |
|---|---|---|---|
| `queue-coverage` | 按已同步的矩形阴影和实际候车队列范围计算荫蔽比例。 | [输入](examples/queue-coverage.json) | [结果](tests/expected/queue-coverage.json) |
| `walk-exposure` | 沿已排列的步行段合并连续曝晒，未观测段不当作曝晒或遮阴。 | [输入](examples/walk-exposure.json) | [结果](tests/expected/walk-exposure.json) |
| `photo-evidence` | 摄取已导出的巡查照片清单，在同观察点同观察时刻内选最后核准的复拍。 | [输入](examples/photo-evidence.json) | [结果](tests/expected/photo-evidence.json) |
| `construction-service` | 按施工日历核对停用后的服务点是否有验收开放的临时遮棚。 | [输入](examples/construction-service.json) | [结果](tests/expected/construction-service.json) |
| `shade-contributions` | 按已划分的不相交矩形观察单元汇总树、建筑和共用遮阴。 | [输入](examples/shade-contributions.json) | [结果](tests/expected/shade-contributions.json) |

## 运行

在仓库根目录使用 Python 3.11 及以上版本，无需安装运行依赖：

```sh
python3 -m public_shade_evidence queue-coverage examples/queue-coverage.json
python3 -m public_shade_evidence queue-coverage examples/queue-coverage.json --sqlite facts.sqlite
python3 -m unittest discover -s tests -v
```

每个输入文件包含 `records` 数组，记录的 `id` 在批内唯一。各数据链校验自己的业务字段，输出按 `fact_id` 标识的事实。起止范围若无另行说明均为左闭右开；日期、深度、金额和持续时间等单位由字段标明。

加上 `--sqlite` 时，`runs` 表保存规范化的来源 JSON 与 SHA-256，`facts` 表保存同一批次的事实。原样重放不新增事实；写入失败回滚整批。既有数据库不会被自动改写为不同版本的处理结果。JSON 接口和入库只是数据处理的运行入口，不是仓库的业务主体。
