# performance（性能测试）

Locust 性能测试目录。

当前包含三个显式性能测试入口：

- `locustfile.py`：只读 Locust 用户模型，包含登录、商品查询、库存查询和单据查询；采购写入用户模型包含采购入库单创建、查询、审核、反审核、定向清理和残留复核；销售写入用户模型包含销售出库单创建、查询、审核、反审核、库存恢复校验、定向清理和残留复核。
- `reports/locust/`：Locust HTML、CSV 和运行日志输出目录。

只读场景：

```bash
python run.py performance --users 1 --spawn-rate 1 --run-time 1m --scenario readonly
```

采购写入单用户预检：

```bash
python run.py performance --scenario purchase_write --users 1 --spawn-rate 1 --run-time 1m
```

采购写入小并发上限：

```bash
python run.py performance --scenario purchase_write --users 3 --spawn-rate 1 --run-time 2m
```

销售写入单用户预检：

```bash
python run.py performance --scenario sales_write --users 1 --spawn-rate 1 --run-time 1m
```

销售写入小并发上限：

```bash
python run.py performance --scenario sales_write --users 3 --spawn-rate 1 --run-time 2m
```

只读接口来源：

- `/user/login`：来自现有 `api/login.yaml`、`shared/api_client.py` 和 `shared/debugtalk.py`。
- `/material/list`：来自现有 `api/cases/goods/goods_read.yaml`。
- `/material/getListWithStock`：来自 jshERP 商品库存页面 `MaterialStock.vue` 的只读列表接口。
- `/depotHead/list`：来自 jshERP 单据列表页面的只读列表接口；现有 API 用例也已使用同一
  `depotHead` 模块的详情、审核接口。

采购写入接口来源：

- `/depotHead/addDepotHeadAndDetail`：参考 `api/cases/purchase/buy_add.yaml` 的采购入库参数。
- `/depotHead/getDetailByNumber`：参考 `api/cases/purchase/buy_get_detail.yaml` 按单据编号查询详情。
- `/depotHead/batchSetStatus`：参考 `api/cases/purchase/buy_set_status.yaml` 执行审核；反审核使用同一接口传 `status=0`，与 E2E 后置清理一致。

销售写入接口来源：

- `/depotHead/addDepotHeadAndDetail`：参考 `api/cases/sales/sale_add.yaml` 的销售出库参数。
- `/depotHead/getDetailByNumber`：参考 `api/cases/sales/sale_get_detail.yaml` 按单据编号查询详情。
- `/depotHead/batchSetStatus`：参考 `api/cases/sales/sale_set_status.yaml` 执行审核；反审核使用同一接口传 `status=0`，与 E2E 后置清理一致。

采购写入数据约束：

- 单据编号使用 `AUTO_PERF_PI_<run_id>_<sequence>`。
- 每个 Locust 用户只执行一次完整采购写入闭环，完成清理和残留复核后停止。
- 清理只处理本轮 `AUTO_PERF_` 前缀、包含本轮 `run_id`、且本轮代码记录过的出入库单据头和明细。
- 不清理 `AUTO_API_`、`AUTO_UI_`、`AUTO_E2E_` 数据，不清理供应商、客户、仓库、结算账户、固定商品等基础资料。

销售写入数据约束：

- 单据编号使用 `AUTO_PERF_SOUT_<run_id>_<sequence>`。
- 每个 Locust 用户只执行一次完整销售写入闭环，完成库存恢复校验、清理和残留复核后停止。
- 执行前检查本用户选定销售商品库存；库存不足时记录为 Locust failure 后停止，不修改基础库存或基础资料。
- 单用户预检校验审核后库存精确扣减和反审核后库存精确恢复。
- 小并发下按用户序号选择不同销售商品组合，当前固定使用 `请购单测试商品A`、`请购单测试商品B`、`洗脸巾`，仓库仍使用配置中的自动化测试仓库；最后一个完成的用户清理后，逐一复核本轮涉及商品库存恢复到执行前基线。
- 已观察到同一商品同一仓库热点库存并发销售会触发 MySQL deadlock，该问题作为后端并发控制专项风险记录，不作为当前最小闭环验收口径。
- 销售写入中的登录、前置检查、业务请求和清理异常都会记录为 Locust failure；失败后停止本轮运行，不继续升压。
- 清理只处理本轮 `AUTO_PERF_` 前缀、包含本轮 `run_id`、且本轮代码记录过的出入库单据头和明细。
- 不清理 `AUTO_API_`、`AUTO_UI_`、`AUTO_E2E_` 数据，不清理供应商、客户、仓库、结算账户、固定商品等基础资料。

当前边界：

- `readonly` 最大 `10` 用户、最长 `5m`。
- `purchase_write` 最大 `3` 用户、最长 `2m`、最大 `spawn-rate=1`。
- `sales_write` 最大 `3` 用户、最长 `2m`、最大 `spawn-rate=1`。
- 当前不包含付款、收款、删除接口、UI 写入性能、长时间稳定性、峰值压测、分布式 Locust、Docker 或监控平台。
- 本目录输出的 Locust 结果只能用于受控测试环境下的链路验证，不给出生产容量结论。
