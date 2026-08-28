import json
import os
import stat
import subprocess
from pathlib import Path
from typing import Dict, List

from har_reproducer.models import AgentType, DynamicToken, Extractor, StepRequest, TokenLocation
from har_reproducer.replay.curl_token_comment import CurlTokenComment
from har_reproducer.reproduction.cookie_jar_curl_override import CookieJarCurlOverride
from har_reproducer.reproduction.curl_generator import CurlGenerator
from har_reproducer.session import CookieJar, SessionStore
from har_reproducer.templates.extractor_template import ExtractorTemplate


def _override(cookie_jar: CookieJar) -> CookieJarCurlOverride:
    return CookieJarCurlOverride(cookie_jar)


def test_apply_returns_original_text_unchanged_when_jar_empty_for_scope() -> None:
    cookie_jar: CookieJar = CookieJar()
    override: CookieJarCurlOverride = _override(cookie_jar)
    curl_text: str = "curl -X GET 'https://exemplo.com/login'"

    result: str = override.apply(curl_text, "exemplo.com", 443, "/login")

    assert result == curl_text


def test_apply_inserts_cookie_flag_when_absent_and_jar_has_cookies() -> None:
    cookie_jar: CookieJar = CookieJar()
    cookie_jar.feed("exemplo.com", 443, {"sess": "x"}, {})
    override: CookieJarCurlOverride = _override(cookie_jar)
    curl_text: str = "curl -X GET 'https://exemplo.com/login'"

    result: str = override.apply(curl_text, "exemplo.com", 443, "/login")

    assert "--cookie" in result
    assert "sess=x" in result


def test_apply_merges_jar_over_existing_cookie_preserving_untouched_keys() -> None:
    cookie_jar: CookieJar = CookieJar()
    cookie_jar.feed("exemplo.com", 443, {"a": "9"}, {})
    override: CookieJarCurlOverride = _override(cookie_jar)
    curl_text: str = "curl -X GET 'https://exemplo.com/login' --cookie 'a=1; b=2'"

    result: str = override.apply(curl_text, "exemplo.com", 443, "/login")

    assert "a=9" in result
    assert "a=1" not in result
    assert "b=2" in result


def test_apply_does_not_confuse_cookie_substring_inside_data_binary_payload() -> None:
    cookie_jar: CookieJar = CookieJar()
    cookie_jar.feed("exemplo.com", 443, {"sess": "x"}, {})
    override: CookieJarCurlOverride = _override(cookie_jar)
    curl_text: str = (
        "curl -X POST 'https://exemplo.com/login' "
        "--data-binary '{\"cmd\": \"--cookie fake\"}'"
    )

    result: str = override.apply(curl_text, "exemplo.com", 443, "/login")

    assert '{"cmd": "--cookie fake"}' in result
    assert result.count("--cookie") == 2
    assert "sess=x" in result


def _fake_curl_script(tmp_path: Path, dump_file: Path) -> Path:
    script_path: Path = tmp_path / "curl"
    script_path.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        f"with open({str(dump_file)!r}, 'w') as f:\n"
        "    json.dump(sys.argv[1:], f)\n",
        encoding="utf-8",
    )
    script_path.chmod(script_path.stat().st_mode | stat.S_IEXEC)
    return script_path


def test_apply_reconstructs_real_curl_generator_output_runnable_via_real_bash(tmp_path: Path) -> None:
    session_store: SessionStore = SessionStore()
    generator: CurlGenerator = CurlGenerator(CurlTokenComment(step_index_width=4), session_store)
    request: StepRequest = StepRequest(
        url="https://exemplo.com/login",
        method="GET",
        headers={"Accept": "text/html"},
        cookies={"a": "1"},
    )
    curl_text: str = generator.generate(request, [])
    assert "\\\n" in curl_text

    cookie_jar: CookieJar = CookieJar()
    cookie_jar.feed("exemplo.com", 443, {"a": "9", "sess": "x"}, {})
    override: CookieJarCurlOverride = _override(cookie_jar)

    result: str = override.apply(curl_text, "exemplo.com", 443, "/login")

    assert "\n" not in result.replace("\\n", "")

    dump_file: Path = tmp_path / "argv.json"
    _fake_curl_script(tmp_path, dump_file)
    env: Dict[str, str] = dict(os.environ)
    env["PATH"] = f"{tmp_path}:{env.get('PATH', '')}"

    completed: subprocess.CompletedProcess = subprocess.run(
        ["bash", "-c", result], capture_output=True, env=env, timeout=10,
    )

    assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")
    received_argv: List[str] = json.loads(dump_file.read_text(encoding="utf-8"))

    assert "\n" not in received_argv
    assert "-X" in received_argv
    assert "GET" in received_argv
    assert "https://exemplo.com/login" in received_argv
    assert "--cookie" in received_argv
    cookie_index: int = received_argv.index("--cookie")
    cookie_value: str = received_argv[cookie_index + 1]
    cookie_pairs: Dict[str, str] = dict(
        pair.strip().split("=", 1) for pair in cookie_value.split(";")
    )
    assert cookie_pairs["a"] == "9"
    assert cookie_pairs["sess"] == "x"


def test_apply_does_not_turn_curl_sh_shebang_into_command_name(tmp_path: Path) -> None:
    session_store: SessionStore = SessionStore()
    generator: CurlGenerator = CurlGenerator(CurlTokenComment(step_index_width=4), session_store)
    request: StepRequest = StepRequest(
        url="https://exemplo.com/login",
        method="GET",
        headers={"Accept": "text/html"},
        cookies={"a": "1"},
    )
    curl_text: str = generator.generate(request, [])
    bash_script: str = ExtractorTemplate.render_bash_script(curl_text)
    assert bash_script.startswith("#!/bin/bash\n")

    cookie_jar: CookieJar = CookieJar()
    cookie_jar.feed("exemplo.com", 443, {"a": "9", "sess": "x"}, {})
    override: CookieJarCurlOverride = _override(cookie_jar)

    result: str = override.apply(bash_script, "exemplo.com", 443, "/login")

    assert not result.startswith("'#!/bin/bash'")

    dump_file: Path = tmp_path / "argv.json"
    _fake_curl_script(tmp_path, dump_file)
    env: Dict[str, str] = dict(os.environ)
    env["PATH"] = f"{tmp_path}:{env.get('PATH', '')}"

    completed: subprocess.CompletedProcess = subprocess.run(
        ["bash", "-c", result], capture_output=True, env=env, timeout=10,
    )

    assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")
    received_argv: List[str] = json.loads(dump_file.read_text(encoding="utf-8"))

    assert "#!/bin/bash" not in received_argv
    assert "-X" in received_argv
    assert "GET" in received_argv
    assert "https://exemplo.com/login" in received_argv
    assert "--cookie" in received_argv
    cookie_index: int = received_argv.index("--cookie")
    cookie_value: str = received_argv[cookie_index + 1]
    cookie_pairs: Dict[str, str] = dict(
        pair.strip().split("=", 1) for pair in cookie_value.split(";")
    )
    assert cookie_pairs["a"] == "9"
    assert cookie_pairs["sess"] == "x"
