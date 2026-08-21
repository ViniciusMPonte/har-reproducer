"""Verificações sobre as duas épocas de um workspace: legibilidade dos corpos, estabilidade
de headers entre as épocas, e a classe de requisição condicional.

É o script que sustenta M12 (corpo comprimido persistido como mojibake), M14 (requisição
condicional) e M16 (estabilidade de ETag/Last-Modified).

Uso, da raiz do projeto:

    D='docs/20260820 Investigação da Porta de Admissão/medições'
    uv run python "$D/epocas.py" --workspace ../arquivos-har/ws_20260817_main \
        --har ../arquivos-har/progressofit.har
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from har_reproducer.fs_io import HARParser

REPLACEMENT: str = "�"
UNREADABLE_RATIO: float = 0.05
CONDITIONAL_HEADERS: Tuple[str, ...] = ("if-none-match", "if-modified-since")
EPOCH_STABLE_HEADERS: Tuple[str, ...] = ("etag", "last-modified")


def _load(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _unreadable_ratio(body: Optional[str]) -> float:
    if not body:
        return 0.0
    return body.count(REPLACEMENT) / len(body)


def _lower_headers(response: Optional[Dict[str, Any]]) -> Dict[str, str]:
    if not response:
        return {}
    return {name.lower(): value for name, value in (response.get("headers") or {}).items()}


def report_body_legibility(workspace: Path) -> None:
    """M12 — respostas legíveis numa época e ilegíveis na outra."""
    har_bad = exec_bad = har_total = exec_total = 0
    flips: List[Tuple[int, str, int, int, int, int]] = []

    for har_file in sorted((workspace / "original_responses").glob("res_*.json")):
        step_index: int = int(har_file.stem.split("_")[1])
        har_response = _load(har_file)
        exec_response = _load(workspace / "real_responses" / har_file.name)
        har_body: str = (har_response or {}).get("body") or ""
        exec_body: str = (exec_response or {}).get("body") or ""
        encoding: str = _lower_headers(har_response).get("content-encoding", "")

        har_ratio: float = _unreadable_ratio(har_body)
        exec_ratio: float = _unreadable_ratio(exec_body)
        if har_body:
            har_total += 1
            har_bad += har_ratio > UNREADABLE_RATIO
        if exec_body:
            exec_total += 1
            exec_bad += exec_ratio > UNREADABLE_RATIO
        if har_body and exec_body and (har_ratio > UNREADABLE_RATIO) != (exec_ratio > UNREADABLE_RATIO):
            flips.append((step_index, encoding, len(har_body), round(har_ratio * 100),
                          len(exec_body), round(exec_ratio * 100)))

    print("== M12 — legibilidade dos corpos ==")
    print(f"  ilegíveis (>{UNREADABLE_RATIO:.0%} U+FFFD): época do HAR {har_bad}/{har_total} | "
          f"época da execução {exec_bad}/{exec_total}")
    print(f"  legíveis numa época e ILEGÍVEIS na outra: {len(flips)}")
    for step_index, encoding, har_len, har_pct, exec_len, exec_pct in flips:
        print(f"    step {step_index:4d} enc={encoding or '-':5s} "
              f"HAR {har_len:7d} ch ({har_pct:2d}% FFFD) | EXEC {exec_len:7d} ch ({exec_pct:2d}% FFFD)")
    if flips:
        print("  ⚠️ cada uma destas é um gerador de dinamismo fantasma para qualquer comparação "
              "entre as épocas")


def report_stable_headers(workspace: Path) -> None:
    """M16 — headers que mudam no deploy, não entre duas execuções."""
    print("\n== M16 — estabilidade de headers entre as épocas ==")
    for header in EPOCH_STABLE_HEADERS:
        identical = total = 0
        for har_file in sorted((workspace / "original_responses").glob("res_*.json")):
            har_headers = _lower_headers(_load(har_file))
            if header not in har_headers:
                continue
            exec_headers = _lower_headers(_load(workspace / "real_responses" / har_file.name))
            total += 1
            identical += har_headers[header] == exec_headers.get(header)
        if total:
            print(f"  {header:15s} idêntico entre as épocas em {identical}/{total}")
        else:
            print(f"  {header:15s} ausente neste workspace")


def report_conditional(har_path: Path) -> None:
    """M14 — a classe de requisição condicional."""
    entries: List[Dict[str, Any]] = HARParser.get_entries(har_path)
    counts: Counter = Counter()
    for entry in entries:
        names = {header["name"].lower() for header in entry["request"].get("headers", [])}
        for header in CONDITIONAL_HEADERS:
            if header in names:
                counts[header] += 1
        if entry["response"]["status"] == 304:
            counts["respostas 304"] += 1

    print("\n== M14 — requisição condicional ==")
    print(f"  entries: {len(entries)}")
    for header in CONDITIONAL_HEADERS:
        print(f"  {header:20s} {counts[header]}")
    print(f"  {'respostas 304':20s} {counts['respostas 304']}")
    missing_raw = sum(1 for e in entries if not (e["response"].get("content", {}).get("text") or ""))
    missing_rule = HARParser.entries_missing_response_body(entries)
    print(f"\n== corpo de resposta ausente ==")
    print(f"  sem content.text (bruto) ........................ {missing_raw}/{len(entries)}")
    print(f"  pela régua do projeto (exclui 101/204/304) ...... {missing_rule}")
    print("  ⚠️ a descoberta na época do HAR depende de o step de origem ter corpo gravado")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--har", required=False)
    return parser.parse_args()


if __name__ == "__main__":
    options = parse_args()
    workspace_path = Path(options.workspace)
    report_body_legibility(workspace_path)
    report_stable_headers(workspace_path)
    if options.har:
        report_conditional(Path(options.har))
