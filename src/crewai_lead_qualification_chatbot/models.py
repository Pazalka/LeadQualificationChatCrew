from typing import Optional, List
from pydantic import BaseModel

class ScoreState(BaseModel):
    score: int
    quality: str
    reasons: List[str]

class MeetingState(BaseModel):
    message: str

class ChatState(BaseModel):
    id: str = ""
    message: Optional[str] = None
    history: Optional[str] = None

    # LeadData
    full_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    property_type: Optional[str] = None
    price_range: Optional[str] = None
    location: Optional[str] = None
    timeline: Optional[str] = None
    financing: Optional[str] = None
    other_agents: Optional[str] = None
    search_reason: Optional[str] = None

    # QuestionState
    current_question_id: str = ""
    current_question_text: str = ""
    next_question_id: str = ""
    next_question_text: str = ""
    is_complete: bool = False
