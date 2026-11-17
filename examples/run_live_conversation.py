"""Run a frozen synthetic user script against a real provider and local v2 API.

Raw dialogue, requests and SQLite stay in --output, never in source fixtures.
Usage: python examples/run_live_conversation.py --api-key-file /private/key.md --output /private/run
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import html
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from memory_system.conversation import ConversationHost, V2MemoryGateway
from memory_system.providers import ChatClient, ProviderError


def save_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


class RecordedProvider:
    def __init__(self, client: ChatClient, output: Path, *, max_calls: int, max_cost: float) -> None:
        self.client, self.output = client, output
        self.max_calls, self.max_cost = max_calls, max_cost
        self.calls, self.prompt_tokens, self.completion_tokens = 0, 0, 0
        self.estimated_peak_cost_usd = 0.0
        self.stage = "initial"

    def complete(self, messages: list[dict], **options):
        # Conservative all-input-cache-miss peak tariff; this is not a bill.
        reserved = sum(len(m["content"]) for m in messages) * 0.3 / 1_000_000
        reserved += options.get("max_tokens", 1200) * 1.2 / 1_000_000
        if self.calls >= self.max_calls or self.estimated_peak_cost_usd + reserved > self.max_cost:
            raise RuntimeError("local_provider_budget_exceeded")
        self.calls += 1
        try:
            result = self.client.complete(messages, **options)
        except ProviderError as exc:
            record = {"call": self.calls, "stage": self.stage, "status": "failed",
                      "code": exc.code, "status_code": exc.status_code,
                      "request_metadata": exc.request_metadata}
            self._record(record)
            raise
        record = {"call": self.calls, "stage": self.stage, "status": "completed", **asdict(result)}
        usage = result.usage
        self.prompt_tokens += int(usage.get("prompt_tokens", 0))
        self.completion_tokens += int(usage.get("completion_tokens", 0))
        self.estimated_peak_cost_usd = (self.prompt_tokens * 0.3 + self.completion_tokens * 1.2) / 1_000_000
        self._record(record)
        return result

    def _record(self, record: dict) -> None:
        with (self.output / "provider_calls.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")


def render_transcripts(output: Path, scenario: dict, results: list[dict]) -> None:
    lines = ["# 真实模型项目续接对话", "", scenario["synthetic_notice"], "",
             "用户侧为预先编排的合成脚本；以下助手回答均为真实 API 原文，未改写。",
             "两组均只保留同会话最近两轮对话；会话切换时清空。记忆组额外经过实际 v2 记忆读写。", ""]
    cards = []
    for row in results:
        turn_id, arm = row["turn_id"], row["arm"]
        answer = row.get("answer", {}).get("content", "[调用未完成；见错误记录]")
        lines += [f"## {turn_id} · {arm}", "", f"**用户：** {row['user_text']}", "", "**DeepSeek：**", "", answer, ""]
        write_ops = row.get("ingest", {}).get("operations", [])
        if arm == "memory":
            changes = ", ".join(f"{op['operation']}:{op['candidate']['key']}" for op in write_ops) or "无持久化候选"
            lines += [f"记忆写入：`{changes}`", ""]
        cards.append(f'<article data-arm="{arm}"><header>{html.escape(turn_id)} · {arm}</header>'
                     f'<p class="user">{html.escape(row["user_text"])}</p><pre>{html.escape(answer)}</pre>'
                     f'<details><summary>本轮证据</summary><pre>{html.escape(json.dumps({"timestamp": row["timestamp"], "status": row["status"], "model": row.get("answer",{}).get("model"), "source_turns": [x.get("source_turn_ids") for x in row.get("retrieval_after",{}).get("candidates",[])]}, ensure_ascii=False, indent=2))}</pre></details></article>')
    (output / "transcript.md").write_text("\n".join(lines), encoding="utf-8")
    page = '''<!doctype html><html lang="zh"><meta charset="utf-8"><title>EvolveMemory 实际多轮对话</title>
<style>body{max-width:1000px;margin:40px auto;padding:0 20px;background:#f5f5f7;color:#222;font:16px/1.65 system-ui}h1{font-size:30px}nav{position:sticky;top:0;background:#f5f5f7;padding:14px 0}button{padding:9px 18px;margin-right:8px;border:1px solid #ccc;border-radius:20px;background:white;cursor:pointer}article{background:white;border:1px solid #ddd;border-radius:14px;padding:24px;margin:20px 0}header{font-weight:700;color:#6352a0}.user{padding:12px 16px;background:#f1eff7;border-radius:8px}pre{font:inherit;white-space:pre-wrap;overflow-wrap:anywhere}summary{color:#666;cursor:pointer}details pre{font:12px/1.5 monospace}</style>
<h1>EvolveMemory · 实际多轮对话</h1><p>合成用户脚本，真实 DeepSeek 回答。保留全部回答，不修饰失败；记忆组与近期上下文对照均为两轮窗口。真实用户体验尚需你评判。</p>
<nav><button onclick="filter('all')">全部对照</button><button onclick="filter('memory')">记忆组</button><button onclick="filter('recent_only')">近期对话组</button></nav>'''
    page += "".join(cards) + "<script>function filter(a){document.querySelectorAll('article').forEach(e=>e.hidden=a!=='all'&&e.dataset.arm!==a)}</script></html>"
    (output / "transcript.html").write_text(page, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", type=Path, default=ROOT / "examples/scenarios/project_continuation_zh.json")
    parser.add_argument("--api-key-file", type=Path)
    parser.add_argument("--key-index", type=int, default=0)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default="deepseek-flash")
    parser.add_argument("--max-turns", type=int)
    parser.add_argument("--max-calls", type=int, default=100)
    parser.add_argument("--max-cost-usd", type=float, default=2.0)
    args = parser.parse_args()
    if args.model != "deepseek-flash":
        parser.error("This evaluation tariff is pinned to deepseek-flash; configure other models separately.")
    if args.output.exists() and any(args.output.iterdir()):
        parser.error("Output must be new/empty to preserve previous runs.")
    args.output.mkdir(parents=True, mode=0o700, exist_ok=True)
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if args.api_key_file:
        keys = re.findall(r"sk-[A-Za-z0-9_-]{16,}", args.api_key_file.read_text())
        if args.key_index < 0 or args.key_index >= len(keys):
            parser.error("Requested key index is unavailable.")
        key = keys[args.key_index]
    if not key:
        parser.error("Set DEEPSEEK_API_KEY or supply a private --api-key-file.")
    scenario_bytes = args.scenario.read_bytes()
    scenario = json.loads(scenario_bytes)
    save_json(args.output / "scenario.json", scenario)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]
    env = {k: v for k, v in os.environ.items() if k != "DEEPSEEK_API_KEY"}
    env.update(AME_DATA_DIR=str(args.output / "data"), AME_SQLITE_DB_PATH=str(args.output / "data/memory.sqlite3"), AME_JSON_SESSION_DIR=str(args.output / "data/sessions"))
    server_log = (args.output / "memory-server.log").open("w")
    server = subprocess.Popen([sys.executable, "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"], cwd=ROOT, env=env, stdout=server_log, stderr=server_log)
    base = f"http://127.0.0.1:{port}"
    gateway = None
    client = ChatClient(key, model=args.model, timeout_seconds=40, max_retries=1)
    provider = RecordedProvider(client, args.output, max_calls=args.max_calls, max_cost=args.max_cost_usd)
    results, errors = [], []
    started = datetime.now(timezone.utc).isoformat()
    try:
        for _ in range(100):
            try:
                if httpx.get(base + "/health", timeout=1).status_code == 200: break
            except httpx.HTTPError: pass
            if server.poll() is not None: raise RuntimeError("memory_server_exited")
            time.sleep(0.1)
        else: raise RuntimeError("memory_server_start_timeout")
        gateway = V2MemoryGateway(base, "synthetic-" + uuid4().hex, scenario["project_id"])
        settings = gateway.enable_project()
        hosts = {"memory": ConversationHost(provider, memory=gateway),
                 "recent_only": ConversationHost(provider, memory=None)}
        base_time = datetime(2026, 11, 16, 10, tzinfo=timezone.utc)
        turns = scenario["turns"][:args.max_turns] if args.max_turns else scenario["turns"]
        for index, turn in enumerate(turns):
            timestamp = (base_time + timedelta(days=turn["day_offset"], hours=turn.get("hours_offset", 0), minutes=index)).isoformat()
            for arm, host in hosts.items():
                provider.stage = f"{turn['id']}:{arm}"
                try:
                    # The only scenario fields available to the host are below.
                    row = host.turn(text=turn["text"], turn_id=turn["id"], session_id=turn["session_id"], timestamp=timestamp)
                except Exception as exc:
                    row = dict(getattr(host, "last_trace", {}))
                    row.update(status="failed", error_type=type(exc).__name__, error_code=getattr(exc, "code", "host_failure"))
                    errors.append({"turn_id": turn["id"], "arm": arm, "type": type(exc).__name__, "code": getattr(exc, "code", "host_failure")})
                row["arm"] = arm
                results.append(row)
                save_json(args.output / f"{index+1:02d}-{arm}.json", row)
                print(json.dumps({"turn": turn["id"], "arm": arm, "status": row["status"], "calls": provider.calls,
                                  "characters": len(row.get("answer", {}).get("content", ""))}, ensure_ascii=False), flush=True)
                if row["status"] == "failed": raise RuntimeError("run_stopped_preserving_failure")
        save_json(args.output / "memory-export.json", gateway.export())
        save_json(args.output / "settings.json", settings)
    except Exception as exc:
        if not errors: errors.append({"type": type(exc).__name__, "code": getattr(exc, "code", "run_failure")})
    finally:
        if gateway: gateway.close()
        client.close()
        server.terminate()
        try: server.wait(timeout=10)
        except subprocess.TimeoutExpired: server.kill(); server.wait()
        server_log.close()
        render_transcripts(args.output, scenario, results)
        manifest = {"started_at": started, "finished_at": datetime.now(timezone.utc).isoformat(),
                    "model_requested": args.model, "scenario_sha256": sha256(scenario_bytes).hexdigest(),
                    "code_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                    "working_tree_diff_sha256": sha256(subprocess.check_output(["git", "diff", "HEAD"], cwd=ROOT)).hexdigest(),
                    "history_pairs": 2, "expected_turns": len(turns) if 'turns' in locals() else 0,
                    "completed_replies": sum(x.get("status") == "completed" for x in results), "errors": errors,
                    "provider_calls": provider.calls, "prompt_tokens": provider.prompt_tokens,
                    "completion_tokens": provider.completion_tokens,
                    "estimated_peak_cost_usd": round(provider.estimated_peak_cost_usd, 6),
                    "pricing_source": "https://api-docs.deepseek.com/quick_start/pricing/",
                    "billing_note": "Conservative peak, all input cache-miss estimate; not an account bill. Failed calls may also be billed.",
                    "synthetic_user_turns": True, "real_provider": True, "expectations_sent_to_model": False}
        save_json(args.output / "manifest.json", manifest)
        print(json.dumps(manifest, ensure_ascii=False), flush=True)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
