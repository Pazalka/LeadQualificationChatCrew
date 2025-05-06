#!/usr/bin/env python
from crewai.flow import Flow, listen, start, persist, router, or_
from src.crewai_lead_qualification_chatbot.crews.chat_crew.chat_crew import ChatCrew
from src.crewai_lead_qualification_chatbot.question_manager import QuestionManager
from src.crewai_lead_qualification_chatbot.models import ChatState
import gradio as gr
import uuid
from typing import List, Dict, Any
from datetime import datetime
from dotenv import load_dotenv
from composio_crewai import ComposioToolSet
import os

load_dotenv()

composio_toolset = ComposioToolSet(api_key=os.getenv("COMPOSIO_API_KEY"))
tools = composio_toolset.get_tools(actions=['GOOGLECALENDAR_CREATE_EVENT'])



@persist()
class ChatFlow(Flow[ChatState]):
    def __init__(self, persistence=None):
        super().__init__(persistence=persistence)
        self.question_manager = QuestionManager()

    @start()
    def initialize_chat(self):
        if not self.state.current_question_id:
            self.state.current_question_text, self.state.current_question_id = (
                self.question_manager.get_question("q1")
            )
            self.state.next_question_text, self.state.next_question_id = (
                self.question_manager.get_next_question("q1")
            )

            return "send_response_request"

        return "process_response_request"

    @router(initialize_chat)
    def route_request(self, classification: str):
        return classification

    @listen("process_response_request")
    def process_response(self) -> str:
        result = (
            ChatCrew()
            .crew_chat()
            .kickoff(
                inputs={
                    "state": self.state.model_dump(),
                    "message": self.state.message,
                    "current_question_text": self.state.current_question_text,
                    "history": self.state.history,
                }
            )
        )

        # clear previous message
        self.state.message = ""
        new_state = result.pydantic.model_dump()
        self.state.message = new_state["message"]

        # if the current question was answered, update state
        field_id = self.question_manager.get_field_id(self.state.current_question_id)
        if new_state.get(field_id):
            for key, value in new_state.items():
                if hasattr(self.state, key):
                    setattr(self.state, key, value)

            # advance to next or finish
            if self.question_manager.is_last_question(self.state.current_question_id):
                self.state.is_complete = True
            else:
                self.state.current_question_id = self.state.next_question_id
                self.state.current_question_text = self.state.next_question_text
                nxt_text, nxt_id = self.question_manager.get_next_question(
                    self.state.current_question_id
                )
                self.state.next_question_text = nxt_text
                self.state.next_question_id = nxt_id

        return "send_response"

    @listen(or_("send_response_request", "process_response_request"))
    def send_response(self) -> str:
        # Once all questions are answered, score (and maybe schedule)
        if self.state.is_complete:
            crew = ChatCrew()

            # 2) Score the lead
            score_task = crew.score_lead()
            scorer_agent = crew.lead_scorer()
            score_output = score_task.execute_sync(
                agent=scorer_agent,
                context=self.state.model_dump_json()
            ).pydantic

            score = score_output.score
            quality = score_output.quality
            reasons = score_output.reasons

            summary = (
                    f"🎯 Your Lead Score: {score}/100 ({quality})\n"
                    "Scoring Details:\n" +
                    "\n".join(f"- {r}" for r in reasons)
            )

            # 3) If Warm/Hot, schedule meeting
            if score > 50:
                sched_task = crew.schedule_meeting()
                scheduler_agent = crew.meeting_scheduler()
                sched_output = sched_task.execute_sync(
                    agent=scheduler_agent,
                    context=self.state.model_dump_json(),
                    tools=list(tools)
                ).pydantic

                return summary + "\n\n" + sched_output.message

            # 4) Otherwise, end politely
            return (
                    summary + "\n\n"
                              "Thank you for your time! It seems we’re not the best fit right now, "
                              "but we’ll keep you in mind for future opportunities."
            )

        # Mid-conversation: ask next question (or repeat clarification)
        return (
            self.state.current_question_text
            if not self.state.message
            else self.state.message
        )


class ChatbotInterface:
    def __init__(self):
        self.chat_flows = {}
        self.chat_id = None

    def chat(self, message: str, history: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Process chat messages and maintain conversation history"""
        if not self.chat_id or not message:
            # Initialize new chat session
            self.chat_id = str(uuid.uuid4())
            self.chat_flows[self.chat_id] = ChatFlow()
            response = self._process_message("", self.chat_id, history)
            return [{"role": "assistant", "content": response}]

        # Process user message
        response = self._process_message(message, self.chat_id, history)

        # Create a new history list to avoid modifying the input
        new_history = history.copy()
        new_history.append({"role": "user", "content": message})
        new_history.append({"role": "assistant", "content": response})
        return [{"role": "assistant", "content": response}]

    def _process_message(
        self, message: str, chat_id: str, history: List[Dict[str, Any]] = []
    ) -> str:
        """Process a message through the chat flow"""
        chat_flow = self.chat_flows[chat_id]

        result = chat_flow.kickoff(
            inputs={
                "id": chat_id,
                "message": message,
                "history": (
                    "\n".join(f"{msg['role']}: {msg['content']}" for msg in history)
                    if history
                    else ""
                ),
            }
        )
        return result


def create_lead_qualification_chatbot() -> gr.Blocks:
    """Create and configure the lead qualification chatbot"""
    chatbot = ChatbotInterface()

    demo = gr.ChatInterface(
        chatbot.chat,
        chatbot=gr.Chatbot(
            label="Lead Qualification Chat",
            height=600,
            show_copy_button=True,
            type="messages",
        ),
        textbox=gr.Textbox(
            placeholder="Type your response here",
            container=True,
            scale=7,
            show_label=False,
        ),
        submit_btn="Send",
        title="Lead Qualification Chatbot",
        description="I'll help qualify you as a potential lead by asking a series of questions about your real estate needs.",
        theme="soft",
        examples=[
            "Hi, I'm looking to buy a property",
            "Hi, I'm looking to rent a property",
        ],
        type="messages",
        autofocus=True,
    )

    return demo


if __name__ == "__main__":
    chatbot = create_lead_qualification_chatbot()
    chatbot.launch(share=True)
