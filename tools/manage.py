"""鱼鱼第一阶段：通过本机 AstrBot API 配置人格与原生文字节奏。标准库，无插件。"""
import argparse
import contextlib
import copy
import fnmatch
import getpass
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / ".local"
RULE_KEY = "session_service_config"


class PackError(Exception):
    pass


class ApiError(PackError):
    def __init__(self, method, path, code):
        self.code = code
        super().__init__(f"接口失败：{method} {path.split('?')[0]}，HTTP {code}。检查版本、登录权限和后台日志。")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def normalize_url(raw):
    if "://" not in raw:
        raw = "http://" + raw
    try:
        p = urllib.parse.urlsplit(raw)
        port = p.port
    except ValueError:
        raise PackError("后台地址格式错误。") from None
    if (p.scheme not in ("http", "https") or p.hostname not in ("localhost", "127.0.0.1", "::1")
            or p.username or p.password or p.path not in ("", "/") or p.query or p.fragment):
        raise PackError("请在运行 AstrBot 的电脑上执行，只支持本机后台地址，不支持子路径或远程后台。")
    host = "[::1]" if p.hostname == "::1" else p.hostname
    return f"{p.scheme}://{host}" + (f":{port}" if port else "")


class Api:
    def __init__(self, base, token=None):
        self.base = normalize_url(base)
        self.token = token
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def call(self, method, path, body=None):
        data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        request = urllib.request.Request(self.base + "/api/v1" + path, data=data, method=method, headers=headers)
        try:
            with self.opener.open(request, timeout=60) as response:
                status, payload = response.status, response.read()
        except urllib.error.HTTPError as error:
            # Never print server bodies: they can contain credentials or full configuration.
            raise ApiError(method, path, error.code) from None
        except (urllib.error.URLError, OSError, TimeoutError):
            raise PackError("后台连接失败或请求超时。写入结果可能尚不明确；保留 .local，先检查或恢复，勿删除记录后重装。") from None
        try:
            out = json.loads(payload)
        except (ValueError, UnicodeDecodeError):
            raise PackError("后台返回非 JSON，请核对地址和 AstrBot 版本。") from None
        if not isinstance(out, dict) or out.get("status") != "ok" or "data" not in out:
            raise ApiError(method, path, status)
        return out["data"]

    def login(self, username, password):
        for candidate in (password, hashlib.md5(password.encode()).hexdigest()):
            try:
                out = self.call("POST", "/auth/login", {"username": username, "password": candidate})
            except ApiError as error:
                if error.code not in (200, 400, 401, 403):
                    raise
                continue
            if isinstance(out, dict) and isinstance(out.get("token"), str) and out["token"]:
                self.token = out["token"]
                return
        raise PackError("登录未成功。检查账号密码；启用二次验证时可用本地 API Key 文件，或按手动说明操作。")


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    with temp.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    try:
        temp.chmod(0o600)
    except OSError:
        pass
    os.replace(temp, path)


def state_path(base, origin):
    return LOCAL / (hashlib.sha256((base + "\n" + origin).encode()).hexdigest()[:24] + ".json")


@contextlib.contextmanager
def mutation_lock():
    LOCAL.mkdir(exist_ok=True)
    lock = LOCAL / "operation.lock"
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise PackError("另一个导入/恢复可能正在运行。若此前异常退出，确认进程已经结束后，仅移除 .local/operation.lock。") from None
    try:
        os.write(descriptor, str(os.getpid()).encode())
        os.close(descriptor)
        yield
    finally:
        lock.unlink(missing_ok=True)


def validate_origin(origin):
    parts = origin.split(":", 2)
    if (len(parts) != 3 or not all(parts) or parts[1] not in ("FriendMessage", "GroupMessage")
            or any(c.isspace() or c in "*?[]" for c in origin)):
        raise PackError("填写 /sid 返回的完整、单个 QQ 会话 UMO，不要填 QQ 号或通配符。")
    return origin


def canonical_prompt(text):
    if not isinstance(text, str) or not text.strip():
        raise PackError("人格文本为空或格式错误。")
    # Match AstrBot PersonaService.create_persona; do not normalize internal text.
    return text.strip()


