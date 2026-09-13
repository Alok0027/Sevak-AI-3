"""Retrieval over the NHM protocol corpus (SRS section 10, Week 2).

This is the RAG half of FR-03. `nhm_protocol_rag.py` next door holds the
deterministic thresholds; this module finds the published guidance that
those thresholds came from, so a risk flag can say *which* NHM document
says a reading is dangerous instead of asserting it.

Two backends, chosen by RETRIEVAL_PROVIDER, following the same pattern as
STT_PROVIDER and LLM_PROVIDER elsewhere in the project:

    lexical  (default) -- BM25 over the corpus. Pure Python, no model, no
                          index files, ~200 lines. Starts in milliseconds
                          and runs in a few MB.
    chroma             -- ChromaDB with sentence-embedding search, the
                          store the SRS names. Pulls onnxruntime and an
                          ~80MB model, so it is opt-in rather than default.
    none               -- retrieval off; Agent 2 falls back to thresholds
                          alone, which is the behaviour before this module
                          existed.

Why lexical is the default, given the SRS says ChromaDB
-------------------------------------------------------
Two reasons, one practical and one about this corpus in particular.

The practical one: the deployment target is a 512MB free-tier container.
An embedding model plus its runtime is most of that budget, and an API that
is OOM-killed mid-demo retrieves nothing at all.

The one that matters more: this corpus is small (a handful of documents,
tens of chunks) and the queries are dense with the exact terms the
documents use -- "blood pressure 150/100", "haemoglobin 6.4", "convulsions".
Lexical matching is strong exactly there. Embeddings earn their cost on
large corpora and paraphrased queries, neither of which applies yet. Both
are implemented so the claim can be demonstrated either way, and so that
when the corpus grows to hundreds of documents the switch is one env var.
"""
from __future__ import annotations

import logging
import math
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

CORPUS_DIR = Path(__file__).resolve().parent.parent.parent / "nhm_corpus"


@dataclass(frozen=True)
class ProtocolChunk:
    """One retrievable passage, and enough provenance to cite it.

    `title` and `source_url` ride with every chunk rather than being looked
    up later, because a citation that gets separated from its source on the
    way to the UI is indistinguishable from an invented one.
    """

    doc_id: str          # file stem, e.g. "antenatal_care"
    title: str           # the published document's title
    source_url: str
    publisher: str
    phase: str           # antenatal | postnatal | newborn | any
    heading: str         # the "## ..." this passage sits under
    text: str

    @property
    def citation(self) -> str:
        return f"{self.title} — {self.heading}"


# ---------------------------------------------------------------------------
# Corpus loading
# ---------------------------------------------------------------------------

_FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.S)


def _parse_front_matter(raw: str) -> tuple[dict[str, str], str]:
    m = _FRONT_MATTER.match(raw)
    if not m:
        return {}, raw
    meta: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip()
    return meta, raw[m.end():]


