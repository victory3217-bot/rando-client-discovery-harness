# -*- coding: utf-8 -*-
"""Checking that an organization name is one the evidence actually contains.

This is the control the whole phase rests on. A language model asked for companies in a market
will produce companies in that market, drawing on everything it has ever read; the names will
be plausible, some will be real, and none of them will be evidence. So the pipeline does not
accept a name because a model returned it — it accepts a name because that name appears, as
text, in the passage the model cited.

**Matching is deliberately literal.** The name is Unicode-normalised, case-folded and
whitespace-collapsed, then compared **token by token**, with a short list of legal suffixes and
Korean particles tolerated at the edges. That is all. No alias resolution, no fuzzy matching, no
embedding similarity, no model-based entity resolution, no deciding that "ABC Holdings" and
"ABC Corporation" are the same firm — that is a judgement about the world which needs evidence
of its own. An alias counts only when a document states it or an operator supplies a mapping.

The rule the matcher enforces is that **the name must account for the whole name in the text**:

=============================== ======================= ======= ==============================
Evidence                        Model                   Verdict Why
=============================== ======================= ======= ==============================
Mekong Aqua Utilities           Mekong Aqua Utilities   accept  the same tokens
Mekong Aqua Utilities Co., Ltd. Mekong Aqua Utilities   accept  a tolerated legal form
Mekong Aqua Utilities가 …       Mekong Aqua Utilities   accept  a Korean particle, not a word
Mekong Aqua Utilities           Mekong Aqua             refuse  ``Utilities`` is part of a name
AlphaBeta Industrial            Alpha                   refuse  not even a whole token
=============================== ======================= ======= ==============================

The last two are the failures worth dwelling on, because a plain substring test accepts both and
reports the verification as having *passed*: the wrong organization then travels downstream with
provenance attached and nothing marking it as doubtful.

Telling "Utilities" (part of the name) from "announced" (the next word) needs no knowledge of
the world, only of orthography. A Latin script marks a continuing proper noun by capitalising
it, and Korean marks the end of one with a particle. Where a script offers neither mark the
matcher assumes the name continues, so it refuses instead of guessing — every judgement call
here resolves toward a missed organization rather than a wrong one.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Iterable, Optional, Sequence

from core.client.models import OrganizationMention, VerifiedOrganization

#: Tolerated when comparing a reported name with the text. Anything beyond this is guessing.
LEGAL_SUFFIXES: tuple[str, ...] = (
    "co ltd", "co., ltd", "coltd", "ltd", "limited", "llc", "inc", "incorporated",
    "corp", "corporation", "plc", "gmbh", "bv", "nv", "sa", "ag", "pte", "pty",
    "jsc", "psc", "group", "holdings", "co",
    "주식회사", "유한회사", "사", "그룹",
)

#: Every token the tolerated legal forms are built from, for testing one token at a time.
_SUFFIX_TOKENS: frozenset[str] = frozenset(
    token for suffix in LEGAL_SUFFIXES for token in suffix.replace(",", " ").split()
)

#: Shorter than this, a "name" is too generic for a match to mean anything.
MIN_NAME_CHARS = 3

#: Korean attaches grammatical particles straight onto a noun with no space, so the end of a
#: name in a Korean sentence carries no whitespace the way it does in English:
#: "Mekong Aqua Utilities가 발표했다" is one run of characters. This is the closed list tolerated
#: at a trailing boundary — the Korean equivalent of a word break, and nothing more. It resolves
#: no aliases and joins no names. A trailing run that is not in this list means no match, so
#: being wrong here costs a missed organization rather than a wrong one.
KOREAN_PARTICLES: frozenset[str] = frozenset(
    {
        # subject, topic, object, possessive
        "은", "는", "이", "가", "을", "를", "의",
        # location, direction, recipient
        "에", "에서", "에게", "한테", "께", "께서", "로", "으로",
        "에는", "에서는", "에도", "에서도", "로는", "으로는", "로도", "으로도",
        "에의", "에서의", "로의", "으로의",
        # conjunction and addition
        "와", "과", "랑", "이랑", "도", "와는", "과는", "와도", "과도", "와의", "과의",
        # scope and limit
        "만", "만은", "만도", "부터", "까지", "부터는", "까지는",
        "조차", "마저", "밖에", "뿐", "마다", "대로",
        # comparison and quotation
        "보다", "처럼", "같이", "라", "이라", "라는", "이라는", "라고", "이라고",
        # enumeration
        "등", "등의", "등은", "등이",
        # copula endings a sentence may close on
        "이다", "입니다", "이며", "이고", "인", "이란", "란", "였다", "이었다",
        # or / either
        "나", "이나", "든", "이든",
    }
)

_PUNCTUATION = re.compile(r"[.,;:()\[\]{}'\"`·・]")
_WHITESPACE = re.compile(r"\s+")

#: Scripts that mark no word break with whitespace and no proper noun with case, so a following
#: token has to be assumed part of the name unless a particle ended it.
_UNCASED_RANGES = (
    (0x1100, 0x11FF),  # Hangul Jamo
    (0x3040, 0x30FF),  # Hiragana, Katakana
    (0x3130, 0x318F),  # Hangul compatibility Jamo
    (0x4E00, 0x9FFF),  # CJK unified ideographs
    (0xAC00, 0xD7A3),  # Hangul syllables
)


def _spaced(text: str) -> str:
    """NFKC, punctuation turned into breaks, whitespace collapsed. Case preserved.

    Case survives here because :func:`_continues_a_name` needs it; comparison folds it away.
    """
    folded = unicodedata.normalize("NFKC", text)
    folded = _PUNCTUATION.sub(" ", folded)
    return _WHITESPACE.sub(" ", folded).strip()


def normalize(text: str) -> str:
    """Case-folded, punctuation-stripped, whitespace-collapsed form for comparison."""
    return _spaced(text).casefold()


def strip_legal_suffix(name: str) -> str:
    """Drop one trailing legal-form suffix, if present.

    One, not all: repeatedly stripping would reduce "Delta Group Holdings" to "Delta", which is
    a different organization.
    """
    normalized = normalize(name)
    for suffix in sorted(LEGAL_SUFFIXES, key=len, reverse=True):
        if normalized.endswith(" " + suffix):
            return normalized[: -(len(suffix) + 1)].strip()
    return normalized


def _is_uncased_script(text: str) -> bool:
    """Whether any character belongs to a script that marks neither case nor word breaks."""
    return any(
        any(low <= ord(char) <= high for low, high in _UNCASED_RANGES) for char in text
    )


def _continues_a_name(token: str) -> bool:
    """Whether a token following a match looks like more of the same organization's name.

    Capitalisation is the signal in a Latin script: "Mekong Aqua **Utilities**" continues the
    name, "Mekong Aqua Utilities **announced**" does not. Hangul and CJK carry no such mark, so
    anything that is not a particle is taken as continuing the name — which refuses the match
    rather than accepting a partial one.
    """
    if not token or token in KOREAN_PARTICLES:
        return False
    if _is_uncased_script(token):
        return True
    return token[:1].isupper()


def _is_name_plus_particle(token: str, tail: str) -> bool:
    """Whether ``token`` is the name's last token with one Korean particle glued on."""
    if not token.startswith(tail) or token == tail:
        return False
    return token[len(tail) :] in KOREAN_PARTICLES


