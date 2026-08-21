"""Maior substring comum entre um valor curto e o texto de uma resposta.

Duas implementações, porque a investigação mediu as duas e elas não têm o mesmo custo:

- `longest_common`: busca binária no tamanho, com poda opcional por cobertura mínima. É a
  que a spec descreve (uma busca por texto de resposta).
- `anchor_fragment`: âncora fixa `valor[16:32]` com expansão maximal e piso de 32. Mais
  rápida, mas o piso absoluto rejeita toda classe de token curto.
"""
from typing import List, Optional, Tuple

ANCHOR_LENGTH: int = 16


def longest_common(value: str, text: str, min_coverage: float = 0.0) -> Optional[Tuple[str, int]]:
    """Devolve (fragmento, deslocamento no valor) do maior pedaço contíguo comum, ou None.

    `min_coverage` poda a busca: só procura fragmentos que já satisfaçam a cobertura, o que
    descarta o caso comum antes de qualquer busca binária. Fragmento igual ao valor inteiro
    não é devolvido — esse caso é do passe de valor inteiro.
    """
    if not value or not text:
        return None

    k_max: int = len(value) - 1
    if k_max < 1:
        return None
    k_min: int = max(1, _ceil_int(min_coverage * len(value)))
    if k_min > k_max:
        return None
    if _probe(value, text, k_min) is None:
        return None

    best: Optional[Tuple[str, int]] = None
    low: int = k_min
    high: int = k_max
    while low <= high:
        middle: int = (low + high) // 2
        hit: Optional[Tuple[str, int]] = _probe(value, text, middle)
        if hit is not None:
            best = hit
            low = middle + 1
        else:
            high = middle - 1
    return best


def anchor_fragment(value: str, text: str) -> Optional[Tuple[str, int]]:
    """Algoritmo de âncora fixa: `valor[16:32]`, expansão maximal, piso `2 * ANCHOR_LENGTH`."""
    minimum: int = 2 * ANCHOR_LENGTH
    if len(value) < minimum:
        return None

    anchor: str = value[ANCHOR_LENGTH:2 * ANCHOR_LENGTH]
    best: Optional[Tuple[str, int]] = None
    position: int = text.find(anchor)
    while position >= 0:
        left_value, left_text = ANCHOR_LENGTH, position
        while left_value > 0 and left_text > 0 and value[left_value - 1] == text[left_text - 1]:
            left_value -= 1
            left_text -= 1
        right_value, right_text = 2 * ANCHOR_LENGTH, position + ANCHOR_LENGTH
        while right_value < len(value) and right_text < len(text) and value[right_value] == text[right_text]:
            right_value += 1
            right_text += 1

        fragment: str = value[left_value:right_value]
        if len(fragment) >= minimum and fragment != value:
            if best is None or len(fragment) > len(best[0]):
                best = (fragment, left_value)
        position = text.find(anchor, position + 1)
    return best


def _probe(value: str, text: str, size: int) -> Optional[Tuple[str, int]]:
    """Primeiro pedaço de `size` caracteres do valor que aparece no texto, com seu offset.

    Desempate por menor deslocamento dentro do valor — é a regra que produziu os números da
    investigação, e ela tem que ser explícita porque dois fragmentos de mesmo tamanho podem
    ter vereditos diferentes nos critérios de admissão.
    """
    for start in range(0, len(value) - size + 1):
        piece: str = value[start:start + size]
        if piece in text:
            return piece, start
    return None


def _ceil_int(number: float) -> int:
    truncated: int = int(number)
    return truncated if truncated == number else truncated + 1


def variants_of_lengths(fragments: List[str]) -> List[int]:
    """Utilitário de relatório: os comprimentos, para as tabelas de distribuição."""
    return sorted(len(fragment) for fragment in fragments)
