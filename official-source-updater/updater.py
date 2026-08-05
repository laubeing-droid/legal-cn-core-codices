#!/usr/bin/env python3
"""全国官方法源统一更新入口；只写候选区，不修改正式区。"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

TOOL_ROOT = Path(__file__).resolve().parent
DEFAULT_DATABASE_ROOT = TOOL_ROOT.parent / "corpus"
DEFAULT_CONFIG = TOOL_ROOT / "config" / "sources.json"
READY_ADAPTERS = {
    "npc_flk",
    "moj_admin_regulations",
    "national_rules_database",
    "state_council_policy_database",
    "state_council_gazette",
    "central_ministry_websites",
    "spc_website",
    "people_court_case_database",
    "spc_gazette",
    "spp_website",
    "moj_legal_service_case_database",
}
UPDATE_MODES = {"ci_auto", "ci_auto_candidate", "local_manual"}
AUTHENTICATION_MODES = {"none", "local_token"}
FULLTEXT_CAPABILITIES = {"index_only", "index_requires_local_token"}
DATASET_TABLES = {
    "legal_documents.csv",
    "legal_contents.csv",
    "legal_relations.csv",
    "legal_sources.csv",
    "cases.csv",
    "case_holdings.csv",
    "case_legal_references.csv",
    "practice_references.csv",
}
PROXY_ENVIRONMENT_VARIABLES = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)


def enforce_direct_network() -> None:
    """Do not inherit environment proxy configuration into updater subprocesses."""
    for variable_name in PROXY_ENVIRONMENT_VARIABLES:
        os.environ.pop(variable_name, None)


def load_registry(path: Path) -> dict:
    with path.open("r", encoding="utf-8-sig") as file:
        registry = json.load(file)
    if not isinstance(registry.get("official_sources"), list):
        raise ValueError("配置缺少 official_sources 数组")
    return registry


def validate_registry(registry: dict, database_root: Path) -> list[str]:
    errors: list[str] = []
    source_ids: set[str] = set()
    orders: set[int] = set()

    for source in registry["official_sources"]:
        source_id = str(source.get("id") or "").strip()
        order = source.get("order")
        url = str(source.get("url") or "").strip()
        update_mode = source.get("update_mode")
        authentication = source.get("authentication")
        fulltext_capability = source.get("fulltext_capability")
        official_host = str(source.get("official_host") or "").strip()
        content_scope = str(source.get("content_scope") or "").strip()
        target_tables = source.get("target_tables")

        if not source_id:
            errors.append("存在空 source id")
        elif source_id in source_ids:
            errors.append(f"重复 source id：{source_id}")
        source_ids.add(source_id)

        if not isinstance(order, int):
            errors.append(f"{source_id} 的 order 不是整数")
        elif order in orders:
            errors.append(f"重复 order：{order}")
        orders.add(order)

        parsed = urlparse(url)
        allowed_scheme = parsed.scheme == "https" or (
            parsed.scheme == "http" and source.get("allow_http") is True
        )
        if not allowed_scheme or not parsed.netloc:
            errors.append(f"{source_id} 的官网 URL 无效：{url}")
        if official_host != parsed.netloc:
            errors.append(f"{source_id} 的 official_host 与官网 URL 不一致")
        if update_mode not in UPDATE_MODES:
            errors.append(f"{source_id} 的 update_mode 无效：{update_mode}")
        if authentication not in AUTHENTICATION_MODES:
            errors.append(f"{source_id} 的 authentication 无效：{authentication}")
        if fulltext_capability not in FULLTEXT_CAPABILITIES:
            errors.append(
                f"{source_id} 的 fulltext_capability 无效：{fulltext_capability}"
            )
        if not content_scope:
            errors.append(f"{source_id} 缺少 content_scope")
        if not isinstance(target_tables, list) or not target_tables:
            errors.append(f"{source_id} 缺少 target_tables")
        elif unknown_tables := set(target_tables) - DATASET_TABLES:
            errors.append(
                f"{source_id} 包含未知 target_tables：{', '.join(sorted(unknown_tables))}"
            )
        if update_mode == "ci_auto" and authentication != "none":
            errors.append(f"{source_id} 的 ci_auto 来源不得要求认证")
        if source_id == "people_court_case_database" and (
            update_mode != "local_manual" or authentication != "local_token"
        ):
            errors.append("people_court_case_database 必须为 local_manual/local_token")

        for relative in source.get("target_dirs", []):
            target = database_root / Path(relative)
            if not target.is_dir():
                errors.append(f"{source_id} 的目标目录不存在：{target}")

    if READY_ADAPTERS - source_ids:
        errors.append(
            "适配器没有对应来源：" + ", ".join(sorted(READY_ADAPTERS - source_ids))
        )
    return errors


def ci_eligible_source_ids(registry: dict) -> set[str]:
    return {
        source["id"]
        for source in registry["official_sources"]
        if source.get("update_mode") == "ci_auto"
        and source.get("authentication") == "none"
    }


def print_sources(registry: dict) -> None:
    print("序号  状态       来源")
    for source in sorted(registry["official_sources"], key=lambda item: item["order"]):
        status = "READY" if source["id"] in READY_ADAPTERS else "PENDING"
        print(f"{source['order']:>2}    {status:<9} {source['id']}  {source['name']}")


def run_official_index_source(
    source: dict,
    database_root: Path,
    run_root: Path,
    max_pages: int,
) -> dict:
    source_root = run_root / source["id"]
    data_root = source_root / "data"
    candidate_root = source_root / "candidates"
    data_root.mkdir(parents=True, exist_ok=True)
    candidate_root.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        str(TOOL_ROOT / "adapters" / "official_index.py"),
        "--source",
        source["id"],
        "--output",
        str(data_root),
    ]
    if max_pages > 0:
        command.extend(["--max-pages", str(max_pages)])
    if source["id"] == "moj_legal_service_case_database" and max_pages > 1:
        command.extend(
            [
                "--checkpoint",
                str(
                    TOOL_ROOT
                    / "runs"
                    / "_checkpoints"
                    / "moj_legal_service_case_database.json"
                ),
            ]
        )
    fetch = subprocess.run(command, check=False)
    if fetch.returncode == 20:
        meta = json.loads(
            (data_root / "official_index_meta.json").read_text(encoding="utf-8")
        )
        return {
            "source_id": source["id"],
            "status": "BLOCKED_ACCESS",
            "message": meta["blocked_reason"],
            "data_dir": str(data_root),
        }
    if fetch.returncode:
        return {
            "source_id": source["id"],
            "status": "ERROR",
            "message": f"官方索引抓取退出码 {fetch.returncode}",
        }
    meta = json.loads(
        (data_root / "official_index_meta.json").read_text(encoding="utf-8")
    )
    if not meta.get("row_count"):
        return {
            "source_id": source["id"],
            "status": "ERROR",
            "message": "官方索引抓取成功但结果为空",
            "data_dir": str(data_root),
        }

    compare = [
        sys.executable,
        str(TOOL_ROOT / "scripts" / "compare_official_index.py"),
        "--official-csv",
        str(data_root / "official_index.csv"),
        "--output",
        str(candidate_root),
    ]
    for relative in source["target_dirs"]:
        compare.extend(["--formal-dir", str(database_root / Path(relative))])
    comparison = subprocess.run(compare, check=False)
    if comparison.returncode:
        return {
            "source_id": source["id"],
            "status": "ERROR",
            "message": f"正式区比对退出码 {comparison.returncode}",
        }
    summary = json.loads((candidate_root / "比对摘要.json").read_text(encoding="utf-8"))
    if not meta.get("complete"):
        return {
            "source_id": source["id"],
            "status": "PARTIAL_OK",
            "message": f"限量抓取{meta['row_count']}条并生成差异候选；不代表官网全量",
            "candidate_dir": str(candidate_root),
            "counts": summary,
        }
    return {
        "source_id": source["id"],
        "status": "OK",
        "message": f"官方索引{meta['row_count']}条与正式区比对完成",
        "candidate_dir": str(candidate_root),
        "counts": summary,
    }


def run_people_court_case_database(
    source: dict,
    database_root: Path,
    run_root: Path,
    prompt_token: bool,
    max_pages: int,
) -> dict:
    source_root = run_root / source["id"]
    data_root = source_root / "data"
    report_root = source_root / "reports"
    candidate_root = source_root / "candidates"
    data_root.mkdir(parents=True, exist_ok=True)
    report_root.mkdir(parents=True, exist_ok=True)
    candidate_root.mkdir(parents=True, exist_ok=True)

    if not prompt_token and not os.environ.get("RMFYALK_TOKEN", "").strip():
        return {
            "source_id": source["id"],
            "status": "NEEDS_TOKEN",
            "message": "设置 RMFYALK_TOKEN，或使用 --prompt-court-token",
        }

    adapter_root = TOOL_ROOT / "adapters" / "rmfyalk"
    environment = os.environ.copy()
    environment["RMCAL_PROJECT_ROOT"] = str(adapter_root)
    environment["RMCAL_DATA_DIR"] = str(data_root)
    environment["RMCAL_REPORT_DIR"] = str(report_root)

    fetch_command = [
        sys.executable,
        str(adapter_root / "rmfyalk_incremental.py"),
        "--index-only",
    ]
    if prompt_token:
        fetch_command.append("--prompt-token")
    if max_pages > 0:
        fetch_command.extend(["--max-pages", str(max_pages)])

    fetch = subprocess.run(fetch_command, env=environment, check=False)
    if fetch.returncode:
        return {
            "source_id": source["id"],
            "status": "ERROR",
            "message": f"索引抓取退出码 {fetch.returncode}",
        }

    indexes = sorted(data_root.glob("official_index_*.csv"), reverse=True)
    if not indexes:
        return {
            "source_id": source["id"],
            "status": "ERROR",
            "message": "抓取完成但未生成官方索引 CSV",
        }

    compare_command = [
        sys.executable,
        str(TOOL_ROOT / "scripts" / "compare_rmfyalk_formal.py"),
        "--official-csv",
        str(indexes[0]),
        "--output",
        str(candidate_root),
    ]
    for relative in source["target_dirs"]:
        compare_command.extend(["--formal-dir", str(database_root / Path(relative))])

    compare = subprocess.run(compare_command, check=False)
    if compare.returncode:
        return {
            "source_id": source["id"],
            "status": "ERROR",
            "message": f"正式区比对退出码 {compare.returncode}",
        }
    return {
        "source_id": source["id"],
        "status": "OK",
        "message": "官方索引与正式区比对完成",
        "candidate_dir": str(candidate_root),
    }


def run_npc_flk(
    source: dict,
    database_root: Path,
    run_root: Path,
    max_pages: int,
) -> dict:
    source_root = run_root / source["id"]
    data_root = source_root / "data"
    candidate_root = source_root / "candidates"
    data_root.mkdir(parents=True, exist_ok=True)
    candidate_root.mkdir(parents=True, exist_ok=True)

    fetch_command = [
        sys.executable,
        str(TOOL_ROOT / "adapters" / "flk" / "flk_index.py"),
        "--output",
        str(data_root),
    ]
    if max_pages > 0:
        fetch_command.extend(["--max-pages", str(max_pages)])
    fetch = subprocess.run(fetch_command, check=False)
    if fetch.returncode:
        return {
            "source_id": source["id"],
            "status": "ERROR",
            "message": f"官方索引抓取退出码 {fetch.returncode}",
        }

    meta_path = data_root / "flk_official_index_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if not meta.get("complete"):
        return {
            "source_id": source["id"],
            "status": "PARTIAL_OK",
            "message": f"调试抓取完成：{meta['fetched_rows']}/{meta['official_total']}，未执行正式区比对",
            "data_dir": str(data_root),
        }

    compare_command = [
        sys.executable,
        str(TOOL_ROOT / "scripts" / "compare_flk_formal.py"),
        "--official-csv",
        str(data_root / "flk_official_index.csv"),
        "--output",
        str(candidate_root),
    ]
    for relative in source["target_dirs"]:
        compare_command.extend(["--formal-dir", str(database_root / Path(relative))])
    compare = subprocess.run(compare_command, check=False)
    if compare.returncode:
        return {
            "source_id": source["id"],
            "status": "ERROR",
            "message": f"正式区比对退出码 {compare.returncode}",
        }
    comparison = json.loads(
        (candidate_root / "flk_比对摘要.json").read_text(encoding="utf-8")
    )
    return {
        "source_id": source["id"],
        "status": "OK",
        "message": f"全量官方索引{meta['fetched_rows']}条与正式区比对完成",
        "candidate_dir": str(candidate_root),
        "counts": comparison,
    }


def write_run_summary(run_root: Path, results: list[dict]) -> None:
    payload = {
        "finished_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "results": results,
    }
    (run_root / "run_summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = ["# 官方法源更新运行结果", ""]
    lines.extend(
        f"- `{item['source_id']}`：**{item['status']}** — {item['message']}"
        for item in results
    )
    (run_root / "run_summary.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def run_sources(
    registry: dict,
    database_root: Path,
    selected_ids: list[str],
    prompt_token: bool,
    court_max_pages: int,
    flk_max_pages: int,
    max_pages: int,
) -> int:
    sources = {source["id"]: source for source in registry["official_sources"]}
    requested = list(sources) if not selected_ids or "all" in selected_ids else selected_ids
    unknown = sorted(set(requested) - set(sources))
    if unknown:
        raise ValueError("未知来源：" + ", ".join(unknown))

    run_root = TOOL_ROOT / "runs" / datetime.now().strftime("%Y%m%d_%H%M%S")
    run_root.mkdir(parents=True)
    results: list[dict] = []

    for source_id in requested:
        source = sources[source_id]
        if source_id == "npc_flk":
            result = run_npc_flk(source, database_root, run_root, flk_max_pages)
        elif source_id == "people_court_case_database":
            result = run_people_court_case_database(
                source, database_root, run_root, prompt_token, court_max_pages
            )
        else:
            result = run_official_index_source(
                source, database_root, run_root, max_pages
            )
        results.append(result)
        print(f"{source_id}: {result['status']} - {result['message']}")

    write_run_summary(run_root, results)
    print(f"run={run_root}")
    statuses = {result["status"] for result in results}
    if "ERROR" in statuses:
        return 1
    if "NEEDS_TOKEN" in statuses:
        return 2
    if "BLOCKED_ACCESS" in statuses:
        return 5
    if "PARTIAL_OK" in statuses:
        return 4
    return 0


def main() -> int:
    enforce_direct_network()
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["list", "validate", "run"])
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--database-root", type=Path, default=DEFAULT_DATABASE_ROOT)
    parser.add_argument("--source", action="append", default=[])
    parser.add_argument("--prompt-court-token", action="store_true")
    parser.add_argument("--court-max-pages", type=int, default=0)
    parser.add_argument("--flk-max-pages", type=int, default=0)
    parser.add_argument("--max-pages", type=int, default=0)
    args = parser.parse_args()

    registry = load_registry(args.config.resolve())
    database_root = args.database_root.resolve()
    errors = validate_registry(registry, database_root)
    if errors:
        print("\n".join(f"ERROR: {error}" for error in errors), file=sys.stderr)
        return 1

    if args.command == "list":
        print_sources(registry)
        return 0
    if args.command == "validate":
        print(f"official_sources={len(registry['official_sources'])}")
        print(f"ready_adapters={len(READY_ADAPTERS)}")
        print(f"database_root={database_root}")
        print("validation=PASS")
        return 0
    return run_sources(
        registry,
        database_root,
        args.source,
        args.prompt_court_token,
        args.court_max_pages,
        args.flk_max_pages,
        args.max_pages,
    )


if __name__ == "__main__":
    raise SystemExit(main())
