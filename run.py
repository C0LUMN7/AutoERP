import argparse
import platform
import shutil
import subprocess
import sys
import os
import re
import time
import xml.etree.ElementTree as ET
from config.settings import ALLURE_HOST, ALLURE_PORT, ERP_API_URL, ERP_UI_URL, REPORT_TYPE, SYSTEM


def _is_ci() -> bool:
    ci_vars = ['CI', 'GITHUB_ACTIONS', 'JENKINS_CI']
    return any(os.getenv(var, '').lower() == 'true' for var in ci_vars)


# suite 到 pytest marker 的映射；negative 为异常场景的标准套件名，
# exception 保留作为旧命令别名（现有用例标记统一使用 negative）
SUITE_MARKERS = {
    'smoke': 'smoke',
    'single': 'single',
    'business': 'business',
    'negative': 'negative',
    'exception': 'negative',
}


RUN_TIME_PATTERN = re.compile(r'^[1-9]\d*[smh]$')
RUN_TIME_UNITS = {'s': 1, 'm': 60, 'h': 3600}
MAX_PERFORMANCE_USERS = 10
MAX_PERFORMANCE_RUN_SECONDS = 5 * 60
PERFORMANCE_SCENARIOS = {
    'readonly': {
        'user_class': 'ErpReadOnlyUser',
        'max_users': 10,
        'max_run_seconds': 5 * 60,
        'max_spawn_rate': None,
        'description': '只读性能基线',
    },
    'purchase_write': {
        'user_class': 'ErpPurchaseWriteUser',
        'max_users': 3,
        'max_run_seconds': 2 * 60,
        'max_spawn_rate': 1,
        'description': '采购写入最小闭环',
    },
    'sales_write': {
        'user_class': 'ErpSalesWriteUser',
        'max_users': 3,
        'max_run_seconds': 2 * 60,
        'max_spawn_rate': 1,
        'description': '销售写入最小闭环',
    },
}


def _build_pytest_args(
    test_type: str,
    suite: str,
    browser: str = '',
    headed: bool = False,
    collect_only: bool = False,
    results_dir: str = '',
) -> list[str]:
    """按测试类型构建 pytest 参数：各类型使用独立用例目录和 Allure 结果目录。

    ui/e2e 额外传入官方 pytest-playwright 参数：浏览器类型、有头模式，
    以及截图/视频/Trace 产物配置（统一收敛到 reports/playwright）。
    """
    if test_type == 'api':
        target = './api/'
    elif test_type == 'e2e':
        target = './e2e/'
    else:
        target = './ui/'

    args = ['-s', '-v']
    if browser:
        args.append(f'--browser={browser}')
    if headed:
        args.append('--headed')
    if test_type in ('ui', 'e2e'):
        # 页面失败截图/视频/Trace 自动留存，产物统一到 reports/playwright
        args.extend([
            '--output=./reports/playwright',
            '--screenshot=only-on-failure',
            '--video=retain-on-failure',
            '--tracing=retain-on-failure',
        ])
    marker = SUITE_MARKERS.get(suite)
    if marker:
        args.extend(['-m', marker, target])
    else:
        args.append(target)
    if collect_only:
        args.append('--collect-only')
        return args
    if not results_dir:
        results_dir = f'./reports/allure-results/{test_type}'
    args.extend([
        f'--alluredir={results_dir}',
        f'--junitxml=./reports/{test_type}_results.xml',
    ])
    return args


