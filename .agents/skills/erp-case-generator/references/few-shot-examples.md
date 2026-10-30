# Few-shot examples

These examples are derived directly from existing AutoERP YAML. They teach output shape, not additional product rules. All outputs remain pending human review.

## Example 1: read-only warehouse list

Source: `api/cases/warehouse/depot_read.yaml`.

### Input requirement

Use the existing warehouse list interface for a read-only smoke draft. Verify only the success code already asserted by the repository, and do not extract an arbitrary historical warehouse ID for later writes.

### Test points

| test_point_id | scenario_type | preconditions | input_or_action | expected_result | evidence | human_confirmation |
| --- | --- | --- | --- | --- | --- | --- |
| EX1-TP01 | 正常 | pytest session 已完成登录并提供 Token | `GET /depot/list` | 响应包含 `code=200` | `api/cases/warehouse/depot_read.yaml` | 待确认 |
| EX1-TP02 | 数据安全 | 同上 | 不从列表选取任意历史 ID 供写操作 | 草稿不包含 `extract` 或后续写步骤 | 同一 YAML 的用例说明 | 待确认 |

### YAML draft

```yaml
- baseInfo:
    api_name: 查询仓库列表
    url: /depot/list
    method: GET
    header:
      Content-Type: application/json;charset=UTF-8
      X-Access-Token: ${get_extract_data(token)}
  testCase:
    - case_name: 正常查询仓库列表（只读，不提取历史数据行ID）
      validation:
        - contains: { 'code': 200 }
```

### Data handling

The request is read-only and creates no business data, so it has no business cleanup step. It is not independently runnable without the authenticated session fixture.

## Example 2: extract before a dependent audit step

Source: the query and audit blocks in `api/cases/scenarios/PurchaseScenario.yml`.

### Input requirement

Given that the same scenario has already created the current run's purchase receipt, query it by its unique number, extract the real document ID, then audit that exact document. This is a dependent fragment, not a standalone case.

### Test points

| test_point_id | scenario_type | preconditions | input_or_action | expected_result | evidence | human_confirmation |
| --- | --- | --- | --- | --- | --- | --- |
| EX2-TP01 | 正常 | Earlier scenario blocks created `AUTO_API_BSPO_<run_id>` | Query the exact current-run number and extract `$.data.id` | Response contains `code=200` and type `入库`; `buyId` is available to later steps | `PurchaseScenario.yml` query block | 待确认 |
| EX2-TP02 | 数据一致性 | EX2-TP01 completed | Audit with the extracted `buyId` | Response contains the existing success fields and the exact document has status `1` | `PurchaseScenario.yml` audit block | 待确认 |

### YAML draft fragment

```yaml
- baseInfo:
    api_name: 根据单据编号查询采购入库单
    url: /depotHead/getDetailByNumber
    method: GET
    header:
      Content-Type: application/json;charset=UTF-8
      X-Access-Token: ${get_extract_data(token)}
  testCase:
    - case_name: 按本轮唯一编号查询并提取入库单ID
      params:
        number: AUTO_API_BSPO_${fixed_timestamp()}
      extract:
        buyId: $.data.id
      validation:
        - contains: { 'code': 200, 'type': '入库' }
- baseInfo:
    api_name: 审核采购入库单
    url: /depotHead/batchSetStatus
    method: POST
    header:
      Content-Type: application/json;charset=UTF-8
      X-Access-Token: ${get_extract_data(token)}
  testCase:
    - case_name: 使用已提取ID审核本轮入库单
      json:
        ids: ${get_extract_data(buyId)}
        status: "1"
      validation:
        - contains: { 'code': 200, 'message': '成功' }
        - db: "SELECT id FROM jsh_depot_head WHERE id = ${get_extract_data(buyId)} AND status = '1' AND delete_flag = '0'"
```

### Data handling

The fragment depends on the earlier material and receipt creation blocks in the same scenario. The full scenario uses current-run `AUTO_API_` names and numbers; `api/conftest.py` performs matching session cleanup. Do not run only this fragment or treat the status expectation as an independently confirmed product rule.
