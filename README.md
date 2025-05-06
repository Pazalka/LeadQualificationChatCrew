# Lead Qualification Chatbot

An intelligent lead qualification chatbot built with CrewAI and Gradio, designed to engage potential real estate leads through natural conversation while collecting and scoring essential information.

## **Blog Post**: [Building a Lead Qualification Chatbot with CrewAI and Gradio](https://www.zinyando.com/building-a-lead-qualification-chatbot-with-crewai-and-gradio/)


![Screenshot 2025-02-15 at 18 36 14](https://github.com/user-attachments/assets/28e18bf1-7c4e-4217-8da2-d86082a2e84e)


## Features

- Natural conversation flow with intelligent response handling
- Industry-standard lead scoring system
- Real estate-specific qualification criteria
- Structured data collection for:
  - Contact Information
  - Property Preferences
  - Budget Range
  - Timeline
  - Financing Status
  - Motivation
- User-friendly Gradio chat interface
- Detailed lead quality analysis

## Lead Scoring Criteria

The chatbot uses a comprehensive 100-point scoring system:

1. Budget Alignment (30 points)
   - High budget (≥$500K): 30 points
   - Medium budget (≥$300K): 20 points
   - Lower budget: 10 points

2. Timeline Urgency (25 points)
   - Immediate/1 month: 25 points
   - 3-6 months: 15 points
   - Longer term: 5 points

3. Pre-approval Status (20 points)
   - Pre-approved: 20 points
   - In process: 10 points
   - Not started: 0 points

4. Agent Exclusivity (15 points)
   - Not working with other agents: 15 points
   - Considering others: 5 points
   - Working with others: 0 points

5. Motivation Clarity (10 points)
   - Clear, detailed motivation: 10 points
   - Basic motivation: 5 points
   - No clear motivation: 0 points

Lead Quality Categories:
- Hot: ≥80 points
- Warm: 50-79 points
- Cold: <50 points

## Installation

Ensure you have Python >=3.10 <3.13 installed on your system. This project uses [UV](https://docs.astral.sh/uv/) for dependency management.

1. Install UV:
```bash
pip install uv
```

2. Install dependencies:
```bash
crewai install
```

3. Set up environment:
   - Copy `.env.example` to `.env`
   - Add your `OPENAI_API_KEY`

## Usage

1. Start the chatbot:
```bash
python -m src.crewai_lead_qualification_chatbot.main
```

2. Access the chat interface:
   - Open your browser to the URL shown in the terminal
   - Start a conversation by introducing yourself
   - Follow the chatbot's questions to provide lead information

## Project Structure

```
src/crewai_lead_qualification_chatbot/
├── crews/                      # CrewAI configuration
│   └── chat_crew/
│       ├── config/
│       │   ├── tasks.yaml     # Task definitions
│       │   └── agents.yaml    # Agent definitions
│       └── chat_crew.py       # Crew implementation
├── models.py                   # Data models
├── question_manager.py         # Question flow management
├── main.py                    # Application entry point
└── questions.yaml             # Question definitions
```

## Customization

- Modify `questions.yaml` to change the qualification questions
- Update `tasks.yaml` to adjust agent behavior
- Edit `main.py` to customize the chat interface
- Adjust scoring criteria in the lead scoring calculation

## Support

For support and questions:
- Visit [CrewAI documentation](https://docs.crewai.com)
- Join the [CrewAI Discord](https://discord.com/invite/X4JWnZnxPb)
- Check the [CrewAI GitHub repository](https://github.com/joaomdmoura/crewai)

## License

MIT License - feel free to use this project as a template for your own lead qualification systems.
