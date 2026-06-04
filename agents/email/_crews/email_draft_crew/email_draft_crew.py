"""CrewAI @CrewBase crew — email draft sub-pipeline.

Three-agent sequential crew that drafts a reply for one email:
  - Email Triage Analyst  → structured analysis brief
  - Reply Writer          → draft body
  - Voice Polisher        → tone-adjusted + JSON DraftItem output

Usage (from LangGraph ``draft`` node):
    from _crews.email_draft_crew.email_draft_crew import EmailDraftCrew

    crew = EmailDraftCrew().crew()
    result = crew.kickoff(inputs={
        "email_sender": "...",
        "email_subject": "...",
        "email_body": "...",
        ...
    })

Variables in YAML (like {email_subject}) are replaced by CrewAI at
kickoff time using the ``inputs`` dict.
"""
from __future__ import annotations

from crewai import Agent, Crew, Process, Task
from crewai.agents.agent_builder.base_agent import BaseAgent
from crewai.project import CrewBase, agent, crew, task

from _llm import get_crewai_llm, get_env
from _models import DraftItem
from _tools import TemplateTool, ThreadContextTool, ToneTool


def _get_llm():
    """Lazy LLM access — uses the module-level singleton from _llm.py.
    Called at crew instantiation time (first request), not at import time."""
    import os
    env = {
        "AI_GATEWAY_API_KEY": os.environ.get("AI_GATEWAY_API_KEY", ""),
        "AI_GATEWAY_BASE_URL": os.environ.get("AI_GATEWAY_BASE_URL", ""),
    }
    return get_crewai_llm(env)


@CrewBase
class EmailDraftCrew:
    """Three-role sequential crew for drafting one email reply.

    Mirrors the platform crewai-planner-python template's @CrewBase pattern.
    """

    agents: list[BaseAgent]
    tasks: list[Task]

    agents_config = "../agents.yaml"
    tasks_config = "config/tasks.yaml"

    @agent
    def email_triage_analyst(self) -> Agent:
        return Agent(
            config=self.agents_config["email_triage_analyst"],  # type: ignore[index]
            llm=_get_llm(),
            tools=[ThreadContextTool()],
            allow_delegation=False,
            memory=False,
            verbose=False,
        )

    @agent
    def reply_writer(self) -> Agent:
        return Agent(
            config=self.agents_config["reply_writer"],  # type: ignore[index]
            llm=_get_llm(),
            tools=[TemplateTool()],
            allow_delegation=False,
            memory=False,
            verbose=False,
        )

    @agent
    def voice_polisher(self) -> Agent:
        return Agent(
            config=self.agents_config["voice_polisher"],  # type: ignore[index]
            llm=_get_llm(),
            tools=[ToneTool()],
            allow_delegation=False,
            memory=False,
            verbose=False,
        )

    @task
    def analyze_task(self) -> Task:
        return Task(
            config=self.tasks_config["analyze_task"],  # type: ignore[index]
            agent=self.email_triage_analyst(),
        )

    @task
    def draft_task(self) -> Task:
        return Task(
            config=self.tasks_config["draft_task"],  # type: ignore[index]
            agent=self.reply_writer(),
            context=[self.analyze_task()],
        )

    @task
    def polish_task(self) -> Task:
        return Task(
            config=self.tasks_config["polish_task"],  # type: ignore[index]
            agent=self.voice_polisher(),
            context=[self.draft_task(), self.analyze_task()],
            output_pydantic=DraftItem,
        )

    @crew
    def crew(self) -> Crew:
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            memory=False,
            verbose=False,
        )
