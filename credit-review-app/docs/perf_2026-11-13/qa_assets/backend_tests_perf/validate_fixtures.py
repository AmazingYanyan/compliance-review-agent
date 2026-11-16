#!/usr/bin/env python3
"""QA 性能试验 · fixture 自检工具（资产 2/4 的附带工具）。

做三件事：
1. 校验 ``backend/tests/perf/`` 下所有 JSON 配置/fixture 语法合法；
2. 校验 ``fixed_responses.json`` 里每个响应模板符合 ``TextSearchOutput`` 结构、
   且所有 ``{{...}}`` 占位符都能被模拟服务渲染成合法值（不残留 ``{{``）；
3. 校验 ``response_ref`` 路径能从 fixture 根解析到具体响应对象。

不连数据库、不调用真实模型、不改业务代码。输出机器可读 JSON。

用法：
    python3 backend/tests/perf/validate_fixtures.py \
        --out backend/tests/perf/evidence/validate_fixtures.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from mock_llm_server import (  # noqa: E402
    INVALID_BLOCK_ID,
    RequestInfo,
    _build_context,
    _resolve_ref,
    _walk_render,
)
import uuid  # noqa: E402

PLACEHOLDER_RE = re.compile(r"\{\{([^}]+)\}\}")
UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _fake_context() -> dict[str, Any]:
    info = RequestInfo(
        arrival_seq=1,
        arrived_at=_now_iso(),
        arrived_monotonic_ms=0.0,
        schema_name="text_search_output",
        check_item_id="charter.business_scope",
        batch_check_ids=["charter.business_scope"],
        block_ids=[str(uuid.UUID(int=0x2000 + i)) for i in range(4)],
        window_index=0,
        attempt=0,
        tag=None,
        response_format_type="json_schema",
        model="qa-mock-model",
        user_chars=100,
        raw_body_sha256="x",
    )
    return _build_context(info)


def _check_response(tag: str, r: Any, errors: list[str]) -> int:
    """返回该响应里的 source_refs 数量。"""
    if not isinstance(r, dict):
        errors.append(f"{tag}: 不是 dict")
        return 0
    for key in ("bundle_id", "check_results"):
        if key not in r:
            errors.append(f"{tag}: 缺字段 {key}")
    refs = 0
    for i, c in enumerate(r.get("check_results", [])):
        for k in ("check_item_id", "outcome", "evidence"):
            if k not in c:
                errors.append(f"{tag}.check_results[{i}]: 缺字段 {k}")
        if c.get("outcome") not in ("found", "not_found"):
            errors.append(f"{tag}.check_results[{i}]: outcome 非法 {c.get('outcome')}")
        for j, ev in enumerate(c.get("evidence", [])):
            for k in ("source_refs", "relation_status", "relevance_reason"):
                if k not in ev:
                    errors.append(f"{tag}.check_results[{i}].evidence[{j}]: 缺字段 {k}")
            src = ev.get("source_refs", [])
            if not src:
                errors.append(f"{tag}.check_results[{i}].evidence[{j}]: source_refs 为空")
            for k2, ref in enumerate(src):
                for k in ("block_id", "start_char", "end_char"):
                    if k not in ref:
                        errors.append(
                            f"{tag}.check_results[{i}].evidence[{j}].source_refs[{k2}]: 缺字段 {k}"
                        )
                refs += 1
    return refs


def _collect_responses(node: Any, path: list[Any]) -> list[tuple[str, Any]]:
    out: list[tuple[str, Any]] = []
    if isinstance(node, dict):
        if "check_results" in node and "bundle_id" in node:
            out.append((".".join(str(p) for p in path), node))
        for k, v in node.items():
            out.extend(_collect_responses(v, path + [k]))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            out.extend(_collect_responses(v, path + [i]))
    return out


# 架构师提醒：错误码断言字段必须与 detail.code 用 == 严格相等比较，
# 值只能是纯字面量；「（架构师定值）」等来源说明一律放独立 *_note 字段。
ERROR_CODE_ASSERT_FIELDS = {
    "complete_task_code",
    "complete_task_expected_code",
    "expected_complete_task_code",
    "complete_409_code",
}
ERROR_CODE_LITERAL_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


def _check_error_code_literals(
    loaded: dict[str, Any], errors: list[str]
) -> tuple[int, list[str]]:
    """返回 (已检查字段数, 跳过的历史证据文件名)。

    ``evidence/`` 下是修订前 HEAD 的**历史实测快照**，值保持原样不篡改；
    字面量约束只作用于活动资产（fixtures / 配置 / 前端拦截 fixture）。
    """
    checked = 0
    skipped: list[str] = []

    def walk(obj: Any, tag: str) -> None:
        nonlocal checked
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key in ERROR_CODE_ASSERT_FIELDS and isinstance(value, str):
                    checked += 1
                    if not ERROR_CODE_LITERAL_RE.match(value):
                        errors.append(
                            f"{tag}: 错误码断言字段 {key} 不是纯字面量 {value!r}；"
                            "说明请放独立 *_note 字段，#7 会用 == 严格相等断言"
                        )
                walk(value, tag)
        elif isinstance(obj, list):
            for item in obj:
                walk(item, tag)

    for path, data in loaded.items():
        if "evidence" in Path(path).parts:
            skipped.append(Path(path).name)
            continue
        walk(data, Path(path).name)
    return checked, skipped


def _check_two_import_independence(root: Path,
                                    errors: list[str]) -> dict[str, Any]:
    """PM 严谨性确认：两次导入必须是两个独立 task/file，内容 hash 相等不是自比对。

    * A/B 独立 ``Task.id`` / ``TaskFile.id``（导入时生成的随机 UUID）；
    * 两次 ``import_ocr_json`` 各自生成随机 ``OcrBlock.id`` —— 由
      ``window_text_sha256_run_bound``（请求 hash，含 block_id=<UUID>）A != B 证明；
    * 内容 hash / K2 聚合 / 有序清单 A == B 是在这两个独立数据集上分别计算后比对；
    * 共用的 ``OCR_JSON_SHA256`` 是「同一份文件内容」的稳定内容标识，不是导入随机 UUID。
    """
    path = root / "evidence" / "compare_two_imports.json"
    if not path.is_file():
        return {"status": "skipped", "reason": "未找到 compare_two_imports.json"}
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        errors.append(f"compare_two_imports.json 解析失败: {type(exc).__name__}: {exc}")
        return {"status": "error"}

    iso = d.get("isolation") or {}
    a, b = d.get("A") or {}, d.get("B") or {}
    id_a, id_b = iso.get("A") or {}, iso.get("B") or {}
    ha = [w.get("window_text_sha256_run_bound")
          for w in a.get("actual_windows", {}).get("search", [])]
    hb = [w.get("window_text_sha256_run_bound")
          for w in b.get("actual_windows", {}).get("search", [])]
    checks: dict[str, bool] = {
        "distinct_task_ids": bool(
            id_a.get("task_id") and id_b.get("task_id")
            and id_a["task_id"] != id_b["task_id"]
        ),
        "distinct_file_ids": bool(
            id_a.get("file_id") and id_b.get("file_id")
            and id_a["file_id"] != id_b["file_id"]
        ),
        "request_hash_differs_between_imports": bool(ha) and ha != hb,
        "content_hash_equal_across_imports": bool(
            a.get("content_hash_excluding_import_uuid")
            and a.get("content_hash_excluding_import_uuid")
            == b.get("content_hash_excluding_import_uuid")
        ),
        "k2_aggregate_equal_across_imports": bool(
            a.get("content_hash_k2_business_aggregate")
            and a.get("content_hash_k2_business_aggregate")
            == b.get("content_hash_k2_business_aggregate")
        ),
        "ordered_list_equal_across_imports": bool(
            a.get("ordered_block_list_sha256")
            and a.get("ordered_block_list_sha256")
            == b.get("ordered_block_list_sha256")
        ),
    }
    for name, ok in checks.items():
        if not ok:
            errors.append(f"两次导入独立性核查失败: {name}")
    return {
        "status": "checked",
        "file": path.name,
        "checks": checks,
        "note": (
            "common OCR_JSON_SHA256 是同一份文件内容的稳定标识（K1 file_key），不是导入随机 UUID；"
            "content_hash_excluding_import_uuid 既不含随机 UUID 也不含文件 sha256。"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="QA fixture 自检")
    parser.add_argument("--perf-dir", default=str(HERE))
    parser.add_argument("--out", default=str(HERE / "evidence" / "validate_fixtures.json"))
    args = parser.parse_args()

    root = Path(args.perf_dir)
    project_root = root.parents[2] if len(root.parents) >= 3 else root
    errors: list[str] = []
    json_files = sorted(root.rglob("*.json"))
    # 前端 Chrome fixture 也含错误码断言字段，一并纳入字面量检查
    extra_files: list[Path] = []
    frontend_fixture = (
        project_root / "frontend/tests/perf/fixtures/coverage_incomplete.results.json"
    )
    if frontend_fixture.is_file():
        extra_files.append(frontend_fixture)
    loaded: dict[str, Any] = {}
    for p in json_files + extra_files:
        try:
            loaded[str(p)] = json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{p.name}: JSON 解析失败 {type(exc).__name__}: {exc}")

    fixed_path = root / "fixtures" / "fixed_responses.json"
    fixed = loaded.get(str(fixed_path))
    response_count = 0
    ref_count = 0
    if fixed is None:
        errors.append("缺少 fixtures/fixed_responses.json")
    else:
        # 只校验真正会被模拟服务消费的响应模板；
        # contract_facts / placeholder_rules 等是文档示例段，不是响应模板。
        responses: list[tuple[str, Any]] = []
        for section in ("equivalence_pair", "scenarios"):
            if section in fixed:
                responses.extend(_collect_responses(fixed[section], [section]))
        response_count = len(responses)
        ctx = _fake_context()
        for tag, template in responses:
            ref_count += _check_response(tag, template, errors)
            rendered = _walk_render(template, ctx)
            text = json.dumps(rendered, ensure_ascii=False)
            left = PLACEHOLDER_RE.findall(text)
            if left:
                errors.append(f"{tag}: 渲染后仍残留占位符 {left}")
            # 渲染后所有 source_refs.block_id 必须是合法 UUID（含 INVALID_BLOCK 固定值）
            for c in rendered.get("check_results", []):
                for ev in c.get("evidence", []):
                    for ref in ev.get("source_refs", []):
                        bid = ref.get("block_id", "")
                        if not UUID_RE.match(str(bid)):
                            errors.append(f"{tag}: 渲染后 block_id 不是合法 UUID: {bid}")
            # 无效块占位符必须渲染成固定哨兵值
            if "{{INVALID_BLOCK}}" in json.dumps(template, ensure_ascii=False):
                if INVALID_BLOCK_ID not in text:
                    errors.append(f"{tag}: INVALID_BLOCK 未渲染成哨兵 UUID")

    # response_ref 路径可解析性
    refs_checked = 0
    for p, data in loaded.items():
        if not isinstance(data, dict):
            continue
        for rule in (data.get("rules") or []):
            ref = rule.get("response_ref") if isinstance(rule, dict) else None
            if isinstance(ref, dict) and ref.get("file") and ref.get("path"):
                target = (root / str(ref["file"])).resolve()
                try:
                    obj = json.loads(target.read_text(encoding="utf-8"))
                    value = _resolve_ref(obj, list(ref["path"]))
                    _check_response(f"response_ref:{Path(p).name}", value, errors)
                    refs_checked += 1
                except Exception as exc:  # noqa: BLE001
                    errors.append(
                        f"response_ref {Path(p).name}: 解析失败 "
                        f"{type(exc).__name__}: {exc}"
                    )
        example = data.get("_response_ref_example")
        if isinstance(example, dict) and example.get("response_ref"):
            ref = example["response_ref"]
            target = (root / str(ref["file"])).resolve()
            try:
                obj = json.loads(target.read_text(encoding="utf-8"))
                value = _resolve_ref(obj, list(ref["path"]))
                _check_response("example._response_ref_example", value, errors)
                refs_checked += 1
            except Exception as exc:  # noqa: BLE001
                errors.append(f"示例 response_ref 解析失败: {type(exc).__name__}: {exc}")

    # 错误码断言入口一致性：所有断言字段必须是纯字面量
    error_codes_checked, skipped_evidence = _check_error_code_literals(loaded, errors)
    # 两次导入独立性：内容 hash 相等必须发生在两个独立 task/file 上，不是自比对
    two_import_check = _check_two_import_independence(root, errors)
    # .py 里的同名断言字段也一并检查（fault_injection.py::_build_expected）
    fi_path = root / "fault_injection.py"
    if fi_path.is_file():
        for m in re.finditer(
            r'"expected_complete_task_code"\s*:\s*"([^"]+)"',
            fi_path.read_text(encoding="utf-8"),
        ):
            error_codes_checked += 1
            if not ERROR_CODE_LITERAL_RE.match(m.group(1)):
                errors.append(
                    f"fault_injection.py: expected_complete_task_code 不是纯字面量 "
                    f"{m.group(1)!r}；说明请放独立 note 字段"
                )

    evidence = {
        "schema_version": "qa-validate-fixtures-1",
        "ran_at": _now_iso(),
        "scope": "静态自检，不连 DB、不调用真实模型、不改业务代码",
        "json_file_count": len(json_files) + len(extra_files),
        "json_files": (
            [str(p.relative_to(root)) for p in json_files]
            + [str(p.relative_to(project_root)) for p in extra_files]
        ),
        "response_template_count": response_count,
        "source_ref_count": ref_count,
        "response_ref_checked": refs_checked,
        "error_code_assert_fields_checked": error_codes_checked,
        "error_code_assert_fields": sorted(ERROR_CODE_ASSERT_FIELDS),
        "error_code_literal_rule": "^[A-Z][A-Z0-9_]*$（说明放独立 *_note 字段）",
        "error_code_check_skipped_evidence_files": skipped_evidence,
        "error_code_check_note": (
            "evidence/ 下是修订前 HEAD 的历史实测快照，值原样保留不篡改；"
            "字面量约束只作用于活动资产。"
        ),
        "two_import_independence_check": two_import_check,
        "errors": errors,
        "summary": {
            "total_errors": len(errors),
            "status": "PASS" if not errors else "FAIL",
        },
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"fixture 自检：{evidence['summary']['status']}，"
          f"JSON {len(json_files) + len(extra_files)} 个，响应模板 {response_count} 个，"
          f"source_ref {ref_count} 个，response_ref {refs_checked} 个，"
          f"错误码断言字段 {error_codes_checked} 个，"
          f"两次导入独立性 {two_import_check['status']}，错误 {len(errors)} 项")
    for e in errors[:20]:
        print(" -", e)
    print(f"证据：{out}")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
