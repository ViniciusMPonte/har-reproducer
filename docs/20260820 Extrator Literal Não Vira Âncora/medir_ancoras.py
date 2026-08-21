"""Mede quantas linhas de dependência de um workspace declaram literal congelado, e o efeito
no schedule do `replay --mode smart`.

Uso, da raiz do projeto:
    uv run python "docs/20260820 Extrator Literal Não Vira Âncora/medir_ancoras.py" <caminho_do_workspace>
"""
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from har_reproducer.replay.curl_token_comment import CurlTokenComment, OriginStatusPhrase

FROZEN_PHRASES: Set[str] = {phrase.value for phrase in OriginStatusPhrase}


def split_dependencies(curl_text: str) -> Tuple[Dict[str, int], Dict[str, int]]:
    """Devolve (todas as dependências, só as recalculáveis)."""
    todas: Dict[str, int] = {}
    recalculaveis: Dict[str, int] = {}
    for line in curl_text.splitlines():
        match = CurlTokenComment.DEPENDENCY_PATTERN.match(line)
        if match is None:
            continue
        token_id: str = match.group("token_id")
        origin_step: int = int(match.group("origin_step"))
        todas[token_id] = origin_step
        suffix: str = line[line.index(CurlTokenComment.CLAUSE_CLOSING_MARKER) + 1:].strip()
        phrases: List[str] = [part for part in suffix.split(CurlTokenComment.CATEGORY_SEPARATOR) if part]
        if not any(phrase in FROZEN_PHRASES for phrase in phrases):
            recalculaveis[token_id] = origin_step
    return todas, recalculaveis


def smart_schedule(per_step: Dict[int, Tuple[Dict[str, int], Dict[str, int]]], target: int, mode: int) -> List[int]:
    schedule: Set[int] = {target}
    pending: Set[int] = {target}
    while pending:
        current: int = pending.pop()
        for origin_step in per_step.get(current, ({}, {}))[mode].values():
            if origin_step not in schedule and origin_step in per_step:
                schedule.add(origin_step)
                pending.add(origin_step)
    return sorted(schedule)


def main(workspace: Path) -> None:
    curls: List[Path] = sorted((workspace / "curls").glob("req_*.curl.sh"))
    if not curls:
        raise SystemExit(f"nenhum curl em {workspace / 'curls'}")

    per_step: Dict[int, Tuple[Dict[str, int], Dict[str, int]]] = {}
    dep_hoje = dep_recalc = com_hoje = com_recalc = 0
    anc_hoje: Set[int] = set()
    anc_recalc: Set[int] = set()
    for curl in curls:
        todas, recalculaveis = split_dependencies(curl.read_text(encoding="utf-8"))
        index: int = int(curl.stem.split("_")[1].split(".")[0])
        per_step[index] = (todas, recalculaveis)
        dep_hoje += len(todas)
        dep_recalc += len(recalculaveis)
        anc_hoje |= set(todas.values())
        anc_recalc |= set(recalculaveis.values())
        com_hoje += bool(todas)
        com_recalc += bool(recalculaveis)

    alvos: List[int] = sorted(per_step)
    total_hoje: int = sum(len(smart_schedule(per_step, alvo, 0)) for alvo in alvos)
    total_recalc: int = sum(len(smart_schedule(per_step, alvo, 1)) for alvo in alvos)
    alterados: List[int] = [
        alvo for alvo in alvos if smart_schedule(per_step, alvo, 0) != smart_schedule(per_step, alvo, 1)
    ]

    print(f"workspace: {workspace}  ({len(curls)} curls)")
    print(f"  linhas de dependência ......... {dep_hoje} -> {dep_recalc} recalculáveis "
          f"({(1 - dep_recalc / dep_hoje) * 100:.0f}% declaram literal congelado)")
    print(f"  âncoras distintas ............. {len(anc_hoje)} -> {len(anc_recalc)}")
    print(f"  curls que arrastam âncora ..... {com_hoje}/{len(curls)} -> {com_recalc}/{len(curls)}")
    print(f"  requisições por replay smart .. {total_hoje / len(alvos):.2f} -> {total_recalc / len(alvos):.2f} "
          f"(média sobre os {len(alvos)} alvos)")
    print(f"  alvos com schedule alterado ... {len(alterados)}/{len(alvos)}")
    for alvo in alterados[:5]:
        print(f"      alvo {alvo}: {smart_schedule(per_step, alvo, 0)} -> {smart_schedule(per_step, alvo, 1)}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    main(Path(sys.argv[1]))