def _match_ends_the_name(following: Sequence[str], *, model_supplied_suffix: bool) -> bool:
    """Whether the match stopped where the organization's name stops.

    ``model_supplied_suffix`` says the model's name carried a legal form that was stripped
    before matching, and it flips how a legal form in the *text* reads. With no suffix from the
    model, "Mekong Aqua Utilities" against "Mekong Aqua Utilities Co., Ltd." is one firm written
    more fully. With one, "Delta Water Ltd" against "Delta Water Holdings" is two firms sharing
    a word.
    """
    if not following:
        return True
    head = following[0]
    if head in KOREAN_PARTICLES:
        return True
    if head.casefold() in _SUFFIX_TOKENS:
        return not model_supplied_suffix
    return not _continues_a_name(head)


def _match_index(
    name_tokens: Sequence[str],
    text_tokens: Sequence[str],
    *,
    model_supplied_suffix: bool,
) -> int:
    """Which token the name starts at, or ``-1``.

    Token by token rather than by substring, so a match can never begin or end inside a word.
    """
    if not name_tokens:
        return -1

    folded = [token.casefold() for token in text_tokens]
    head, tail = list(name_tokens[:-1]), name_tokens[-1]

    for index in range(len(text_tokens) - len(name_tokens) + 1):
        if folded[index : index + len(head)] != head:
            continue
        last = folded[index + len(head)]
        if last != tail:
            # A particle glued to the final token ends the name there, so nothing follows it.
            if _is_name_plus_particle(last, tail):
                return index
            continue
        following = text_tokens[index + len(name_tokens) :]
        if _match_ends_the_name(following, model_supplied_suffix=model_supplied_suffix):
            return index
    return -1