def verify_files():
    sums = read_json(ROOT / "SHA256SUMS.json")
    required = {"tools/manage.py", "settings/pack.json", "persona/鱼鱼.md", "INSTALL.md"}
    if not isinstance(sums, dict) or not required.issubset(sums):
        raise PackError("文件校验清单不完整。请重新下载候选包。")
    for rel, expected in sums.items():
        path = (ROOT / rel).resolve()
        if ROOT not in path.parents or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise PackError(f"文件校验失败：{rel}。若是有意修改，请运行构建工具重新生成校验清单。")
    return len(sums)


def path_get(obj, dotted):
    for key in dotted.split("."):
        if not isinstance(obj, dict) or key not in obj:
            raise PackError(f"此版本缺少配置项 {dotted}，停止自动配置，请按 INSTALL.md 手动设置。")
        obj = obj[key]
    return obj


def path_set(obj, dotted, value):
    keys = dotted.split(".")
    parent = obj
    for key in keys[:-1]:
        parent = parent[key]
    parent[keys[-1]] = copy.deepcopy(value)


def read_profile(api, profile_id):
    out = api.call("GET", "/config-profiles/" + urllib.parse.quote(profile_id, safe=""))
    if not isinstance(out, dict) or not isinstance(out.get("config"), dict):
        raise PackError("配置文件接口结构不兼容。")
    return out["config"]


def profiles(api):
    out = api.call("GET", "/config-profiles")
    rows = out.get("info_list") if isinstance(out, dict) else None
    if not isinstance(rows, list) or not all(isinstance(x, dict) and isinstance(x.get("id"), str) for x in rows):
        raise PackError("配置文件列表接口结构不兼容。")
    return rows


def routes(api):
    out = api.call("GET", "/config-routes")
    mapping = out.get("routing") if isinstance(out, dict) else None
    if not isinstance(mapping, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in mapping.items()):
        raise PackError("配置路由接口结构不兼容。")
    return mapping


def matching_profile(mapping, origin):
    target = origin.split(":", 2)
    # Official routing uses FIRST matching pattern, not longest/exact match.
    for pattern, profile in mapping.items():
        parts = pattern.split(":", 2)
        if len(parts) == 3 and all(p == "" or fnmatch.fnmatchcase(t, p) for p, t in zip(parts, target)):
            return profile
    return "default"


def find_persona(api, persona_id):
    rows = api.call("GET", "/personas")
    if not isinstance(rows, list) or not all(isinstance(x, dict) and isinstance(x.get("persona_id"), str) for x in rows):
        raise PackError("人格列表接口结构不兼容。")
    found = [p for p in rows if p["persona_id"] == persona_id]
    if len(found) > 1:
        raise PackError("存在重复的人格 ID。")
    return found[0] if found else None


def session_rule(api, origin):
    for page in range(1, 101):
        query = urllib.parse.urlencode({"search": origin, "page": page, "page_size": 100})
        data = api.call("GET", "/sessions/rules?" + query)
        if not isinstance(data, dict) or not isinstance(data.get("rules"), list) or type(data.get("total")) is not int:
            raise PackError("会话规则接口结构不兼容，无法确认最终人格；停止自动安装。")
        for row in data["rules"]:
            if not isinstance(row, dict) or not isinstance(row.get("rules"), dict):
                raise PackError("会话规则格式不兼容。")
            if row.get("umo") == origin:
                value = row["rules"].get(RULE_KEY)
                if value is not None and not isinstance(value, dict):
                    raise PackError("目标会话服务规则不是对象，停止安装。")
                return value
        if page * 100 >= data["total"]:
            return None
    raise PackError("会话规则分页过多，无法唯一确认目标。")


def profile_changes(config, manifest):
    if path_get(config, "agent_runner.runner_type") != "local":
        raise PackError("第一阶段仅适配 AstrBot 内置执行器 local。外部执行器请手动确认人格与分段是否生效。")
    changes = {"agent_runner.config.persona.persona_id": manifest["persona_id"],
               "provider_settings.streaming_response": False, "provider_tts_settings.enable": False, "t2i": False}
    changes.update({"platform_settings.segmented_reply." + k: v for k, v in manifest["rhythm"].items()})
    for path, value in changes.items():
        old = path_get(config, path)
        if isinstance(value, float):
            valid = type(old) in (int, float)
        else:
            valid = type(old) is type(value)
        if not valid:
            raise PackError(f"配置项类型不兼容：{path}。")
    return changes


