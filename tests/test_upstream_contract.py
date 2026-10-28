"""Contract checks extracted from a pinned official checkout; no AstrBot runtime startup."""
import ast
import asyncio
import math
import logging
import os
from pathlib import Path
import random
from types import SimpleNamespace
import unittest

from test_manage import m, MANIFEST, FakeApi

SOURCE = Path(os.environ.get("ASTRBOT_SOURCE", ".upstream"))


@unittest.skipUnless((SOURCE / "astrbot/core/config/default.py").exists(), "ASTRBOT_SOURCE not provided")
class UpstreamContractTests(unittest.TestCase):
    def test_actual_persona_service_with_outer_whitespace(self):
        path = SOURCE / "astrbot/dashboard/services/persona_service.py"
        nodes = [ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)]
        nodes += [n for n in ast.parse(path.read_text(encoding="utf-8")).body if isinstance(n, ast.ClassDef)]
        namespace = {"NOT_GIVEN": object()}
        exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), str(path), "exec"), namespace)
        class Store:
            async def create_persona(self, **kwargs):
                return SimpleNamespace(created_at=None, updated_at=None, **kwargs)
        service = namespace["PersonaService"](SimpleNamespace(persona_mgr=Store()))
        raw = "\n鱼鱼\n第二行\n"
        output = asyncio.run(service.create_persona({"persona_id": "test", "system_prompt": raw}))
        self.assertEqual(output["persona"]["system_prompt"], m.canonical_prompt(raw))

    def test_actual_defaults_support_every_modified_field(self):
        tree = ast.parse((SOURCE / "astrbot/core/config/default.py").read_text(encoding="utf-8"))
        node = next(n.value for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "DEFAULT_CONFIG" for t in n.targets))
        values = dict(zip([ast.literal_eval(k) for k in node.keys], node.values))
        config = FakeApi().configs["default"]
        for key in ("platform_settings", "provider_tts_settings", "t2i"):
            config[key] = ast.literal_eval(values[key])
        provider = values["provider_settings"]
        streaming_node = next(v for k, v in zip(provider.keys, provider.values) if ast.literal_eval(k) == "streaming_response")
        config["provider_settings"]["streaming_response"] = ast.literal_eval(streaming_node)
        changes = m.profile_changes(config, MANIFEST)
        self.assertEqual(changes["platform_settings.segmented_reply.interval_method"], "log")

    def test_actual_sender_waits_before_every_segment(self):
        source = (SOURCE / "astrbot/core/pipeline/respond/stage.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "RespondStage")
        methods = [n for n in cls.body if isinstance(n, ast.AsyncFunctionDef) and n.name in ("_word_cnt", "_calc_comp_interval")]
        plain = type("Plain", (), {"__init__": lambda self, text: setattr(self, "text", text)})
        namespace = {"math": math, "random": random, "Comp": SimpleNamespace(Plain=plain)}
        nodes = [ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
                 ast.ClassDef(name="NativeTiming", bases=[], keywords=[], body=methods, decorator_list=[])]
        exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), "native_timing", "exec"), namespace)
        timing = namespace["NativeTiming"]()
        timing.interval_method = "log"
        timing.log_base = MANIFEST["rhythm"]["log_base"]
        for count in (5, 15, 30, 60):
            delay = asyncio.run(timing._calc_comp_interval(plain("字" * count)))
            lower = math.log(count + 1, 5)
            self.assertTrue(lower <= delay <= lower + 0.5)
        start = source.index("for comp in result.chain:", source.index("# Record 需要强制单独发送"))
        block = source[start:]
        self.assertLess(block.index("await asyncio.sleep(i)"), block.index("await event.send("))

    def test_official_persona_precedence_supports_session_override(self):
        tree = ast.parse((SOURCE / "astrbot/core/persona_mgr.py").read_text(encoding="utf-8"))
        method = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "resolve_selected_persona")
        class Preferences:
            async def get_async(self, **kwargs):
                return {"persona_id": MANIFEST["persona_id"]}
        namespace = {"sp": Preferences(), "SYSTEM_DEFAULT_PERSONA_ID": "default", "logger": logging.getLogger("contract")}
        nodes = [ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), method]
        exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), "persona_precedence", "exec"), namespace)
        manager = SimpleNamespace(personas_v3=[{"name": MANIFEST["persona_id"], "prompt": "test"}])
        result = asyncio.run(namespace["resolve_selected_persona"](manager, umo="test:FriendMessage:1", conversation_persona_id="OLD_ROLE", platform_name="aiocqhttp"))
        self.assertEqual(result[0], MANIFEST["persona_id"])
        self.assertEqual(result[2], MANIFEST["persona_id"])


if __name__ == "__main__":
    unittest.main()
