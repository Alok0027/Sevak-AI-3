"""Agent 2 -- Risk Classification (FR-03). Thin wrapper around the NHM
protocol knowledge base so the graph node stays a one-line call; see
app/services/nhm_protocol_rag.py for the swap-to-real-RAG TODO."""
from app.schemas.visit import ExtractedFields
from app.services.nhm_protocol_rag import RiskResult, get_nhm_knowledge_base


def classify(extracted: ExtractedFields) -> RiskResult:
    kb = get_nhm_knowledge_base()
    return kb.classify(extracted)