def prepare(api, manifest, origin, source_profile=""):
    validate_origin(origin)
    mapping = routes(api)
    available = profiles(api)
    known = {r["id"] for r in available}
    source = source_profile or matching_profile(mapping, origin)
    if source not in known:
        # AstrBot falls back to default when a route points to a removed profile.
        if source_profile:
            raise PackError("指定的源配置文件 ID 不存在。")
        source = "default"
    config = read_profile(api, source)
    changes = profile_changes(config, manifest)
    original_rule = session_rule(api, origin)
    if any((original_rule or {}).get(k) is False for k in ("session_enabled", "llm_enabled")):
        raise PackError("目标会话或模型回复被停用。先恢复原有 QQ 正常对话，再安装鱼鱼。")
    prompt = canonical_prompt((ROOT / manifest["persona_file"]).read_text(encoding="utf-8-sig"))
    persona = find_persona(api, manifest["persona_id"])
    if persona is not None and canonical_prompt(persona.get("system_prompt")) != prompt:
        raise PackError("已有不同内容的同名鱼鱼人格，停止覆盖。请先保留并重命名旧人格。")
    after = copy.deepcopy(config)
    for path, value in changes.items():
        path_set(after, path, value)
    return {"origin": origin, "source_profile": source, "source_config": config, "config_after": after,
            "changes": changes, "routes_before": mapping, "rule_before": original_rule,
            "prompt": prompt, "persona_exists": persona is not None}


def public_plan(plan, manifest):
    return {"origin": plan["origin"], "source_profile": plan["source_profile"],
            "persona_id": manifest["persona_id"], "profile_strategy": "为这个会话复制专用配置，不改源配置",
            "changes": plan["changes"], "session_changes": {"persona_id": manifest["persona_id"], "tts_enabled": False},
            "typing": "每段发送前按字数等待，附加随机 0–0.5 秒；不显示 QQ 正在输入状态",
            "qq_acceptance": "pending"}


def put_rule_fields(api, origin, changes, expected):
    current = session_rule(api, origin)
    latest = copy.deepcopy(current or {})
    for key, old in expected.items():
        observed = {"exists": key in latest, "value": latest.get(key)}
        if observed != old:
            raise PackError(f"会话规则 {key} 已被改动，停止覆盖。")
    for key, value in changes.items():
        if value["exists"]:
            latest[key] = value["value"]
        else:
            latest.pop(key, None)
    if latest:
        api.call("POST", "/sessions/rules", {"umo": origin, "rule_key": RULE_KEY, "rule_value": latest})
    else:
        api.call("POST", "/sessions/rules/delete", {"umo": origin, "rule_key": RULE_KEY})
    actual = session_rule(api, origin) or {}
    for key, value in changes.items():
        if {"exists": key in actual, "value": actual.get(key)} != value:
            raise PackError("会话规则回读不一致。保留安装记录并恢复。")


def same_routes(first, second):
    return list(first.items()) == list(second.items())


def put_routes(api, updated, expected):
    if not same_routes(routes(api), expected):
        raise PackError("配置路由被其他操作修改，停止覆盖；请暂停后台编辑再重试。")
    api.call("PUT", "/config-routes", {"routing": updated})
    if not same_routes(routes(api), updated):
        raise PackError("配置路由回读不一致。")


def recover_created_profile(api, state):
    if state.get("profile_id"):
        return state["profile_id"]
    if state.get("profile_create_attempted"):
        found = [p["id"] for p in profiles(api) if p.get("name") == state["profile_name"]]
        if len(found) > 1:
            raise PackError("无法唯一识别中断前创建的专用配置，请在后台检查。")
        if found:
            state["profile_id"] = found[0]
            return found[0]
    return None


