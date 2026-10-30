# AutoERP YAML conventions

This reference records repository behavior, not a product specification. Recheck the cited source before generating a draft when code has changed.

## Sources

- Loader and run context: `api/framework/yaml_loader.py`
- Template expressions: `api/framework/template.py`, `shared/debugtalk.py`
- Request execution and extraction: `api/framework/runner.py`, `api/framework/http_client.py`
- Assertions: `api/framework/assertions.py`
- Session login and cleanup: `api/conftest.py`
- Real examples: `api/cases/`, especially `api/cases/scenarios/PurchaseScenario.yml` and `SalesScenario.yml`

## File structure

The document root is a YAML list. Each item has one `baseInfo` mapping and one `testCase` list:

```yaml
- baseInfo:
    api_name: 商品查询
    url: /material/list
    method: GET
    header:
      Content-Type: application/json;charset=UTF-8
      X-Access-Token: ${get_extract_data(token)}
  testCase:
    - case_name: 正常查询商品列表
      validation:
        - contains: { 'code': 200 }
```

`load_case_pairs()` preserves file order and expands every test case into a `(base_info, testcase)` pair. It does not enforce a schema, so static review must reject missing or mistyped structural fields explicitly.

`run_scenario_file()` executes the expanded pairs sequentially and stops on the first error. Ordinary pytest parametrization can load the same format but does not by itself make a case independent of session fixtures or earlier ordered tests.

## Request fields

- `baseInfo`: `api_name`, `url`, `method`, and usually `header`.
- `testCase`: `case_name`, then at most the request containers needed by the verified interface.
- The runner resolves and forwards `params`, `data`, and `json`.
- `files` is supported as a file mapping; do not add it unless an existing interface proves the field and file behavior.
- `cookies` can be read from `baseInfo`, but never put real Cookie values in a draft.
- Use only interface paths, methods, parameter locations, and request fields found in current source or existing YAML.

## Template expressions

The syntax is `${function(args)}`. `TemplateResolver` recursively resolves strings in dictionaries and lists. Arguments are comma-separated text; do not assume nested expressions or a general expression language.

Common repository-backed functions include:

| Function | Purpose and constraint |
| --- | --- |
| `get_extract_data(name)` | Read a value from the current run context; the value must already exist. |
| `get_business_id(key)` | Read a configured category, warehouse, organization, or account ID; never replace it with a guessed historical ID. |
| `fixed_timestamp()` | Return one cached 13-digit run ID for the current process/session. |
| `short_run_id()` | Return the base-36 form of the same fixed run ID for shorter warehouse names. |
| `get_material_id_by_name(prefix)` | Query the exact `prefix + fixed_timestamp()` material; depends on the material already existing. |
| `get_depot_id_by_name(prefix)` | Query the exact warehouse name for the current run; depends on its earlier creation/update. |
| `start_time()` / `end_time()` | Produce existing time strings used by current cases. |
| `gen_bar_code()` | Fetch the next barcode from a live API and store it in run context. Never call it during static validation. |

Other functions may exist in `DebugTalk`; verify their implementation before use. Function existence alone does not prove the related business rule.

## Extraction and cross-step variables

`extract` stores one value per name. JSONPath expressions contain `$`; the runner stores the first matched value. Supported legacy regular-expression capture markers are `(.+?)`, `(.*?)`, `(\d+)`, and `(\d*)`.

`extract_list` stores multiple values. JSONPath results are stored as a list; the two string capture markers can also collect multiple matches.

Example ordering:

```yaml
      extract:
        buyId: $.data.id
# A later block may then use:
      json:
        ids: ${get_extract_data(buyId)}
```

Never reference a variable before its extraction step or required session fixture. A warning from failed extraction does not establish a usable value.

## YAML assertion types

Only these keys are implemented in `Assertions`:

| Type | Actual behavior | Shape |
| --- | --- | --- |
| `contains` | JSONPath-search each named response field; expected value must be contained. `status_code` compares the HTTP status directly. | `- contains: { 'code': 200 }` |
| `eq` | Compare named top-level response fields for equality. | `- eq: { 'msg': '操作成功' }` |
| `ne` | Compare named top-level response fields for inequality. | `- ne: { 'code': 200 }` |
| `rv` | Compare one named top-level response field for equality. | `- rv: { 'code': 200 }` |
| `db` | Execute the supplied SQL and pass only when at least one row is returned. | `- db: "SELECT ..."` |
| `db_eq` | Execute `sql`, compare the first column of the first row with `expect`. | `- db_eq: { sql: "SELECT ...", expect: 1 }` |

Do not invent assertion keys. `validate_schema()` exists in `api/framework/assertions.py`, but current cases invoke it from pytest code; it is not a YAML `validation` type.

Database assertions are allowed only when the table, columns, relationship, and expected result already have repository evidence. They are executable operations against a configured database, so static validation must inspect text only and must not call them.

## Data isolation and cleanup

- Writable API data uses `AUTO_API_` names or numbers with the current fixed run ID.
- Material names commonly use `AUTO_API_<purpose>_${fixed_timestamp()}`.
- Warehouse names use `AUTO_API_D_${short_run_id()}` and `AUTO_API_U_${short_run_id()}`.
- Exact name helpers prevent selecting arbitrary historical IDs.
- `api/conftest.py` performs session teardown for matching current-run account items, document items, document heads, stock rows, material extensions, materials, and the two exact warehouse names.
- Cleanup is a fallback, not permission to target shared fixed data. State every prerequisite and do not call a dependent update/delete case independently.
- Read-only list cases create no business data and require no business cleanup, but an authenticated session is still a runtime prerequisite.

## Static review checklist

1. Parse YAML without resolving templates.
2. Confirm the root list and every `baseInfo` / `testCase` type.
3. Trace URL, method, fields, assertions, SQL, and expectations to repository evidence.
4. List all template functions and confirm each exists.
5. Track extracted variables in block order and flag forward references.
6. Reject unsupported assertion keys and YAML Schema assertions.
7. Search the draft for credential values, tokens, cookies, connection strings, and copied authentication state.
8. Document write-data naming, dependencies, and cleanup; state “no business cleanup” for read-only drafts.
9. Report parsing and convention checks separately from collection or real execution.
