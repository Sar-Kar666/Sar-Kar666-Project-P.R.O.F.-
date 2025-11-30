# Project Antigravity 🚀
**Autonomous Class Coordinator Bot**

## Overview
Project Antigravity is an AI-powered automation tool designed to streamline class coordination for college students. It autonomously contacts teachers via WhatsApp, confirms class schedules, handles cancellations/rescheduling, and broadcasts updates to student groups.

## Features
- **Autonomous Scheduling**: Runs daily on a set schedule.
- **AI-Powered**: Uses Google Gemini Pro to understand natural language replies from teachers.
- **Multi-turn Conversation**: Asks follow-up questions for specific instructions.
- **Robust Automation**: Handles network issues, emoji inputs, and WhatsApp Web UI changes.

## Setup
1.  **Install Dependencies**:
    ```bash
    pip install selenium webdriver-manager google-generativeai
    ```
2.  **Configuration**:
    - Update `routine.json` with your class schedule.
    - Set your `GEMINI_API_KEY` in `antigravity.py` (or use env vars).
3.  **Run**:
    ```bash
    python antigravity.py --continuous
    ```

## Usage
- **Manual Run**: Double-click `start_antigravity.bat`.
- **Demo Mode**: Run with `--demo` flag for faster testing.

## Tech Stack
- Python
- Selenium WebDriver
- Google Gemini API
