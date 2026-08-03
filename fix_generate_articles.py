# -*- coding: utf-8 -*-
from pathlib import Path
from datetime import datetime
import ast, base64, shutil
TARGET = Path("generate_articles.py")
RSS_CONFIG = base64.b64decode("Q05CQ19SU1NfVVJMUyA9IFsKICAgICJodHRwczovL3d3dy5jbmJjLmNvbS9pZC8xMDAwMDMxMTQvZGV2aWNlL3Jzcy9yc3MuaHRtbCIsCiAgICAiaHR0cHM6Ly93d3cuY25iYy5jb20vaWQvMTAwNzI3MzYyL2RldmljZS9yc3MvcnNzLmh0bWwiLAogICAgImh0dHBzOi8vd3d3LmNuYmMuY29tL2lkLzE1ODM3MzYyL2RldmljZS9yc3MvcnNzLmh0bWwiLAogICAgImh0dHBzOi8vd3d3LmNuYmMuY29tL2lkLzIwNDA5NjY2L2RldmljZS9yc3MvcnNzLmh0bWw/eD0xIiwKXQ==").decode()
FETCH_FUNC = base64.b64decode("ZGVmIGZldGNoX2NuYmNfcnNzX2VudHJpZXMoKToKICAgIGhlYWRlcnMgPSB7CiAgICAgICAgIlVzZXItQWdlbnQiOiAiTW96aWxsYS81LjAgKFdpbmRvd3MgTlQgMTAuMDsgV2luNjQ7IHg2NCkgQXBwbGVXZWJLaXQvNTM3LjM2IENocm9tZS8xMjYuMC4wLjAgU2FmYXJpLzUzNy4zNiIsCiAgICAgICAgIkFjY2VwdCI6ICJhcHBsaWNhdGlvbi9yc3MreG1sLGFwcGxpY2F0aW9uL3htbDtxPTAuOSx0ZXh0L3htbDtxPTAuOCwqLyo7cT0wLjciLAogICAgICAgICJBY2NlcHQtTGFuZ3VhZ2UiOiAiZW4tVVMsZW47cT0wLjkiLAogICAgICAgICJSZWZlcmVyIjogImh0dHBzOi8vd3d3LmNuYmMuY29tLyIsCiAgICB9CiAgICBlbnRyaWVzID0gW10KICAgIHNlZW5fbGlua3MgPSBzZXQoKQogICAgZm9yIHJzc191cmwgaW4gQ05CQ19SU1NfVVJMUzoKICAgICAgICBmb3IgYXR0ZW1wdCBpbiByYW5nZSgxLCA0KToKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgcHJpbnQoZiJDTkJDIFJTUyDsmpTssq06IHtyc3NfdXJsfSAo7Iuc64+EIHthdHRlbXB0fS8zKSIpCiAgICAgICAgICAgICAgICByZXNwb25zZSA9IHJlcXVlc3RzLmdldChyc3NfdXJsLCBoZWFkZXJzPWhlYWRlcnMsIHRpbWVvdXQ9MzAsIGFsbG93X3JlZGlyZWN0cz1UcnVlKQogICAgICAgICAgICAgICAgcHJpbnQoZiJDTkJDIFJTUyDsnZHri7U6IHN0YXR1cz17cmVzcG9uc2Uuc3RhdHVzX2NvZGV9LCBzaXplPXtsZW4ocmVzcG9uc2UuY29udGVudCl9IGJ5dGVzIikKICAgICAgICAgICAgICAgIHJlc3BvbnNlLnJhaXNlX2Zvcl9zdGF0dXMoKQogICAgICAgICAgICAgICAgcGFyc2VkID0gZmVlZHBhcnNlci5wYXJzZShyZXNwb25zZS5jb250ZW50KQogICAgICAgICAgICAgICAgaWYgbm90IHBhcnNlZC5lbnRyaWVzOgogICAgICAgICAgICAgICAgICAgIHByaW50KCJSU1Mg6riw7IKsIO2VreuqqeydtCDsl4bsirXri4jri6QuIikKICAgICAgICAgICAgICAgICAgICBicmVhawogICAgICAgICAgICAgICAgZm9yIGVudHJ5IGluIHBhcnNlZC5lbnRyaWVzOgogICAgICAgICAgICAgICAgICAgIHRpdGxlID0gc3RyKGVudHJ5LmdldCgidGl0bGUiLCAiIikpLnN0cmlwKCkKICAgICAgICAgICAgICAgICAgICBsaW5rID0gc3RyKGVudHJ5LmdldCgibGluayIsICIiKSkuc3RyaXAoKQogICAgICAgICAgICAgICAgICAgIGlmIHRpdGxlIGFuZCBsaW5rIGFuZCBsaW5rIG5vdCBpbiBzZWVuX2xpbmtzOgogICAgICAgICAgICAgICAgICAgICAgICBzZWVuX2xpbmtzLmFkZChsaW5rKQogICAgICAgICAgICAgICAgICAgICAgICBlbnRyaWVzLmFwcGVuZChlbnRyeSkKICAgICAgICAgICAgICAgIGJyZWFrCiAgICAgICAgICAgIGV4Y2VwdCByZXF1ZXN0cy5SZXF1ZXN0RXhjZXB0aW9uIGFzIGVycm9yOgogICAgICAgICAgICAgICAgcHJpbnQoZiJDTkJDIFJTUyDsmpTssq0g7Iuk7YyoOiB7ZXJyb3J9IikKICAgICAgICAgICAgICAgIGlmIGF0dGVtcHQgPCAzOgogICAgICAgICAgICAgICAgICAgIHRpbWUuc2xlZXAoYXR0ZW1wdCAqIDMpCiAgICAgICAgaWYgbGVuKGVudHJpZXMpID49IE1BWF9SU1NfRU5UUklFUzoKICAgICAgICAgICAgYnJlYWsKICAgIHByaW50KGYiQ05CQyBSU1Mg7LWc7KKFIOyImOynkSDquLDsgqw6IHtsZW4oZW50cmllcyl96rCcIikKICAgIHJldHVybiBlbnRyaWVzCgoK").decode()
PICK_FUNC = base64.b64decode("ZGVmIHBpY2tfYXJ0aWNsZSgpOgogICAgZW50cmllcyA9IGZldGNoX2NuYmNfcnNzX2VudHJpZXMoKQogICAgaWYgbm90IGVudHJpZXM6CiAgICAgICAgcmFpc2UgUnVudGltZUVycm9yKCLrqqjrk6AgQ05CQyBSU1Mg7KO87IaM7JeQ7IScIOq4sOyCrOulvCDrtojrn6zsmKTsp4Ag66q77ZaI7Iq164uI64ukLiIpCiAgICB0b3BpYyA9IGdldF90b2RheV90b3BpYygpCiAgICBjYW5kaWRhdGVzID0gZ2V0X3RvcGljX2NhbmRpZGF0ZXMoZW50cmllcywgdG9waWMpCiAgICBpZiBub3QgY2FuZGlkYXRlczoKICAgICAgICByYWlzZSBSdW50aW1lRXJyb3IoIuyEoO2DnSDqsIDriqXtlZwgQ05CQyDquLDsgqzqsIAg7JeG7Iq164uI64ukLiIpCiAgICBhcnRpY2xlID0gc2VsZWN0X3B1YmxpY19hcnRpY2xlKGNhbmRpZGF0ZXMpCiAgICB0aXRsZSA9IHN0cihhcnRpY2xlLmdldCgidGl0bGUiLCAiIikpLnN0cmlwKCkKICAgIGxpbmsgPSBzdHIoYXJ0aWNsZS5nZXQoImxpbmsiLCAiIikpLnN0cmlwKCkKICAgIHB1Ymxpc2hlZCA9IGFydGljbGUuZ2V0KCJwdWJsaXNoZWQiLCAiIikgb3IgYXJ0aWNsZS5nZXQoInVwZGF0ZWQiLCAiIikKICAgIHJzc19zdW1tYXJ5ID0gYXJ0aWNsZS5nZXQoInN1bW1hcnkiLCAiIikgb3IgYXJ0aWNsZS5nZXQoImRlc2NyaXB0aW9uIiwgIiIpCiAgICBkZXNjcmlwdGlvbiA9IGNsZWFuX2h0bWwocnNzX3N1bW1hcnkpIG9yIHRpdGxlCiAgICBpZiBub3QgdGl0bGUgb3Igbm90IGxpbms6CiAgICAgICAgcmFpc2UgUnVudGltZUVycm9yKCLshKDtg53rkJwg6riw7IKs7JeQIOygnOuqqSDrmJDripQg66eB7YGs6rCAIOyXhuyKteuLiOuLpC4iKQogICAgaWYgImNuYmMuY29tIiBub3QgaW4gbGluay5sb3dlcigpOgogICAgICAgIHJhaXNlIFJ1bnRpbWVFcnJvcigi7ISg7YOd65CcIOunge2BrOqwgCBDTkJDIOunge2BrOqwgCDslYTri5nri4jri6QuIikKICAgIHJldHVybiB7InRpdGxlIjogdGl0bGUsICJsaW5rIjogbGluaywgInB1Ymxpc2hlZCI6IHB1Ymxpc2hlZCwgImRlc2NyaXB0aW9uIjogZGVzY3JpcHRpb24sICJ0b3BpYyI6IHRvcGljfQoKCg==").decode()

