# AutoERP 自动化测试框架

[![Python](https://img.shields.io/badge/Python-3.12+-blue.svg)](https://www.python.org)
[![pytest](https://img.shields.io/badge/pytest-9.0+-green.svg)](https://pytest.org)
[![Playwright](https://img.shields.io/badge/Playwright-1.x-brightgreen.svg)](https://playwright.dev/python/)
[![Allure](https://img.shields.io/badge/Allure-2.13+-orange.svg)](https://allurereport.org)
[![Locust](https://img.shields.io/badge/Locust-2.31+-red.svg)](https://locust.io)
[![CI GitHub Actions](https://img.shields.io/badge/CI-GitHub_Actions-blue.svg)](https://github.com/features/actions)

AutoERP 是基于 Python + pytest、面向 jshERP 进销存业务的自动化测试框架，统一执行 API、UI 与跨层 E2E 测试，覆盖商品、仓库、采购和销售等核心业务。项目通过数据驱动、数据库断言和失败现场留存，减少重复回归成本并提升问题定位效率。

## 📊 实际测试成果

2026-10-29 在同一轮 pytest 完整执行中共运行 **44 条自动化用例，43 Passed / 1 Failed，通过率 97.72%**；完整执行耗时 **381.52 秒（约 6 分 22 秒）**。

| 测试类型 | 用例数 | Passed | Failed |
| --- | ---: | ---: | ---: |
| API 自动化 | 39 | 38 | 1 |
| UI 自动化 | 3 | 3 | 0 |
| E2E 自动化 | 2 | 2 | 0 |
| **合计** | **44** | **43** | **1** |

- UI 登录、采购转入库、销售转出库 3 条用例全部通过。
- 采购入库、销售出库 2 条跨层 E2E 均通过，完成 UI 操作、API 查询、MySQL 断言和定向清理。
- 本轮没有额外的 teardown ERROR。
- 唯一失败用例为“销售出库数量超出库存，预期接口拒绝请求”：实际接口返回 `code=200` 且创建了出库单，与测试预期不一致；本轮结束后该单据已由后置清理移除。
- 数据库只读复核未发现本轮测试业务数据的有效残留；仓库 `124` 中商品 `929` 的库存恢复至基准值 `197.000000`。

### Allure 全量执行总览

![Allure 全量自动化测试报告](images/allure_overview.png)

### Allure 测试套件与跨层 E2E

![API、UI、E2E 测试套件与销售跨层业务闭环](images/allure_details.png)

> 以上结果来自本地真实测试环境的完整执行，报告保留了失败结果，不将数据清理成功等同于全部测试通过。

## 目录

- [实际测试成果](#-实际测试成果)
- [技术栈](#-技术栈)
- [项目结构](#-项目结构)
- [技术架构](#-技术架构)
- [测试类型详解](#-测试类型详解)
- [设计亮点](#-设计亮点)
- [配置说明](#-配置说明)
- [测试报告](#-测试报告)
- [CI 持续集成](#-ci-持续集成)
- [快速开始](#-快速开始)
- [License](#-license)

## 🛠 技术栈

| 技术/工具 | 作用 |
| --- | --- |
| Python / pytest | 测试执行、fixture 和 marker 管理 |
| requests / YAML / JSONPath | API 请求、数据驱动和响应字段提取 |
| Playwright | Web UI 自动化、截图、视频和 Trace |
| MySQL / PyMySQL | 数据库断言和测试数据复核 |
| Allure | API、UI、E2E 可视化报告 |
| Locust | 性能测试与 HTML/CSV 输出 |
| GitHub Actions | 代码检查、用例收集与只读连通性检查 |

## 📁 项目结构

```text
AutoERP/
├── .github/workflows/        # GitHub Actions workflow
├── api/                      # API 自动化用例、YAML、Schema 和统一执行器
├── ui/                       # Playwright UI 用例、fixture、页面对象
├── e2e/                      # API + UI + 数据库跨层冒烟
├── performance/              # Locust 性能测试
├── shared/                   # API/UI/E2E 复用的客户端和数据库辅助方法
├── config/                   # 统一配置读取与配置模板
├── images/                   # README 使用的 Allure 与 Locust 真实运行截图
├── reports/                  # 测试报告与运行产物
├── run.py                    # 统一执行入口
├── pytest.ini                # pytest 配置与 marker
└── requirements.txt          # 依赖清单
```

## 🏗 技术架构

```text
┌──────────────────────────────────────────────────────────────┐
│                         jshERP 云端测试环境                   │
│                Web UI / 后端 API / MySQL 业务数据库            │
└──────────────────────────┬───────────────────────────────────┘
                           │
    ┌──────────────────────┼──────────────────────┐
    │                      │                      │
    ▼                      ▼                      ▼
┌──────────────┐    ┌────────────────┐    ┌────────────────┐
│ API 自动化    │    │ UI 自动化       │    │ 性能测试        │
│ pytest       │    │ Playwright     │    │ Locust         │
│ requests     │    │ Page Object    │    │ read/write     │
└──────┬───────┘    └───────┬────────┘    └───────┬────────┘
       │                    │                     │
       └────────────┬───────┴────────────┬────────┘
                    ▼                    ▼
            ┌──────────────┐     ┌──────────────┐
            │ 共享工具层     │     │ 报告与产物    │
            │ API Client   │     │ Allure       │
            │ DB Helpers   │     │ Playwright   │
            │ Test Data    │     │ Locust       │
            └──────┬───────┘     └──────────────┘
                   ▼
            ┌──────────────┐
            │ 配置层        │
            │ env/local.ini │
            │ settings.py   │
            └──────────────┘
```

## 📊 测试类型详解

### API 自动化

接口用例使用 YAML 描述请求、提取和断言规则，由统一执行器完成鉴权、变量替换、requests 调用、JSONPath 提取、响应断言、JSON Schema 契约校验及 MySQL 数据库断言。

| 类型 | 覆盖内容 | 入口 |
| --- | --- | --- |
| 单接口用例 | 商品、仓库、采购、销售、收付款等接口 YAML | `python run.py api --suite single` |
| 业务链路 | 采购入库核心链路、销售出库核心链路 | `python run.py api --suite business` |
| 异常边界 | Token 缺失/失效、销售异常、付款异常 | `python run.py api --suite negative` |
| 契约校验 | 登录、商品列表、采购单详情 JSON Schema | `python run.py api --suite smoke` |

### UI 自动化

UI 用例基于 pytest-playwright 和 Page Object，复用登录态，并在失败时保留 Screenshot 与 Trace，便于还原页面状态和请求时序。

| 测试文件 | 覆盖范围 | 说明 |
| --- | --- | --- |
| `ui/cases/test_login.py` | jshERP 登录冒烟 | 账号、密码和登录成功判断均来自配置 |
| `ui/cases/test_purchase_sales.py` | 采购订单转采购入库、销售订单转销售出库 | 单据编号带运行 ID，结束后定向清理本轮数据 |
| `ui/cases/test_skeleton.py` | UI 收集检查 | 不启动浏览器，用于验证 pytest 收集链路 |

### 跨层 E2E

E2E 围绕真实 ERP 业务闭环构建，不只验证浏览器页面：测试从 UI 创建和流转单据，再通过 API 查询、MySQL 库存与金额断言确认后端结果，最后按真实数据库 ID 精确定向清理。

| 测试文件 | 覆盖范围 | 校验方式 |
| --- | --- | --- |
| `e2e/test_purchase_sales_e2e.py` | 采购订单到已审核采购入库 | UI 操作 + API 查询 + MySQL 库存/金额断言 |
| `e2e/test_purchase_sales_e2e.py` | 销售订单到已审核销售出库 | UI 操作 + API 查询 + MySQL 库存/金额断言 |

### 性能测试

| 用户模型 | 请求范围 | 输出 |
| --- | --- | --- |
| `ErpReadOnlyUser` | 登录、商品列表、库存列表、单据列表 | Locust HTML、CSV 和日志 |
| `ErpPurchaseWriteUser` | 采购入库单创建、详情查询、审核、反审核、清理和残留复核 | Locust HTML、CSV 和日志 |
| `ErpSalesWriteUser` | 销售出库单创建、详情查询、审核、反审核、库存恢复、清理和残留复核 | Locust HTML、CSV 和日志 |

性能测试当前提供 `readonly`、`purchase_write` 和 `sales_write` 三个显式场景。写入场景只在受控测试环境中用于短时冒烟验证，使用 `AUTO_PERF_` 前缀、运行 ID、审核/反审核和数据库定向清理控制业务副作用。

2026-08-29 对 ERP 核心业务只读接口执行了约 5 分钟的持续基线测试，场景包含登录鉴权请求：

| 指标 | 结果 |
| --- | ---: |
| 最大并发用户数 | 10 |
| 持续时间 | 约 5 分钟 |
| 总请求数 | 1,441 |
| 失败请求数 | 0 |
| RPS | 4.66 |
| 平均响应时间 | 32.75 ms |
| P95 | 43 ms |
| 错误率 | 0% |

![Locust 性能测试统计结果](images/locust_sta.png)

![Locust RPS、响应时间及并发用户趋势](images/locust_charts.png)

该结果仅作为特定测试环境和 10 用户负载下的性能基线，可用于后续版本回归对比，不代表系统最大承载能力、极限并发或容量上限。采购、销售写入场景属于短时写入冒烟测试，与上述持续只读性能基线分别记录。

## ✨ 设计亮点

| 特性 | 说明 |
| --- | --- |
| 数据驱动与统一执行 | pytest 管理 API、UI、E2E，用 YAML 描述接口请求、提取和断言规则，`run.py` 提供统一入口 |
| API 会话上下文 | 登录鉴权、Token 失效重试、模板变量替换及 JSONPath/正则提取使用会话运行上下文，避免不同运行共享提取数据 |
| 响应与数据库断言 | 统一执行器支持 HTTP/业务字段断言、JSON Schema 契约校验和 MySQL 数据断言，失败信息定位到 YAML、步骤、变量来源和具体断言 |
| UI 稳定性与数据登记 | Page Object 使用显式响应等待；销售订单处理异步自动编号时序，保存后按实际请求单号查询并优先登记真实数据库 ID |
| 跨层闭环与安全清理 | E2E 串联 UI、API、MySQL；对已审核库存单据先反审核，再按精确 ID 清理并复核主单、明细和收付款关联残留 |
| 数据隔离与异常保护 | API、UI、E2E 使用独立前缀和运行 ID；无法唯一定位真实单据时停止扩大清理范围并输出人工核查风险 |
| 失败现场留存 | 本地使用 Allure、日志、断言附件及 Playwright Screenshot / Trace 辅助复现和定位问题，敏感请求字段在日志与附件中脱敏 |
| 受控性能场景 | Locust 提供只读持续基线，以及采购、销售短时写入冒烟；写入数据按 `AUTO_PERF_` 前缀和运行 ID 定向处理 |

## ⚙ 配置说明

本地优先使用环境变量或 `config/local.ini`；模板见 `config/local.ini.example` 和 `config/environments.yaml.example`。敏感信息不要写入代码、YAML、报告或提交记录。

常用环境变量：

| 变量 | 说明 |
| --- | --- |
| `ERP_ENV` | 环境名，默认 `cloud_test` |
| `ERP_VERSION` | 云端测试实例版本说明 |
| `ERP_API_URL` | jshERP 后端 API 根地址 |
| `ERP_UI_URL` | jshERP 前端根地址 |
| `ERP_USERNAME` | 测试账号 |
| `ERP_PASSWORD` | 测试密码 |
| `MYSQL_HOST` | MySQL 地址，E2E 和数据库断言需要 |
| `MYSQL_PORT` | MySQL 端口 |
| `MYSQL_USERNAME` | MySQL 用户名 |
| `MYSQL_PASSWORD` | MySQL 密码 |
| `MYSQL_DATABASE` | MySQL 数据库名 |
| `ERP_CATEGORY_ID` | 商品分类 ID |
| `ERP_DEPOT_ID` | 默认仓库 ID |
| `ERP_SUPPLIER_ORGAN_ID` | 供应商 ID |
| `ERP_CUSTOMER_ORGAN_ID` | 客户 ID |
| `ERP_SETTLE_ACCOUNT_ID` | 单据结算账户 ID |
| `ERP_FINANCE_ACCOUNT_ID` | 收付款财务账户 ID |
| `ERP_UI_LOGIN_SUCCESS_KIND` | UI 登录成功判断方式：`url` / `title` / `text` |
| `ERP_UI_LOGIN_SUCCESS_VALUE` | UI 登录成功判断值 |

## 📈 测试报告

本地执行会生成 Allure、JUnit 和 Playwright 调试产物。失败用例可结合断言上下文、脱敏后的请求/响应附件、Screenshot 与 Trace 还原现场；并非每个通过步骤都会生成截图或完整 Trace。开头的真实报告截图见[实际测试成果](#-实际测试成果)。

| 产物 | 路径 |
| --- | --- |
| API Allure 原始结果 | `reports/allure-results/api/` |
| UI Allure 原始结果 | `reports/allure-results/ui/` |
| E2E Allure 原始结果 | `reports/allure-results/e2e/` |
| 本轮全量 Allure 原始结果 | `reports/allure-results/readme-final-20261029-162021/` |
| 本轮全量 JUnit XML | `reports/readme-final-20261029-162021.xml` |
| Allure HTML 报告 | `reports/allure-report/<类型>-<时间戳>-<进程号>/` |
| Playwright Screenshot / Trace | `reports/playwright/` |
| Locust HTML、CSV、日志 | `reports/locust/` |
| JUnit XML | `reports/api_results.xml`、`reports/ui_results.xml`、`reports/e2e_results.xml` |

查看本轮全量 Allure 结果：

```bash
allure serve reports/allure-results/readme-final-20261029-162021
```

`.runtime/auth/` 只用于 Playwright 登录态，不属于报告目录，不应上传为 artifact。

## 🔄 CI 持续集成

当前仓库包含三个 workflow 文件：

| 文件 | 用途 |
| --- | --- |
| `.github/workflows/quality-gate.yml` | Push / PR / 手动触发的轻量检查与用例收集 |
| `.github/workflows/api-test.yml` | Push 代码检查和收集；手动选择 API 套件执行 |
| `.github/workflows/performance-tests.yml` | 手动只读性能预检与受控基线执行 |

### 自动检查与手动任务

- `quality-gate.yml` 在 `master` 的 Push / PR 和手动触发中执行 Python 编译、API/UI/E2E 收集、API/UI 连通性检查，并对 API/UI smoke 套件执行 `collect-only`；这些轻量门禁不执行会创建 ERP 业务数据的真实回归。
- GitHub 托管 Runner 当前没有已验证的测试数据库网络连接或 SSH 隧道，因此 `quality-gate.yml` 暂不提供云端 API/UI/E2E 业务写入入口；本地 pytest 执行能力不受影响。
- `api-test.yml` 在 `master`、`main` Push 时执行语法检查和 API/UI 用例收集；其手动真实 API 测试在数据库清理链路可达并完成预检前不应触发。
- `performance-tests.yml` 只能手动触发，只允许 `readonly`，最多 10 用户、最长 5 分钟；正式执行前先进行 1 用户、1 分钟预检，并用并发锁避免性能任务重叠。

### 结果归档边界

- 手动 API workflow 和性能任务仅上传 `artifact-summary/*.json` 受限摘要，包含执行状态及必要的聚合计数。
- CI 不上传完整 Allure 原始结果、全量 JUnit XML、Playwright Trace / Screenshot、原始 Locust CSV 或日志；本地报告能力与 CI Artifact 归档相互独立。
- 当前工作流已完成本地代码核对，但仓库内没有足够证据证明最新版本已在 GitHub 托管 Runner 上完整验证通过，因此不作云端成功声明。

采购和销售写入性能场景当前只在本地或受控真实测试环境中显式执行，不纳入 GitHub 托管 Runner 的手动性能流水线。

### GitHub Secrets

建议配置的仓库 Secrets：

| Secret | 用途 |
| --- | --- |
| `ERP_API_URL` | 质量检查和性能流水线使用的 API 地址 |
| `ERP_UI_URL` | 质量检查使用的 UI 地址 |
| `ERP_USERNAME` | API/UI/E2E/性能测试账号 |
| `ERP_PASSWORD` | API/UI/E2E/性能测试密码 |
| `ERP_HOST` | API workflow 兼容字段；当前 workflow 优先使用 `ERP_API_URL` / `ERP_UI_URL` |
| `MYSQL_HOST` | 手动 API workflow 的数据库断言与清理；仅在连接链路已验证时使用 |
| `MYSQL_PORT` | 手动 API workflow 的数据库断言与清理；仅在连接链路已验证时使用 |
| `MYSQL_USERNAME` | 手动 API workflow 的数据库断言与清理；仅在连接链路已验证时使用 |
| `MYSQL_PASSWORD` | 手动 API workflow 的数据库断言与清理；仅在连接链路已验证时使用 |
| `MYSQL_DATABASE` | 手动 API workflow 的数据库断言与清理；仅在连接链路已验证时使用 |

暂不配置且不阻塞当前质量检查的通知类 Secrets：

- `DINGTALK_WEBHOOK`
- `DINGTALK_SECRET`
- `EMAIL_*`

## 🚀 快速开始

### 环境准备

```bash
git clone https://github.com/C0LUMN7/AutoERP.git
cd AutoERP
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

执行会生成 Allure HTML 的 API/UI/E2E 命令前，需要本机已安装 Allure CLI 并加入 `PATH`。
运行 UI/E2E 前还需要安装对应浏览器；默认 Chromium 可执行：

```bash
python -m playwright install chromium
```

### 配置环境

```bash
cp config/local.ini.example config/local.ini
```

填写 `config/local.ini` 或导出环境变量。

### 收集检查

```bash
python run.py preflight
python run.py api --collect-only
python run.py ui --collect-only
python run.py e2e --collect-only
```

### 运行命令

```bash
# API
python run.py api --suite smoke
python run.py api --suite single
python run.py api --suite business
python run.py api --suite negative
python run.py api --suite all

# UI
python run.py ui --suite smoke
python run.py ui --suite all
python run.py ui --browser chromium --headed

# E2E
python run.py e2e --suite smoke
python run.py e2e --suite all

# 性能测试
python run.py performance --scenario readonly --users 1 --spawn-rate 1 --run-time 1m
python run.py performance --scenario purchase_write --users 1 --spawn-rate 1 --run-time 1m
python run.py performance --scenario sales_write --users 1 --spawn-rate 1 --run-time 1m

# 显式发送通知
python run.py notify --report reports/api_results.xml --channel email
python run.py notify --report reports/api_results.xml --channel dingtalk
python run.py notify --report reports/api_results.xml --channel all
```

`performance` 必须显式执行，不会混入 API/UI/E2E 普通回归。当前性能入口提供 `readonly`、`purchase_write` 和 `sales_write` 场景；`readonly` 最大用户数 `10`、最长运行时间 `5m`，写入场景最大用户数 `3`、最长运行时间 `2m`、最大 `spawn-rate=1`。写入类结果仅作为受控测试环境下的性能验证，不作为生产容量结论。

`notify` 也必须显式执行，API/UI/E2E 默认执行完成后不会自动发送通知。通知依赖本地 `config/local.ini` 或环境变量中的钉钉、邮箱配置。

## 📝 License

本项目采用 MIT 许可证 - 详见 [LICENSE](LICENSE) 文件，仅供学习和求职展示使用。