def _generate_allure_report(test_type: str, results_dir: str, run_id: str) -> str:
    """将指定类型的 Allure 原始结果生成为 HTML 报告，返回报告目录。

    报告生成到带时间戳的唯一子目录（reports/allure-report/<类型>-<时间戳>），
    不覆盖、不清理任何已有报告目录，也不使用 --clean。
    """
    report_dir = f'./reports/allure-report/{test_type}-{run_id}'
    if os.path.exists(report_dir):
        # 同一秒内重复执行时追加进程号，保证目录不冲突
        report_dir = f'{report_dir}-{os.getpid()}'
    cmd = f'allure generate {results_dir} -o {report_dir}'
    result = subprocess.run(cmd, shell=True)
    if result.returncode != 0:
        print('错误: Allure 命令执行失败，请确认 Allure 已正确安装并已添加到 PATH 环境变量')
        print('下载地址: https://github.com/allure-framework/allure2/releases')
        sys.exit(1)
    return report_dir


def _write_allure_environment(results_dir: str, test_type: str) -> None:
    """为本次运行写入 Allure 环境信息。"""
    os.makedirs(results_dir, exist_ok=True)
    root = ET.Element('environment')
    items = [
        ('system', platform.platform()),
        ('python version', platform.python_version()),
        ('BaseUrl', ERP_API_URL.rstrip('/') if ERP_API_URL else '未配置'),
        ('UIUrl', ERP_UI_URL.rstrip('/') if ERP_UI_URL else '未配置'),
        ('environment', SYSTEM['environment']),
        ('Project', f'{SYSTEM["name"]} 自动化测试框架'),
        ('test type', test_type.upper()),
    ]
    for key, value in items:
        parameter = ET.SubElement(root, 'parameter')
        ET.SubElement(parameter, 'key').text = key
        ET.SubElement(parameter, 'value').text = value
    ET.indent(root, space='    ')
    ET.ElementTree(root).write(
        os.path.join(results_dir, 'environment.xml'),
        encoding='utf-8',
        xml_declaration=False,
    )


def run_suite(test_type: str, suite: str, browser: str = '', headed: bool = False, collect_only: bool = False) -> None:
    if REPORT_TYPE != 'allure':
        print('当前 REPORT_TYPE 不是 allure，跳过测试执行')
        sys.exit(0)

    run_id = ''
    results_dir = ''
    if not collect_only:
        run_id = f'{time.strftime("%Y%m%d-%H%M%S")}-{os.getpid()}'
        results_dir = f'./reports/allure-results/{test_type}/{run_id}'

    pytest_args = _build_pytest_args(test_type, suite, browser, headed, collect_only, results_dir)
    print(f'执行 pytest 参数: {" ".join(pytest_args)}')
    exit_code = pytest.main(pytest_args)
    if collect_only:
        sys.exit(exit_code)

    _write_allure_environment(results_dir, test_type)

    report_dir = _generate_allure_report(test_type, results_dir, run_id)

    if not _is_ci():
        subprocess.Popen(
            f'allure open {report_dir} --host {ALLURE_HOST} --port {ALLURE_PORT}',
            shell=True,
        )

    sys.exit(exit_code)


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError('必须是正整数') from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError('必须是正整数')
    return parsed


def _performance_users(value: str) -> int:
    parsed = _positive_int(value)
    if parsed > MAX_PERFORMANCE_USERS:
        raise argparse.ArgumentTypeError(f'不能超过 {MAX_PERFORMANCE_USERS}')
    return parsed


def _positive_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError('必须是正数') from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError('必须是正数')
    return parsed


def _run_time_seconds(value: str) -> int:
    return int(value[:-1]) * RUN_TIME_UNITS[value[-1]]


def _run_time(value: str) -> str:
    if not RUN_TIME_PATTERN.fullmatch(value):
        raise argparse.ArgumentTypeError('格式必须是正整数加单位，例如 30s、1m、1h')
    if _run_time_seconds(value) > MAX_PERFORMANCE_RUN_SECONDS:
        raise argparse.ArgumentTypeError('不能超过 5m')
    return value


