"""Explicit release allowlist; excludes local credentials, state, audits and image assets."""
import ast
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FILES = [
    "README.md", "AGENTS.md", "INSTALL.md", "LICENSE", "CHANGELOG.md", ".gitignore", ".gitattributes",
    "persona/鱼鱼.md", "settings/pack.json", "examples/answers.example.json",
    "tools/manage.py", "tools/build_pack.py", "tools/run.ps1",
    "导入鱼鱼.bat", "检查鱼鱼.bat", "恢复鱼鱼设置.bat",
    "docs/Windows验收.md", "docs/验收记录模板.md", "docs/兼容与来源.md", "docs/GitHub发布.md",
    "tests/test_manage.py", "tests/test_upstream_contract.py", ".github/workflows/check.yml",
]


def build():
    for rel in FILES:
        path = ROOT / rel
        if not path.is_file():
            raise FileNotFoundError(rel)
        if path.suffix == ".py":
            ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        elif path.suffix == ".json":
            json.loads(path.read_text(encoding="utf-8"))
    hashes = {rel: hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() for rel in sorted(FILES)}
    (ROOT / "SHA256SUMS.json").write_text(json.dumps(hashes, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    version = json.loads((ROOT / "settings/pack.json").read_text(encoding="utf-8"))["version"]
    target = ROOT.parent / f"鱼鱼人格配置包-v{version}.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for rel in sorted(FILES + ["SHA256SUMS.json"]):
            info = zipfile.ZipInfo("yuyu-persona-pack/" + rel, date_time=(2026, 10, 28, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, (ROOT / rel).read_bytes())
    with zipfile.ZipFile(target) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("ZIP integrity failed")
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    target.with_suffix(".zip.sha256").write_text(f"{digest}  {target.name}\n", encoding="utf-8")
    print(f"Built {target.name}; {len(hashes)} verified files; SHA256 {digest}")


if __name__ == "__main__":
    build()
