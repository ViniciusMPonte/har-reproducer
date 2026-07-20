from typing import Any, List, Optional, Tuple

from bs4 import BeautifulSoup
from bs4.element import Tag

from .base import BaseAgent, Strategy

# A ranked candidate: (rank, css_selector, extraction_kind). ``extraction_kind`` is
# either "text" or the name of the attribute holding the value.
Candidate = Tuple[int, str, str]

# Attributes considered stable enough to build a selector from.
STABLE_ATTRS: Tuple[str, ...] = ("name", "for", "aria-label")

RANK_ID: int = 0
RANK_ATTR: int = 1
RANK_CLASS: int = 2


class CSSAgent(BaseAgent):
    """
    Agent specialized in extracting tokens from HTML bodies using CSS selectors.

    A naive class selector is fragile: the value may live in an attribute (not the
    text), may appear in several places, or the element may lack stable hooks. This
    agent parses the HTML, locates every element carrying the value (in text or in
    an attribute) and builds a ranked list of *unique* selectors:

      1. unique ``id``          (strongest)
      2. unique stable attribute (``name``, ``data-*``, ...)
      3. unique ``class``

    Purely positional selectors (``nth-of-type``) are intentionally **not**
    generated: rather than shipping something fragile, the agent lets the loop fall
    through to the LLM fallback (and ultimately reports failure if nothing works).
    """

    def deterministic_strategies(self) -> List[Strategy]:
        candidates: List[Candidate] = self._rank_candidates()
        return [self._make_strategy(sel, kind) for _, sel, kind in candidates]

    # ------------------------------------------------------------------ #
    # Structural search + ranking
    # ------------------------------------------------------------------ #
    def _rank_candidates(self) -> List[Candidate]:
        body: Any = self.response_sample.get("body", "")
        if not isinstance(body, str) or not body:
            return []
        soup: BeautifulSoup = BeautifulSoup(body, "html.parser")

        candidates: List[Candidate] = []
        for element in soup.find_all(True):
            if not isinstance(element, Tag):
                continue
            kind: Optional[str] = self._match_kind(element)
            if kind is None:
                continue
            candidates.extend(self._selectors_for(soup, element, kind))

        # Deduplicate keeping the strongest rank per (selector, kind).
        seen: dict[Tuple[str, str], int] = {}
        for rank, sel, kind in candidates:
            key = (sel, kind)
            if key not in seen or rank < seen[key]:
                seen[key] = rank
        unique: List[Candidate] = [(rank, sel, kind) for (sel, kind), rank in seen.items()]
        unique.sort(key=lambda c: c[0])
        return unique

    def _match_kind(self, element: Tag) -> Optional[str]:
        """Return "text", an attribute name, or None depending on where the value is."""
        for attr, val in element.attrs.items():
            values: List[str] = val if isinstance(val, list) else [val]
            if any(str(v) == self.expected_value for v in values):
                return attr
        # Only treat as a text match when this element is the innermost holder.
        if element.get_text(strip=True) == self.expected_value and not any(
            isinstance(child, Tag) and child.get_text(strip=True) == self.expected_value
            for child in element.find_all(True)
        ):
            return "text"
        return None

    def _selectors_for(
        self, soup: BeautifulSoup, element: Tag, kind: str
    ) -> List[Candidate]:
        found: List[Candidate] = []

        element_id: Optional[str] = element.get("id")
        if element_id and self._is_unique(soup, f"#{element_id}"):
            found.append((RANK_ID, f"#{element_id}", kind))

        for attr in (*STABLE_ATTRS, *[a for a in element.attrs if a.startswith("data-")]):
            val: Any = element.get(attr)
            if isinstance(val, str) and val:
                selector: str = f'{element.name}[{attr}="{val}"]'
                if self._is_unique(soup, selector):
                    found.append((RANK_ATTR, selector, kind))

        classes: Any = element.get("class") or []
        for cls in classes:
            if self._is_unique(soup, f".{cls}"):
                found.append((RANK_CLASS, f".{cls}", kind))

        return found

    @staticmethod
    def _is_unique(soup: BeautifulSoup, selector: str) -> bool:
        try:
            return len(soup.select(selector)) == 1
        except Exception:
            return False

    # ------------------------------------------------------------------ #
    # Code generation
    # ------------------------------------------------------------------ #
    def _make_strategy(self, selector: str, kind: str) -> Strategy:
        def strategy(last_error: Optional[str] = None) -> Optional[str]:
            return self._build_code(selector, kind)

        return strategy

    def _build_code(self, selector: str, kind: str) -> str:
        if kind == "text":
            extraction: str = "value = element.get_text(strip=True)"
        else:
            extraction = f"value = element.get({kind!r})"
        return f"""
from bs4 import BeautifulSoup

def extract_{self.safe_token_id}(response: dict) -> str:
    body = response.get('body', '')
    soup = BeautifulSoup(body, 'html.parser')
    element = soup.select_one({selector!r})
    if not element:
        raise Exception("Token element not found in HTML")
    {extraction}
    if not value:
        raise Exception("Token value not found in HTML element")
    return value
"""