def name_appears_in(name: str, text: str) -> bool:
    """Whether ``text`` names this organization, allowing only the tolerated differences.

    Suffix tolerance is narrower than it first looks, because a loose version of it quietly
    becomes alias resolution. ``ABC Corporation`` and ``ABC Holdings`` both reduce to ``ABC``,
    and treating that as a match would mean the harness deciding two firms are the same company
    on the strength of a shared first word. Four guards prevent it:

    * tokens are compared whole, so ``Alpha`` is not found in ``AlphaBeta``;
    * a match must account for the whole name in the text, so ``Mekong Aqua`` is not found in
      ``Mekong Aqua Utilities``;
    * a stripped name must still be more than one token, so ``ABC Corporation`` is only ever
      matched in full;
    * a stripped name followed by a *different* legal form is refused, so ``Delta Water Ltd``
      matches "Delta Water announced" but not "Delta Water Holdings announced".
    """
    if len(name.strip()) < MIN_NAME_CHARS:
        return False

    text_tokens = _spaced(text).split()
    if _match_index(normalize(name).split(), text_tokens, model_supplied_suffix=False) >= 0:
        return True

    # The document may write the name without the legal form the model supplied.
    bare = strip_legal_suffix(name)
    if not bare or bare == normalize(name) or len(bare) < MIN_NAME_CHARS:
        return False
    if len(bare.split()) < 2:
        # A single token is too generic to match on once its suffix is gone.
        return False

    return _match_index(bare.split(), text_tokens, model_supplied_suffix=True) >= 0


def verify_mentions(
    mentions: Iterable[OrganizationMention],
    *,
    snippet_locator: str = "snippet",
) -> list[VerifiedOrganization]:
    """Collapse verified mentions into one organization per name.

    A mention that reached here has already been checked against its passage; this groups the
    survivors, gathers their sources, and records whether every one of them is a search snippet.
    That last flag is what stops a candidate known only from search summaries being placed
    first — see ``core/client/priority.py``.
    """
    by_key: dict[str, VerifiedOrganization] = {}

    for mention in mentions:
        key = strip_legal_suffix(mention.name) or normalize(mention.name)
        organization = by_key.get(key)
        if organization is None:
            organization = VerifiedOrganization(name=mention.name.strip(), snippet_only=True)
            by_key[key] = organization

        if mention.source_id and mention.source_id not in organization.source_ids:
            organization.source_ids.append(mention.source_id)
        if mention.locator and mention.locator not in organization.locators:
            organization.locators.append(mention.locator)
        if mention.locator != snippet_locator:
            organization.snippet_only = False

    return list(by_key.values())


def direct_locators(locators: Iterable[str], *, snippet_locator: str = "snippet") -> list[str]:
    """Locators that point into a document rather than at a search summary."""
    return [locator for locator in locators if locator != snippet_locator]


def find_span(name: str, text: str, *, window: int = 12) -> Optional[str]:
    """A few tokens around the match, for the transient mention only.

    Kept out of everything persisted and out of every log line; it exists so a developer
    debugging a verification failure can see what was compared.
    """
    text_tokens = _spaced(text).split()
    needle = normalize(name).split()
    index = _match_index(needle, text_tokens, model_supplied_suffix=False)
    if index < 0:
        bare = strip_legal_suffix(name)
        if not bare:
            return None
        needle = bare.split()
        index = _match_index(needle, text_tokens, model_supplied_suffix=True)
    if index < 0:
        return None
    start = max(0, index - window // 2)
    return " ".join(text_tokens[start : index + len(needle) + window // 2])
