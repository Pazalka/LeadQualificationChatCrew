import os

from crewai import Agent, Task, Crew, Process
from crewai.project import CrewBase, agent, crew, task
from src.crewai_lead_qualification_chatbot.models import ChatState,ScoreState, MeetingState

@CrewBase
class ChatCrew:
    """Chat Crew for Lead Qualification"""

    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    @agent
    def lead_qualifier(self) -> Agent:
        return Agent(
            config=self.agents_config["lead_qualifier"],
        )

    @agent
    def lead_scorer(self) -> Agent:
        return Agent(
            config=self.agents_config["lead_scorer"],
        )

    @agent
    def meeting_scheduler(self) -> Agent:
        return Agent(
            config=self.agents_config["meeting_scheduler"]
        )

    @task
    def qualify_lead(self) -> Task:
        return Task(
            config=self.tasks_config["qualify_lead"],
            output_pydantic=ChatState,
        )

    @task
    def score_lead(self) -> Task:
        return Task(
            config=self.tasks_config["score_lead"],
            output_pydantic=ScoreState,  # or a dedicated ScoreState if desired
        )

    @task
    def schedule_meeting(self) -> Task:
        return Task(
            config=self.tasks_config["schedule_meeting"],
            output_pydantic=MeetingState,  # or a MeetingState for stricter typing
        )

    @crew
    def crew_chat(self) -> Crew:
        """Creates the Lead Qualification Crew"""
        return Crew(
            agents=[self.lead_qualifier()],
            tasks=[self.qualify_lead()],
            process=Process.sequential,
            verbose=True,
        )