def install(api, manifest, origin, source_profile="", dry_run=False, confirm=lambda _: True):
    verify_files()
    intent = hashlib.sha256((json.dumps(manifest, sort_keys=True, ensure_ascii=False) + "\n" +
                            canonical_prompt((ROOT / manifest["persona_file"]).read_text(encoding="utf-8-sig"))).encode()).hexdigest()
    destination = state_path(api.base, origin)
    if destination.exists():
        previous = read_json(destination)
        validate_state(previous, api, origin)
        if previous["status"] == "complete":
            if previous["version"] != manifest["version"] or previous.get("intent") != intent:
                raise PackError("已有不同版本记录；本候选版不自动升级，请先恢复或使用版本迁移说明。")
            result = verify(api, previous)
            if not result["ok"]:
                raise PackError("已有安装发生变化：" + "；".join(result["problems"]))
            return {"status": "already_installed", **result}
        if previous["status"] != "restored":
            raise PackError("有未完成安装。先运行 restore；不要删除 .local。")
    plan = prepare(api, manifest, origin, source_profile)
    preview = public_plan(plan, manifest)
    if dry_run or not confirm(preview):
        return {"status": "planned" if dry_run else "cancelled", "plan": preview}
    # Re-read all mutable preconditions after the user has reviewed the preview.
    fresh = prepare(api, manifest, origin, source_profile)
    if (fresh["source_config"] != plan["source_config"] or fresh["rule_before"] != plan["rule_before"]
            or not same_routes(fresh["routes_before"], plan["routes_before"])):
        raise PackError("预览后后台配置发生变化，请重新预览。")
    if destination.exists():
        save_json(LOCAL / "history" / (destination.stem + "-" + str(time.time_ns()) + ".json"), read_json(destination))
    rule_before = plan["rule_before"] or {}
    changes = {"persona_id": manifest["persona_id"], "tts_enabled": False}
    state = {"schema": 2, "base": api.base, "origin": origin, "version": manifest["version"], "intent": intent, "status": "installing",
             "persona_id": manifest["persona_id"], "prompt": plan["prompt"], "changes": plan["changes"],
             "source_profile": plan["source_profile"], "profile_id": None,
             "profile_name": manifest["profile_name"] + "-" + uuid.uuid4().hex[:12],
             "route_before": {"exists": origin in plan["routes_before"], "value": plan["routes_before"].get(origin)},
             "route_order_before": list(plan["routes_before"]),
             "rule_before": {k: {"exists": k in rule_before, "value": rule_before.get(k)} for k in changes},
             "rule_after": {k: {"exists": True, "value": v} for k, v in changes.items()},
             "profile_create_attempted": False, "route_attempted": False, "rule_attempted": False}
    save_json(destination, state)
    if not fresh["persona_exists"]:
        api.call("POST", "/personas", {"persona_id": state["persona_id"], "system_prompt": state["prompt"], "begin_dialogs": [], "tools": None})
    persona = find_persona(api, state["persona_id"])
    if persona is None or canonical_prompt(persona.get("system_prompt")) != state["prompt"]:
        raise PackError("人格回读不一致，安装停止。")
    state["profile_create_attempted"] = True
    save_json(destination, state)
    out = api.call("POST", "/config-profiles", {"name": state["profile_name"], "config": plan["config_after"]})
    if not isinstance(out, dict) or not isinstance(out.get("conf_id"), str) or not out["conf_id"]:
        raise PackError("专用配置创建结果不明确。保留 .local 并恢复。")
    state["profile_id"] = out["conf_id"]
    save_json(destination, state)
    actual = read_profile(api, state["profile_id"])
    if any(path_get(actual, p) != v for p, v in state["changes"].items()):
        raise PackError("专用配置回读失败。")
    # Exact route must precede an existing wildcard route in AstrBot's first-match table.
    updated = {origin: state["profile_id"], **{k: v for k, v in plan["routes_before"].items() if k != origin}}
    state["route_attempted"] = True
    save_json(destination, state)
    put_routes(api, updated, plan["routes_before"])
    state["rule_attempted"] = True
    save_json(destination, state)
    put_rule_fields(api, origin, state["rule_after"], state["rule_before"])
    result = verify(api, state)
    if not result["ok"]:
        raise PackError("安装回读未通过：" + "；".join(result["problems"]))
    state["status"] = "complete"
    save_json(destination, state)
    return {"status": "configured", **result}


def validate_state(state, api, origin):
    if state.get("schema") != 2 or state.get("base") != api.base or state.get("origin") != origin:
        raise PackError("安装记录与当前版本、后台或会话不匹配。")