def load_corpus(corpus_dir: Path | None = None) -> list[ProtocolChunk]:
    """Read every .md in the corpus and split it on `##` headings.

    Headings are the chunk boundary rather than a fixed token count,
    because the source documents are already organised by clinical topic
    and a chunk is what an ASHA ends up reading as the justification for a
    risk flag. A 512-token window cutting across "when to refer for
    anaemia" and "IFA dosing" retrieves for both and explains neither.

    README.md is skipped: it documents the corpus rather than being part
    of it, and it would otherwise match every query containing "anaemia"
    or "referral".
    """
    directory = corpus_dir or CORPUS_DIR
    if not directory.is_dir():
        logger.warning("NHM corpus directory not found at %s; retrieval disabled", directory)
        return []

    chunks: list[ProtocolChunk] = []
    for path in sorted(directory.glob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        meta, body = _parse_front_matter(path.read_text(encoding="utf-8"))
        title = meta.get("title", path.stem.replace("_", " ").title())
        for section in body.split("\n## "):
            section = section.strip()
            if not section:
                continue
            heading, _, text = section.partition("\n")
            heading = heading.lstrip("# ").strip()
            text = text.strip()
            if not text:
                continue
            chunks.append(ProtocolChunk(
                doc_id=path.stem,
                title=title,
                source_url=meta.get("source_url", ""),
                publisher=meta.get("publisher", ""),
                phase=meta.get("phase", "any"),
                heading=heading,
                text=text,
            ))
    return chunks


# ---------------------------------------------------------------------------
# Tokenisation
# ---------------------------------------------------------------------------

# Kept deliberately dumb, with one exception. "140/90" and "7 g/dL" are the
# most discriminating tokens in this whole corpus -- they are the actual
# thresholds -- so the number pattern keeps decimals and slashed pairs
# together instead of shattering them into "140", "90", "7".
_TOKEN = re.compile(r"[a-z]+|\d+(?:[./]\d+)*")

# Words that appear in nearly every chunk of clinical guidance and so
# discriminate nothing. Not a general English stop-list: "refer" and
# "pregnant" are dropped because this corpus is *entirely* about referring
# pregnant women, which makes them noise here specifically.
_STOP = frozenset("""
a an and the of to in for is are be been at on or if it its with without
that this these those as by from any all more than not no her she woman
women pregnant pregnancy refer referral should must may can will need
""".split())


def tokenise(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOP and len(t) > 1]


# ---------------------------------------------------------------------------
# Lexical backend: BM25
# ---------------------------------------------------------------------------

class LexicalRetriever:
    """BM25 over the corpus.

    BM25 rather than plain TF-IDF for one property that matters here: term
    saturation. A chunk repeating "anaemia" nine times is not nine times
    more about anaemia than one mentioning it once, and TF-IDF thinks it
    is. With chunks of uneven length -- a two-line threshold list beside a
    forty-line management section -- that difference decides whether short,
    precise chunks can ever win.
    """

    K1 = 1.5   # term-frequency saturation
    B = 0.75   # length normalisation

    # Multiplier applied to a chunk whose phase of care does not match the
    # visit's. Not a filter: postnatal guidance can still be the right
    # answer for a woman six weeks after delivery whose record still says
    # "9 months", and hard-excluding it would return nothing at all for
    # cases the corpus does cover.
    #
    # It exists because the corpus repeats itself across phases. "Swelling
    # on face, hands and legs" is listed verbatim in both the antenatal
    # and postnatal danger signs, and the postnatal list is longer, so a
    # seven-months-pregnant woman with BP 150/100 and facial swelling
    # retrieved *postnatal* guidance above the antenatal blood-pressure
    # thresholds -- the right clinical concern, from the wrong stage of
    # care. 0.35 is enough to reorder that without silencing the chunk.
    PHASE_MISMATCH = 0.35

    def __init__(self, chunks: list[ProtocolChunk]):
        self.chunks = chunks
        # The heading is indexed alongside the body, weighted by repetition:
        # "Blood pressure thresholds in pregnancy" is the most on-topic
        # sentence in its chunk and would otherwise count for one line in
        # forty.
        self._docs = [tokenise(c.heading) * 3 + tokenise(c.text) for c in chunks]
        self._tf = [Counter(d) for d in self._docs]
        self._len = [len(d) or 1 for d in self._docs]
        self._avg_len = (sum(self._len) / len(self._len)) if self._len else 1.0

        df = Counter()
        for d in self._docs:
            df.update(set(d))
        n = len(self._docs)
        # The +0.5 smoothing is standard BM25 and stops a term present in
        # every chunk from producing a negative weight.
        self._idf = {
            term: math.log(1 + (n - freq + 0.5) / (freq + 0.5))
            for term, freq in df.items()
        }

    def search(self, query: str, k: int = 3, phase: str | None = None) -> list[tuple[ProtocolChunk, float]]:
        terms = tokenise(query)
        if not terms or not self.chunks:
            return []
        scored: list[tuple[ProtocolChunk, float]] = []
        for i, tf in enumerate(self._tf):
            score = 0.0
            for term in terms:
                f = tf.get(term)
                if not f:
                    continue
                norm = 1 - self.B + self.B * self._len[i] / self._avg_len
                score += self._idf.get(term, 0.0) * (f * (self.K1 + 1)) / (f + self.K1 * norm)
            chunk = self.chunks[i]
            if phase and chunk.phase not in (phase, "any"):
                score *= self.PHASE_MISMATCH
            if score > 0:
                scored.append((chunk, score))
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:k]


# ---------------------------------------------------------------------------
# Chroma backend
# ---------------------------------------------------------------------------