def fn_range(source, name):
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return sum(map(len, lines[:node.lineno-1])), sum(map(len, lines[:node.end_lineno]))
    raise RuntimeError(f"함수를 찾지 못했습니다: {name}")

def main():
    if not TARGET.exists():
        raise FileNotFoundError("fix_generate_articles.py를 generate_articles.py와 같은 폴더에서 실행하세요.")
    source = TARGET.read_text(encoding="utf-8")
    if "import time" not in source:
        source = source.replace("import re\n", "import re\nimport time\n", 1)
    old = 'CNBC_RSS_URL = "여기에_기존_CNBC_RSS_URL"'
    if old in source:
        source = source.replace(old, RSS_CONFIG, 1)
    elif "CNBC_RSS_URLS = [" not in source:
        raise RuntimeError("CNBC RSS 설정 위치를 찾지 못했습니다.")
    if "def fetch_cnbc_rss_entries():" not in source:
        marker = "def get_topic_candidates(entries, topic):"
        pos = source.find(marker)
        if pos < 0:
            raise RuntimeError("get_topic_candidates 함수를 찾지 못했습니다.")
        source = source[:pos] + FETCH_FUNC + source[pos:]
    start, end = fn_range(source, "pick_article")
    source = source[:start] + PICK_FUNC + source[end:]
    ast.parse(source)
    backup = TARGET.with_name(f"generate_articles_backup_{datetime.now():%Y%m%d_%H%M%S}.py")
    shutil.copy2(TARGET, backup)
    TARGET.write_text(source, encoding="utf-8")
    print("[OK] 백업:", backup)
    print("[OK] 수정:", TARGET)
    print("[OK] 문법 검사 완료")

if __name__ == "__main__":
    main()