def verify(api, state):
    validate_state(state, api, state["origin"])
    issues = []
    persona = find_persona(api, state["persona_id"])
    if persona is None or canonical_prompt(persona.get("system_prompt")) != state["prompt"]:
        issues.append("人格被删除或修改")
    profile = state.get("profile_id")
    if not profile:
        issues.append("尚未创建专用配置")
    else:
        config = read_profile(api, profile)
        for path, value in state["changes"].items():
            if path_get(config, path) != value:
                issues.append("配置被修改：" + path)
        if matching_profile(routes(api), state["origin"]) != profile:
            issues.append("目标会话没有实际匹配到鱼鱼配置")
    rule = session_rule(api, state["origin"]) or {}
    for key, expected in state["rule_after"].items():
        if {"exists": key in rule, "value": rule.get(key)} != expected:
            issues.append("会话规则被修改：" + key)
    return {"ok": not issues, "problems": issues, "origin": state["origin"], "profile_id": profile,
            "persona_id": state["persona_id"], "qq_acceptance": "pending",
            "next": "在 QQ 验证人格、两段回复、打字停顿和恢复，按 docs/Windows验收.md 记录。"}


def restore(api, state):
    origin = state["origin"]
    validate_state(state, api, origin)
    destination = state_path(api.base, origin)
    if state["status"] == "restored":
        return {"status": "already_restored"}
    recover_created_profile(api, state)
    mapping = routes(api)
    changes, expected = {}, {}
    # Preflight every potentially modified item BEFORE restoring any item.
    if state["rule_attempted"]:
        rule = session_rule(api, origin) or {}
        for key, old in state["rule_before"].items():
            current = {"exists": key in rule, "value": rule.get(key)}
            if current == old:
                continue
            if current != state["rule_after"][key]:
                raise PackError(f"恢复冲突：会话规则 {key} 后来被手动修改，未覆盖。")
            changes[key], expected[key] = old, current
    updated = None
    if state["route_attempted"]:
        current = {"exists": origin in mapping, "value": mapping.get(origin)}
        if current != state["route_before"]:
            if mapping.get(origin) != state["profile_id"]:
                raise PackError("恢复冲突：目标会话的配置绑定后来被改动，未覆盖。")
            pairs = [(k, v) for k, v in mapping.items() if k != origin]
            if state["route_before"]["exists"]:
                order = state["route_order_before"]
                following = order[order.index(origin) + 1:]
                anchor = next((k for k in following if any(k == p[0] for p in pairs)), None)
                index = next((i for i, p in enumerate(pairs) if p[0] == anchor), len(pairs))
                pairs.insert(index, (origin, state["route_before"]["value"]))
            updated = dict(pairs)
    if changes:
        put_rule_fields(api, origin, changes, expected)
    if updated is not None:
        put_routes(api, updated, mapping)
    state["status"] = "restored"
    save_json(destination, state)
    return {"status": "restored", "retained_profile": state.get("profile_id"),
            "note": "原会话绑定和本轮改过的会话字段已恢复。人格与专用配置保留，确认无人使用后可在后台删除；聊天记录未清空。"}


def inspect(api, origin=""):
    out = {"version": api.call("GET", "/stats/version"), "profiles": profiles(api)}
    if origin:
        validate_origin(origin)
        rule = session_rule(api, origin) or {}
        out.update({"origin": origin, "effective_profile": matching_profile(routes(api), origin),
                    "session_persona": rule.get("persona_id"), "session_enabled": rule.get("session_enabled", True),
                    "llm_enabled": rule.get("llm_enabled", True)})
    # Only return the version string; backend version responses may contain extra metadata.
    version = out["version"]
    out["version"] = version.get("version", "unknown") if isinstance(version, dict) else "unknown"
    out["profiles"] = [{"id": p["id"], "name": p.get("name", "")} for p in out["profiles"]]
    return out


def read_options(args):
    options = {}
    folder = Path.cwd()
    allowed = {"base_url", "origin", "source_profile", "username", "password_file", "password_env", "token_file", "token_env"}
    if args.answers:
        location = Path(args.answers).resolve()
        folder = location.parent
        options = read_json(location)
        if not isinstance(options, dict) or set(options) - allowed:
            raise PackError("回答文件含未知字段。不要写 password/token 明文；用 password_file 或 token_file 指向本地文件。")
    for key in allowed:
        value = getattr(args, key, None)
        if value is not None:
            options[key] = value
    if not all(isinstance(v, str) for v in options.values()):
        raise PackError("回答文件各项应为字符串。")
    for key in ("password_file", "token_file"):
        if options.get(key):
            options[key] = str((folder / options[key]).resolve())
    return options