class ChromaRetriever:
    """ChromaDB with its default sentence-embedding function.

    In-memory and rebuilt at startup rather than persisted: the corpus is
    tens of chunks, embedding it takes about a second, and a persisted
    index is one more thing that can be stale relative to the files on
    disk. Persist it when the corpus is large enough that startup cost
    shows, not before.
    """

    def __init__(self, chunks: list[ProtocolChunk]):
        import chromadb  # imported here: absent unless RETRIEVAL_PROVIDER=chroma

        self.chunks = chunks
        self._by_id = {f"{c.doc_id}::{i}": c for i, c in enumerate(chunks)}
        client = chromadb.EphemeralClient()
        self._collection = client.create_collection("nhm_protocols")
        if chunks:
            ids = list(self._by_id)
            self._collection.add(
                ids=ids,
                documents=[f"{self._by_id[i].heading}\n{self._by_id[i].text}" for i in ids],
                metadatas=[{"doc_id": self._by_id[i].doc_id} for i in ids],
            )

    def search(self, query: str, k: int = 3, phase: str | None = None) -> list[tuple[ProtocolChunk, float]]:
        if not self.chunks:
            return []
        # Over-fetch, then reorder by phase in Python. Chroma could filter
        # on the metadata instead, but a `where` clause is a hard exclusion
        # and this has to be a demotion -- see LexicalRetriever.
        res = self._collection.query(query_texts=[query], n_results=len(self.chunks))
        out: list[tuple[ProtocolChunk, float]] = []
        for cid, dist in zip(res["ids"][0], res["distances"][0]):
            chunk = self._by_id.get(cid)
            if chunk is not None:
                # Chroma returns a distance; invert it so both backends
                # hand back "bigger is better" and callers need not care
                # which one answered.
                score = 1.0 / (1.0 + dist)
                if phase and chunk.phase not in (phase, "any"):
                    score *= LexicalRetriever.PHASE_MISMATCH
                out.append((chunk, score))
        out.sort(key=lambda pair: pair[1], reverse=True)
        return out[:k]


class NullRetriever:
    """RETRIEVAL_PROVIDER=none, and the landing place for every failure.

    Returns nothing, so Agent 2 falls back to the deterministic thresholds
    -- which is the behaviour that existed before this module and is safe
    on its own. Retrieval adds explanation; it is not load-bearing for the
    classification, and it must never be able to take the classification
    down with it.
    """

    chunks: list[ProtocolChunk] = []

    def search(self, query: str, k: int = 3, phase: str | None = None) -> list[tuple[ProtocolChunk, float]]:
        return []


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def get_retriever():
    """The retriever for the configured provider, built once per process.

    Cached because building it reads every file in the corpus and, on the
    chroma path, embeds them -- per-request would be absurd. Cleared in
    tests via get_retriever.cache_clear().

    Any failure degrades to NullRetriever rather than raising: a missing
    corpus directory, an unparseable file or an uninstalled chromadb
    should cost you citations, not the ability to classify a visit.
    """
    from app.core.config import get_settings

    provider = (get_settings().retrieval_provider or "lexical").lower()
    if provider == "none":
        return NullRetriever()

    try:
        chunks = load_corpus()
    except Exception:  # noqa: BLE001 -- see docstring
        logger.exception("NHM corpus failed to load; retrieval disabled")
        return NullRetriever()

    if not chunks:
        logger.warning("NHM corpus is empty; retrieval disabled")
        return NullRetriever()

    if provider == "chroma":
        try:
            return ChromaRetriever(chunks)
        except Exception:  # noqa: BLE001 -- chromadb missing, or model download blocked
            logger.exception("ChromaDB retriever unavailable; falling back to lexical")
            return LexicalRetriever(chunks)

    return LexicalRetriever(chunks)


def retrieve(query: str, k: int = 3, phase: str | None = None) -> list[ProtocolChunk]:
    """Top-k passages for a free-text clinical query, best first.

    `phase` is "antenatal", "postnatal" or "newborn" when the caller knows
    which stage of care the visit belongs to; passages from another stage
    are demoted rather than dropped.
    """
    try:
        return [chunk for chunk, _ in get_retriever().search(query, k=k, phase=phase)]
    except Exception:  # noqa: BLE001 -- see get_retriever
        logger.exception("retrieval failed for query %r", query[:80])
        return []
