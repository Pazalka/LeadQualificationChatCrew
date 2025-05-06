import yaml
from pathlib import Path


class QuestionManager:
    def __init__(self):
        self.questions = self._load_questions()
        self.total_questions = len(self.questions)

    def _load_questions(self):
        questions_path = Path(__file__).parent / "questions.yaml"
        with open(questions_path, "r") as file:
            data = yaml.safe_load(file)
            return data["questions"]

    def get_question(self, question_id: str) -> tuple[str, str]:
        """Get question text and ID for a given question number"""
        if question_id not in self.questions:
            return "", ""
        return self.questions[question_id]["question"], question_id

    def get_next_question(self, current_id: str) -> tuple[str, str]:
        """Get the next question text and ID"""
        if current_id not in self.questions:
            return "", ""
            
        next_id = self.questions[current_id]["next"]
        if next_id == "end" or next_id not in self.questions:
            return "", ""
            
        return self.questions[next_id]["question"], next_id

    def get_field_id(self, question_id: str) -> str:
        """Get the field ID for a question"""
        if question_id not in self.questions:
            return ""
        return self.questions[question_id]["id"]

    def is_last_question(self, question_id: str) -> bool:
        """Check if this is the last question"""
        if question_id not in self.questions:
            return True
        return self.questions[question_id]["next"] == "end"