def _validate_performance_limits(scenario: str, users: int, spawn_rate: float, run_time: str) -> None:
    limits = PERFORMANCE_SCENARIOS[scenario]
    if users > limits['max_users']:
        raise ValueError(f'{scenario} 场景并发用户数不能超过 {limits["max_users"]}')
    if _run_time_seconds(run_time) > limits['max_run_seconds']:
        max_minutes = limits['max_run_seconds'] // 60
        raise ValueError(f'{scenario} 场景运行时长不能超过 {max_minutes}m')
    max_spawn_rate = limits['max_spawn_rate']
    if max_spawn_rate is not None and spawn_rate > max_spawn_rate:
        raise ValueError(f'{scenario} 场景用户生成速率不能超过 {max_spawn_rate}/s')


def run_performance(users: int, spawn_rate: float, run_time: str, scenario: str) -> None:
    """性能测试显式入口。

    显式执行 Locust headless，只运行指定性能场景对应的用户模型。
    """
    report_dir = './reports/locust'
    os.makedirs(report_dir, exist_ok=True)
    timestamp = time.strftime('%Y%m%d-%H%M%S')
    run_id = time.strftime('%Y%m%d%H%M%S')
    html_report = f'{report_dir}/{scenario}-{timestamp}.html'
    csv_prefix = f'{report_dir}/{scenario}-{timestamp}'
    log_file = f'{report_dir}/{scenario}-{timestamp}.log'
    user_class = PERFORMANCE_SCENARIOS[scenario]['user_class']
    locust_args = [
        sys.executable,
        '-m',
        'locust',
        '-f',
        './performance/locustfile.py',
        '--headless',
        '--users',
        str(users),
        '--spawn-rate',
        str(spawn_rate),
        '--run-time',
        run_time,
        '--html',
        html_report,
        '--csv',
        csv_prefix,
        '--logfile',
        log_file,
        '--only-summary',
        '--exit-code-on-error',
        '1',
        user_class,
    ]

    print('执行 Locust 性能调试参数: ' + ' '.join(locust_args))
    print(f'场景: {scenario}（{PERFORMANCE_SCENARIOS[scenario]["description"]}）')
    print(f'本轮 run_id: {run_id}')
    print(f'并发用户数: {users}')
    print(f'用户生成速率: {spawn_rate}/s')
    print(f'运行时长: {run_time}')
    print(f'HTML 报告路径: {html_report}')
    print(f'CSV 输出前缀: {csv_prefix}')
    print(f'日志路径: {log_file}')

    env = os.environ.copy()
    env['ERP_PERF_SCENARIO'] = scenario
    env['ERP_PERF_RUN_ID'] = run_id
    env['ERP_PERF_USERS'] = str(users)
    result = subprocess.run(locust_args, env=env)
    if result.returncode != 0:
        print('错误: Locust 性能调试失败，请先分析失败原因，不继续升压')
    sys.exit(result.returncode)


def run_notify(report: str, channel: str) -> None:
    """显式发送测试报告通知。"""
    from shared.notification import notify_report
    try:
        results = notify_report(report, channel=channel)
    except Exception as e:
        print(f'通知发送失败: {e}')
        sys.exit(1)
    for name, result in results:
        print(f'{name} 通知发送结果: {result}')
    sys.exit(0)


