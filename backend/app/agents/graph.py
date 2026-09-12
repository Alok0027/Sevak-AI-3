"""LangGraph wiring for Agents 1-4 (SRS section 5.2 data flow).

Agent 2 fans out to Agent 3 and Agent 4 in parallel branches, mirroring the
architecture diagram (deck slide 6/7: "Risk Assessment -> Decision Support"
and "-> Report Generation" happen together) and the demo script's framing
("Agent 3 is generating... Agent 4 is updating... All simultaneously").
Agent 5 is intentionally not a node here -- see agent5_escalation.py.
"""
from langgraph.graph import END, StateGraph

from app.agents import agent1_voice_comprehension as agent1
from app.agents import agent2_risk_classification as agent2
from app.agents import agent3_action_generation as agent3
from app.agents import agent4_reporting as agent4
from app.agents.state import PipelineState
from app.services.bhashini_client import BhashiniClientBase
from app.services.llm_client import LLMClientBase
from app.services.sms_client import SmsClientBase
from app.services.whatsapp_client import WhatsAppClientBase


def build_pipeline_graph(
    bhashini_client: BhashiniClientBase,
    llm_client: LLMClientBase,
    whatsapp_client: WhatsAppClientBase,
    sms_client: SmsClientBase,
):
    graph = StateGraph(PipelineState)

    async def node_transcribe(state: PipelineState) -> dict:
        # FR-01.4: a confirmed (possibly hand-edited) transcript always wins
        # -- never silently re-transcribe over what the ASHA already
        # reviewed and approved.
        confirmed = state.get("confirmed_transcript")
        if confirmed:
            return {"transcript": confirmed}
        transcript = await bhashini_client.transcribe(state["audio_base64"], state["language_code"])
        return {"transcript": transcript}

    async def node_agent1(state: PipelineState) -> dict:
        # Same rule as the transcript above: fields the ASHA has already
        # reviewed and corrected win over a fresh extraction.
        confirmed = state.get("confirmed_extracted")
        if confirmed:
            return {"extracted": confirmed}
        extracted = await agent1.extract_with_llm(state["transcript"], llm_client)
        return {"extracted": extracted}

    async def node_agent2(state: PipelineState) -> dict:
        result = await agent2.classify_with_llm(state["extracted"], llm_client)
        return {
            "risk_level": result.risk_level,
            "risk_score": result.risk_score,
            "risk_drivers": result.drivers,
        }

    async def node_agent3(state: PipelineState) -> dict:
        patient_name = state.get("patient_name") or state["extracted"].patient_name or "Patient"
        actions = await agent3.generate(
            extracted=state["extracted"],
            risk_level=state["risk_level"],
            risk_drivers=state["risk_drivers"],
            patient_name=patient_name,
            patient_phone=state.get("patient_phone"),
            llm_client=llm_client,
            whatsapp_client=whatsapp_client,
            sms_client=sms_client,
        )
        return {"actions": actions}

    async def node_agent4(state: PipelineState) -> dict:
        hmis_fields = agent4.build_visit_contribution(state["extracted"], state["risk_level"])
        return {"hmis_fields": hmis_fields}

    graph.add_node("transcribe", node_transcribe)
    graph.add_node("agent1_voice_comprehension", node_agent1)
    graph.add_node("agent2_risk_classification", node_agent2)
    graph.add_node("agent3_action_generation", node_agent3)
    graph.add_node("agent4_reporting", node_agent4)

    graph.set_entry_point("transcribe")
    graph.add_edge("transcribe", "agent1_voice_comprehension")
    graph.add_edge("agent1_voice_comprehension", "agent2_risk_classification")
    graph.add_edge("agent2_risk_classification", "agent3_action_generation")
    graph.add_edge("agent2_risk_classification", "agent4_reporting")
    graph.add_edge("agent3_action_generation", END)
    graph.add_edge("agent4_reporting", END)

    return graph.compile()
