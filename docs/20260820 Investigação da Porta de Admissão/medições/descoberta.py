"""Arnês parametrizável da descoberta de origem, para reproduzir as medições da investigação.

Usa as classes reais do projeto (`HARParser`, `BaselineDiff`, `ResponseCorpus`,
`OriginFinder`) e reimplementa apenas o laço do `CandidateResolver`, porque é ele que a
investigação variou.

Exemplos, da raiz do projeto:

    D='docs/20260820 Investigação da Porta de Admissão/medições'

    # M1 — linha de base: só casamento de valor inteiro
    uv run python "$D/descoberta.py" --har ../arquivos-har/progressofit.har \
        --workspace ../arquivos-har/ws_20260817_main --estrategia inteiro

    # M6 — as três políticas de cache, contando ocorrências
    for c in definitivo misses provisorio; do
      uv run python "$D/descoberta.py" --har ../arquivos-har/progressofit.har \
          --workspace ../arquivos-har/ws_20260817_main --cache $c --porta
    done

    # M9 — ablação de critérios
    uv run python "$D/descoberta.py" --har ... --workspace ... --piso 0 --ubiquidade 1.0 --sem-vocabulario --porta
"""
import argparse
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from har_reproducer.fs_io import HARParser
from har_reproducer.models import SkipRulesConfig, Step
from har_reproducer.reproduction import StepSkipEvaluator
from har_reproducer.tracking.baseline_diff import BaselineDiff
from har_reproducer.tracking.origin_finder import OriginFinder
from har_reproducer.tracking.response_corpus import ResponseCorpus

from lcs import anchor_fragment, longest_common

STEP_INDEX_WIDTH: int = 4


class Match:
    """Um casamento: o texto que a resposta contém e de qual step ele veio."""

    def __init__(self, kind: str, matched: str, origin_step: int) -> None:
        self.kind: str = kind
        self.matched: str = matched
        self.origin_step: int = origin_step