if __name__ == '__main__':
    import pytest

    parser = argparse.ArgumentParser(description='ERP 自动化测试统一执行入口')
    parser.add_argument(
        'test_type',
        choices=['api', 'ui', 'e2e', 'preflight', 'performance', 'notify'],
        help='测试类型: api(接口) / ui(UI) / e2e(跨层闭环) / preflight(环境预检) / performance(性能骨架) / notify(显式通知)',
    )
    parser.add_argument(
        '--suite',
        choices=['smoke', 'single', 'business', 'negative', 'exception', 'all'],
        default='all',
        help='回归范围: smoke(冒烟) / single(单接口) / business(业务链路) / negative(异常场景) / all(全量)；exception 为 negative 的旧命令别名',
    )
    parser.add_argument(
        '--browser',
        choices=['chromium', 'firefox', 'webkit'],
        default=None,
        help='浏览器类型（仅对 ui/e2e 有效），默认 chromium，默认 headless',
    )
    parser.add_argument(
        '--headed',
        action='store_true',
        help='有头模式运行（仅对 ui/e2e 有效）',
    )
    parser.add_argument(
        '--collect-only',
        action='store_true',
        help='只收集用例，不执行、不生成报告（仅对 api/ui/e2e 有效）',
    )
    parser.add_argument(
        '--users',
        type=_performance_users,
        default=None,
        help=f'并发用户数，最大 {MAX_PERFORMANCE_USERS}（仅对 performance 有效）',
    )
    parser.add_argument(
        '--spawn-rate',
        type=_positive_float,
        default=None,
        help='用户生成速率，单位 users/s（仅对 performance 有效）',
    )
    parser.add_argument(
        '--run-time',
        type=_run_time,
        default=None,
        help='运行时长，格式如 30s、1m、5m，最长 5m（仅对 performance 有效）',
    )
    parser.add_argument(
        '--scenario',
        choices=list(PERFORMANCE_SCENARIOS.keys()),
        default=None,
        help='性能场景（仅对 performance 有效；写入类场景为受控最小闭环）',
    )
    parser.add_argument(
        '--report',
        default=None,
        help='报告路径（仅对 notify 有效，例如 reports/api_results.xml 或 reports/allure-report/...）',
    )
    parser.add_argument(
        '--channel',
        choices=['all', 'dingtalk', 'email'],
        default=None,
        help='通知渠道（仅对 notify 有效，默认 all）',
    )
    args = parser.parse_args()

    performance_args = any(value is not None for value in (args.users, args.spawn_rate, args.run_time, args.scenario))
    notify_args = any(value is not None for value in (args.report, args.channel))
    if args.test_type != 'performance' and performance_args:
        parser.error('--users / --spawn-rate / --run-time / --scenario 仅对 performance 命令有效')
    if args.test_type != 'notify' and notify_args:
        parser.error('--report / --channel 仅对 notify 命令有效')
    if args.test_type == 'performance' and args.collect_only:
        parser.error('--collect-only 仅对 api/ui/e2e 命令有效')
    if args.test_type == 'performance' and args.suite != 'all':
        parser.error('--suite 仅对 api/ui/e2e 命令有效')
    if args.test_type == 'notify' and args.collect_only:
        parser.error('--collect-only 仅对 api/ui/e2e 命令有效')
    if args.test_type == 'notify' and args.suite != 'all':
        parser.error('--suite 仅对 api/ui/e2e 命令有效')
    if args.test_type in ('ui', 'e2e') and args.suite not in ('smoke', 'all'):
        # 页面和跨层套件范围保持明确，不会误触发其它测试类型或性能任务
        parser.error(f'{args.test_type} 当前只支持 --suite smoke / all')
    if args.test_type not in ('ui', 'e2e') and (args.browser or args.headed):
        parser.error('--browser / --headed 仅对 ui/e2e 命令有效')
    if args.test_type == 'preflight':
        if args.collect_only:
            parser.error('--collect-only 仅对 api/ui/e2e 命令有效')
        from config.settings import preflight
        sys.exit(0 if preflight() else 1)
    if args.test_type == 'performance':
        scenario = args.scenario or 'readonly'
        users = args.users or 1
        spawn_rate = args.spawn_rate or 1.0
        run_time = args.run_time or '1m'
        try:
            _validate_performance_limits(scenario, users, spawn_rate, run_time)
        except ValueError as exc:
            parser.error(str(exc))
        run_performance(
            users,
            spawn_rate,
            run_time,
            scenario,
        )
        sys.exit(0)
    if args.test_type == 'notify':
        if not args.report:
            parser.error('notify 命令必须提供 --report')
        run_notify(args.report, args.channel or 'all')

    run_suite(args.test_type, args.suite, args.browser or '', args.headed, args.collect_only)
