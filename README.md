# AutoERP 自动化测试框架

[![Python](https://img.shields.io/badge/Python-3.12+-blue.svg)](https://www.python.org)
[![pytest](https://img.shields.io/badge/pytest-9.0+-green.svg)](https://pytest.org)
[![Playwright](https://img.shields.io/badge/Playwright-1.x-brightgreen.svg)](https://playwright.dev/python/)
[![Allure](https://img.shields.io/badge/Allure-2.13+-orange.svg)](https://allurereport.org)
[![Locust](https://img.shields.io/badge/Locust-2.31+-red.svg)](https://locust.io)
[![CI GitHub Actions](https://img.shields.io/badge/CI-GitHub_Actions-blue.svg)](https://github.com/features/actions)

本项目是基于进销存系统 **jshERP** 的全方位自动化测试框架，覆盖接口自动化、UI 自动化、E2E 和性能测试。适用于测试工程师对自动化测试框架进行实践、求职面试展示或学习参考。

## 目录

- [技术栈](#-技术栈)
- [项目结构](#-项目结构)
- [技术架构](#-技术架构)
- [测试类型详解](#-测试类型详解)
- [设计亮点](#-设计亮点)
- [配置说明](#-配置说明)
- [测试报告](#-测试报告)
- [CI/CD 流水线](#-cicd-流水线)
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
| GitHub Actions | 质量检查与手动性能流水线 |

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

| 类型 | 覆盖内容 | 入口 |
| --- | --- | --- |
| 单接口用例 | 商品、仓库、采购、销售、收付款等接口 YAML | `python run.py api --suite single` |
| 业务链路 | 采购入库核心链路、销售出库核心链路 | `python run.py api --suite business` |
| 异常边界 | Token 缺失/失效、销售异常、付款异常 | `python run.py api --suite negative` |
| 契约校验 | 登录、商品列表、采购单详情 JSON Schema | `python run.py api --suite smoke` |

### UI 自动化

| 测试文件 | 覆盖范围 | 说明 |
| --- | --- | --- |
| `ui/cases/test_login.py` | jshERP 登录冒烟 | 账号、密码和登录成功判断均来自配置 |
| `ui/cases/test_purchase_sales.py` | 采购订单转采购入库、销售订单转销售出库 | 单据编号带运行 ID，结束后定向清理本轮数据 |
| `ui/cases/test_skeleton.py` | UI 收集检查 | 不启动浏览器，用于验证 pytest 收集链路 |

### 跨层 E2E

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

性能测试当前提供 `readonly`、`purchase_write` 和 `sales_write` 三个显式场景。只读场景最大用户数 `10`、最长运行时间 `5m`；写入场景最大用户数 `3`、最长运行时间 `2m`、最大 `spawn-rate=1`。写入场景只走 API，使用 `AUTO_PERF_` 前缀、运行 ID、审核/反审核和数据库定向清理控制业务副作用，不输出生产容量结论。

## ✨ 设计亮点

| 特性 | 说明 |
| --- | --- |
| 真实接口基线 | API 用例复用 jshERP 真实 YAML，覆盖商品、仓库、采购、销售、异常边界和采购/销售业务链路 |
| 统一 API 执行器 | 支持单接口用例和多步骤业务场景，失败信息定位到 YAML、用例、请求、断言和变量来源 |
| Playwright 页面自动化 | 使用官方 `pytest-playwright`，按 Page Object 组织登录、采购转入库、销售转出库等 ERP 页面冒烟用例 |
| 跨层闭环校验 | E2E 用例串联 UI 操作、API 查询和数据库校验，覆盖采购入库与销售出库链路 |
| 性能测试 | Locust 覆盖只读查询基线、采购写入和销售写入两个受控事务场景，写入数据使用 `AUTO_PERF_` 前缀和运行 ID 定向清理 |
| 运行入口收敛 | 根目录 `run.py` 统一承接 API、UI、E2E、环境预检、性能和通知命令 |
| 报告产物隔离 | API/UI/E2E 使用分目录 Allure 原始结果，UI/E2E 输出截图、视频和 Trace，性能输出 HTML、CSV 和日志 |

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

| 产物 | 路径 |
| --- | --- |
| API Allure 原始结果 | `reports/allure-results/api/` |
| UI Allure 原始结果 | `reports/allure-results/ui/` |
| E2E Allure 原始结果 | `reports/allure-results/e2e/` |
| Allure HTML 报告 | `reports/allure-report/<类型>-<时间戳>-<进程号>/` |
| Playwright 截图、视频、Trace | `reports/playwright/` |
| Locust HTML、CSV、日志 | `reports/locust/` |
| JUnit XML | `reports/api_results.xml`、`reports/ui_results.xml`、`reports/e2e_results.xml` |

`.runtime/auth/` 只用于 Playwright 登录态，不属于报告目录，不应上传为 artifact。

## 🔄 CI/CD 流水线

当前仓库包含三个 workflow 文件：

| 文件 | 用途 |
| --- | --- |
| `.github/workflows/api-test.yml` | API 自动化 workflow，保留兼容 |
| `.github/workflows/quality-gate.yml` | API/UI/E2E 质量检查 |
| `.github/workflows/performance-tests.yml` | 手动只读性能流水线 |

### 质量检查策略

- PR 到 `master` 默认运行 `lint-and-collect`、`api-smoke`、`ui-smoke`。
- PR 的 `api-smoke` 只做 API smoke 收集和 API 连通性检查，不执行数据库断言或数据库闭环。
- PR 的 `ui-smoke` 只做 UI smoke 收集和 UI 连通性检查，不安装浏览器、不执行真实页面用例。
- `master` push 或 `workflow_dispatch` 可运行 `e2e-smoke`。
- 建议 Required Checks 设置为 `lint-and-collect`、`api-smoke`、`ui-smoke`。
- 不建议把 `e2e-smoke` 和 `performance-tests` 设为普通 PR Required Checks。
- artifact 上传使用 `if: always()` 保留失败证据；测试步骤失败时 job 仍然失败，不使用 `continue-on-error` 掩盖结果。

### 手动性能流水线策略

- 只能通过 `workflow_dispatch` 手动触发。
- 输入包含 `environment`、`scenario`、`users`、`spawn_rate`、`run_time`。
- `scenario` 只能是 `readonly`。
- `users` 最大 `10`，`run_time` 最长 `5m`。
- 正式执行前先跑 `1` 用户、`1m`、`readonly` 预检。
- 预检失败不得继续升压。
- 不执行写入类性能场景，不使用 `MYSQL_*` 做数据库闭环。
- 使用并发锁 `jsh-erp-performance`，同一时间只允许一个性能任务运行。

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
| `MYSQL_HOST` | E2E 或非 PR 数据库断言需要 |
| `MYSQL_PORT` | E2E 或非 PR 数据库断言需要 |
| `MYSQL_USERNAME` | E2E 或非 PR 数据库断言需要 |
| `MYSQL_PASSWORD` | E2E 或非 PR 数据库断言需要 |
| `MYSQL_DATABASE` | E2E 或非 PR 数据库断言需要 |

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