class Harness:

    def __init__(self, options: argparse.Namespace) -> None:
        self.options: argparse.Namespace = options
        self.discovery: ResponseCorpus = ResponseCorpus(
            Path(options.workspace) / "original_responses", STEP_INDEX_WIDTH
        )
        self.execution: ResponseCorpus = ResponseCorpus(
            Path(options.workspace) / "real_responses", STEP_INDEX_WIDTH
        )
        self.finder: OriginFinder = OriginFinder(self.discovery)
        self.texts: Dict[int, str] = self._load_texts()
        self.steps: List[int] = sorted(self.texts)
        self.addresses: Set[str] = set()
        self.counters: Counter = Counter()
        self.rows: List[Tuple[int, str, str, Match]] = []
        self._ubiquity: Dict[Tuple[str, int], float] = {}

    def _load_texts(self) -> Dict[int, str]:
        texts: Dict[int, str] = {}
        for step_index in sorted(self.discovery.eligible_indexes(10 ** 9)):
            text: Optional[str] = self.discovery.searchable_text(step_index)
            if text:
                texts[step_index] = text
        return texts

    # ---- critérios de admissão do fragmento

    def _ubiquity_of(self, fragment: str, before_step: int) -> float:
        key: Tuple[str, int] = (fragment, before_step)
        if key in self._ubiquity:
            return self._ubiquity[key]
        eligible: List[int] = [step for step in self.steps if step < before_step]
        if not eligible:
            self._ubiquity[key] = 0.0
            return 0.0
        hits: int = sum(1 for step in eligible if fragment in self.texts[step])
        self._ubiquity[key] = hits / len(eligible)
        return self._ubiquity[key]

    def _rejection_reason(self, fragment: str, value: str, before_step: int) -> Optional[str]:
        if len(fragment) / len(value) < self.options.cobertura:
            return "cobertura"
        if len(fragment) < self.options.piso:
            return "piso"
        if self._ubiquity_of(fragment, before_step) >= self.options.ubiquidade:
            return "ubiquidade"
        if not self.options.sem_vocabulario and any(fragment in address for address in self.addresses):
            return "vocabulário do fluxo"
        return None

    # ---- passes

    def _whole_match(self, value: str, from_step: int, before_step: int) -> Optional[Match]:
        found = self.finder.find(value, from_step, before_step)
        if found is None:
            return None
        return Match("inteiro", value, found.step_index)

    def _fragment_match(self, value: str, from_step: int, before_step: int) -> Optional[Match]:
        if self.options.estrategia == "inteiro":
            return None

        best: Optional[Tuple[str, int, int]] = None
        for step_index in self.steps:
            if not (from_step <= step_index < before_step):
                continue
            if self.options.estrategia == "ancora":
                hit = anchor_fragment(value, self.texts[step_index])
            else:
                hit = longest_common(value, self.texts[step_index], self.options.cobertura)
            if hit is None:
                continue
            fragment, offset = hit
            if best is None or len(fragment) > len(best[0]):
                best = (fragment, offset, step_index)
        if best is None:
            self.counters["sem fragmento"] += 1
            return None

        reason: Optional[str] = self._rejection_reason(best[0], value, before_step)
        if reason is not None:
            self.counters[f"rejeitado: {reason}"] += 1
            return None
        self.counters["fragmento admitido"] += 1
        return Match("fragmento", best[0], best[2])

    # ---- porta de admissão

    def _gate(self, match: Match) -> str:
        if not self.options.porta:
            return "mudou"
        text: Optional[str] = self.execution.searchable_text(match.origin_step)
        if not text:
            return "indeterminado"
        return "estatico" if match.matched in text else "mudou"

    # ---- laço principal

    def run(self) -> None:
        entries: List[dict] = HARParser.get_entries(Path(self.options.har))
        baseline: Step = HARParser.parse_entry(entries[0], 0)
        skip_evaluator: StepSkipEvaluator = StepSkipEvaluator(SkipRulesConfig())
        diff: BaselineDiff = BaselineDiff()

        definitive: Dict[str, Match] = {}
        provisional: Dict[str, Match] = {}
        misses: Dict[str, int] = {}
        skipped: List[int] = []
        started: float = time.time()

        for index, entry in enumerate(entries):
            step: Step = HARParser.parse_entry(entry, index)
            parsed = urlparse(step.request.url)
            if parsed.hostname:
                self.addresses |= {parsed.hostname, parsed.netloc, f"{parsed.scheme}://{parsed.netloc}"}
            if skip_evaluator.skip_reason(step.request) is not None:
                skipped.append(index)
                continue

            for path, value in diff.compare(step, baseline).items():
                self.counters["ocorrências de candidato"] += 1
                self._process(index, path, value, definitive, provisional, misses)

        self.elapsed: float = time.time() - started
        self.entries: int = len(entries)
        self.skipped: List[int] = skipped

    def _process(
            self,
            index: int,
            path: str,
            value: str,
            definitive: Dict[str, Match],
            provisional: Dict[str, Match],
            misses: Dict[str, int],
    ) -> None:
        cached: Optional[Match] = definitive.get(value)
        if cached is not None:
            self.rows.append((index, path, value, cached))
            return

        held: Optional[Match] = provisional.get(value)
        if held is not None and self.options.cache == "provisorio":
            promoted: Optional[Match] = self._whole_match(value, 0, index)
            if promoted is not None:
                definitive[value] = promoted
                provisional.pop(value)
                self.counters["promoções de fragmento para inteiro"] += 1
                self.rows.append((index, path, value, promoted))
                return
            self.rows.append((index, path, value, held))
            return
        if held is not None:
            self.rows.append((index, path, value, held))
            return

        from_step: int = misses.get(value, 0)
        whole: Optional[Match] = self._whole_match(value, from_step, index)
        if whole is not None:
            definitive[value] = whole
            self.counters["casou inteiro"] += 1
            self.rows.append((index, path, value, whole))
            return

        fragment: Optional[Match] = self._fragment_match(value, from_step, index)
        if fragment is None:
            misses[value] = index
            return

        self.rows.append((index, path, value, fragment))
        if self.options.cache == "definitivo":
            definitive[value] = fragment
        elif self.options.cache == "provisorio":
            provisional[value] = fragment
        else:
            misses[value] = index

    # ---- relatório

    def report(self) -> None:
        print(f"har={self.options.har}")
        print(f"workspace={self.options.workspace}")
        print(f"estratégia={self.options.estrategia} cache={self.options.cache} porta={self.options.porta} "
              f"cobertura={self.options.cobertura} piso={self.options.piso} "
              f"ubiquidade<{self.options.ubiquidade} vocabulário={not self.options.sem_vocabulario}")
        print(f"entries={self.entries} steps pulados={self.skipped} tempo={self.elapsed:.1f}s\n")

        for name, count in self.counters.most_common():
            print(f"  {count:5d}  {name}")

        whole_origins = {(row[3].matched, row[3].origin_step) for row in self.rows if row[3].kind == "inteiro"}
        frag_origins = {(row[3].matched, row[3].origin_step) for row in self.rows if row[3].kind == "fragmento"}
        print(f"\n  origens distintas: {len(whole_origins)} inteiras + {len(frag_origins)} fragmentos")

        verdicts: Counter = Counter()
        admitted: Dict[Tuple[str, int], int] = {}
        for index, path, value, match in self.rows:
            verdict: str = self._gate(match)
            verdicts[f"{match.kind}/{verdict}"] += 1
            if verdict == "mudou":
                admitted[(path, match.origin_step)] = admitted.get((path, match.origin_step), 0) + 1
        print(f"  veredito da porta: {dict(verdicts)}")
        print(f"  EXTRATORES (slots distintos que sobrevivem): {len(admitted)}")
        print(f"  ocorrências que receberam extrator: {sum(admitted.values())}")
        for (path, origin_step), occurrences in sorted(admitted.items(), key=lambda item: -item[1]):
            print(f"      {occurrences:4d}x  {path} <- step {origin_step}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--har", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--estrategia", choices=("inteiro", "lcs", "ancora"), default="lcs")
    parser.add_argument("--cache", choices=("definitivo", "misses", "provisorio"), default="definitivo")
    parser.add_argument("--cobertura", type=float, default=0.5)
    parser.add_argument("--piso", type=int, default=4)
    parser.add_argument("--ubiquidade", type=float, default=0.2)
    parser.add_argument("--sem-vocabulario", action="store_true")
    parser.add_argument("--porta", action="store_true", help="aplica a porta de admissão entre as épocas")
    return parser.parse_args()


if __name__ == "__main__":
    harness = Harness(parse_args())
    harness.run()
    harness.report()