def secret(options, kind):
    file = options.get(kind + "_file")
    variable = options.get(kind + "_env")
    if file and variable:
        raise PackError(f"{kind}_file 与 {kind}_env 只选一种。")
    if file:
        value = Path(file).read_text(encoding="utf-8-sig").rstrip("\r\n")
    elif variable:
        value = os.environ.get(variable, "")
    else:
        return None
    if not value:
        raise PackError("指定的本地凭证为空或环境变量不存在。")
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description="鱼鱼第一阶段：检查、预览、安装、验证、恢复")
    parser.add_argument("action", choices=("check", "inspect", "plan", "install", "verify", "restore"))
    parser.add_argument("--answers", help="本地 JSON 回答文件，凭证使用文件路径")
    for name in ("base-url", "origin", "source-profile", "username", "password-file", "password-env", "token-file", "token-env"):
        parser.add_argument("--" + name)
    parser.add_argument("--yes", action="store_true", help="按已确认范围执行安装或恢复")
    parser.add_argument("--non-interactive", action="store_true", help="缺信息直接返回错误，不挂起等待")
    parser.add_argument("--json", action="store_true", help="输出结构化结果")
    args = parser.parse_args(argv)
    try:
        if args.action == "check":
            result = {"status": "files_ok", "checked_files": verify_files(), "qq_acceptance": "pending"}
        else:
            options = read_options(args)
            noninteractive = args.non_interactive or bool(args.answers) or not sys.stdin.isatty()
            def ask(key, prompt, default=""):
                if options.get(key):
                    return options[key]
                if noninteractive:
                    if default:
                        return default
                    raise PackError("缺少必填项：" + key)
                return input(prompt).strip() or default
            base = ask("base_url", "后台地址 [http://127.0.0.1:6185]：", "http://127.0.0.1:6185")
            token = secret(options, "token")
            api = Api(base, token)
            if not token:
                username = ask("username", "后台用户名 [astrbot]：", "astrbot")
                password = secret(options, "password")
                if password is None:
                    if noninteractive:
                        raise PackError("缺少本地凭证。使用 password_file/password_env，或交互运行以隐藏输入密码。")
                    password = getpass.getpass("后台密码（不回显）：")
                api.login(username, password)
                del password
            origin = options.get("origin", "") if args.action == "inspect" else validate_origin(ask("origin", "目标 QQ 会话 /sid 返回的完整 UMO："))
            manifest = read_json(ROOT / "settings/pack.json")
            if args.action == "inspect":
                result = inspect(api, origin)
            elif args.action in ("plan", "install"):
                if args.action == "install" and noninteractive and not args.yes:
                    raise PackError("自动安装需要 --yes 表示执行已确认的范围；先运行 plan 查看计划。")
                def confirm(preview):
                    if args.yes:
                        return True
                    print(json.dumps(preview, ensure_ascii=False, indent=2))
                    return input("确认范围，输入 导入：").strip() == "导入"
                with mutation_lock():
                    result = install(api, manifest, origin, options.get("source_profile", ""), args.action == "plan", confirm)
            else:
                path = state_path(api.base, origin)
                if not path.exists():
                    raise PackError("此后台和会话没有安装记录；请检查地址是否与导入时一致，或按手动说明操作。")
                state = read_json(path)
                validate_state(state, api, origin)
                if args.action == "verify":
                    if state["status"] == "restored":
                        result = {"ok": False, "status": "restored", "problems": ["已恢复，不再应用鱼鱼配置"]}
                    else:
                        result = verify(api, state)
                        if state["status"] != "complete":
                            result["ok"] = False
                            result["problems"].append("上轮安装记录未完成，请先恢复再安装。")
                else:
                    if not args.yes:
                        if noninteractive:
                            raise PackError("自动恢复需要 --yes。")
                        if input("恢复本轮会话设置？输入 恢复：").strip() != "恢复":
                            result = {"status": "cancelled"}
                            print(json.dumps(result, ensure_ascii=False))
                            return 0
                    with mutation_lock():
                        result = restore(api, state)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok", True) else 2
    except (PackError, ValueError, KeyError, OSError) as error:
        message = str(error) if isinstance(error, PackError) else "本地文件或配置格式异常。检查文件是否存在、JSON 是否正确。"
        print(json.dumps({"ok": False, "error": message, "hint": "写入中断时保留 .local，按 INSTALL.md 检查/恢复。"}, ensure_ascii=False, indent=2))
        return 1
    except KeyboardInterrupt:
        print("已中止；如已开始写入，请保留 .local 并执行 restore。")
        return 130


if __name__ == "__main__":
    sys.exit(main())
