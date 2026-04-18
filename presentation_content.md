# Presentation: Project P.R.O.F. (Programmed Routine for Operational Flow)

## Slide 1: Title Slide

**Title:** P.R.O.F. - The Autonomous Class Coordinator
**Subtitle:** Revolutionizing Academic Communication with Agentic AI
**Presented By:** [Your Name/Group Name]
**Date:** [Current Date]

**Speaker Notes:**
Good morning/afternoon everyone. Today, we are excited to present our final year project, "P.R.O.F." or Programmed Routine for Operational Flow. This project represents a leap forward in how we handle daily academic logistics, moving from manual coordination to a fully autonomous, AI-driven system.

---

## Slide 2: The Problem Statement

**Headline:** The Chaos of Manual Coordination

**Key Points:**
*   **Daily Struggle:** Class representatives spend hours daily calling/messaging professors to confirm schedules.
*   **Communication Gap:** Information is often delayed, leading to students waiting for classes that are cancelled.
*   **Unstructured Data:** Professors reply in natural language ("I'll be late", "Not today", "Yes"), which is hard to automate with simple rules.
*   **Inefficiency:** The process is repetitive, error-prone, and dependent on human availability.

**Speaker Notes:**
We identified a critical inefficiency in our daily college life. Every day, class representatives act as middlemen, manually contacting teachers to check if classes are on. This leads to miscommunication, late updates, and wasted time. The core issue is that human communication is messy—teachers don't reply with "True" or "False"; they use natural language, making standard automation impossible.

---

## Slide 3: The Solution - P.R.O.F.

**Headline:** An Intelligent, Autonomous Agent

**Key Points:**
*   **What is it?** An AI-powered bot that acts as a liaison between faculty and students.
*   **Core Function:** Automatically contacts teachers via WhatsApp, interprets their replies using AI, and notifies students.
*   **Key Differentiator:** Uses Large Language Models (LLMs) to understand context, nuance, and intent, not just keywords.
*   **Goal:** Zero-touch coordination. The system runs itself.

**Speaker Notes:**
Our solution is P.R.O.F. It's not just a chatbot; it's an autonomous agent. It proactively initiates conversations based on the class schedule, understands the semantic meaning of the professor's reply—whether it's in English, Hindi, or Hinglish—and then broadcasts the update to the students. It effectively replaces the manual "middleman" role with an intelligent system.

---

## Slide 4: System Architecture

**Headline:** How It Works Under the Hood

**Key Points:**
*   **The Brain (Logic Layer):** Python-based controller (`prof.py`) that orchestrates the workflow.
*   **The Interface (Web Automation):** Selenium WebDriver automates a real Chrome browser to interact with WhatsApp Web.
*   **The Intelligence (AI Layer):** Integration with Cloud APIs (e.g., Google Gemini / OpenAI) for high-level reasoning.
*   **The Database:** A JSON-based routine file (`routine.json`) acting as the source of truth for the schedule.

**Speaker Notes:**
The system is built on three main pillars. First, the Python logic which manages the schedule. Second, Selenium, which drives a real web browser to send and receive messages on WhatsApp, mimicking human behavior. And third, the Intelligence layer, where we connect to powerful Cloud APIs to process and understand the text data we receive.

---

## Slide 5: The Workflow - Step 1: Initiation

**Headline:** Waking Up and Reaching Out

**Key Points:**
*   **Daily Trigger:** The system wakes up at a scheduled time (e.g., 8:00 AM).
*   **Schedule Parsing:** Reads `routine.json` to identify today's classes.
*   **Message Dispatch:**
    *   Locates the professor's contact on WhatsApp.
    *   Sends a polite, context-aware query: *"Hello [Name], do you have the [Subject] class today?"*
*   **State Tracking:** Marks the class status as `WAITING_FOR_CONFIRMATION`.

**Speaker Notes:**
The workflow begins automatically. The bot reads the day's schedule and sends out inquiries. It's important to note that it tracks the state of every conversation. It knows who it has messaged and who it is waiting for, maintaining a state machine for every class slot.

---

## Slide 6: The Workflow - Step 2: Perception

**Headline:** Listening and Detecting Replies

**Key Points:**
*   **Polling Mechanism:** The bot continuously monitors the chat window for new incoming messages.
*   **Filtering:** Distinguishes between its own sent messages and the professor's replies.
*   **Sanitization:** Cleans the text input (removing timestamps, system messages) to prepare it for the AI.
*   **Real-time Response:** Detects replies within seconds of them being sent.

**Speaker Notes:**
Once messages are sent, the bot enters a "listening" phase. It polls the browser DOM to detect new message bubbles. It's smart enough to ignore its own messages and only focus on what the professor says. Once a new message is detected, it's extracted for analysis.

---

## Slide 7: The Workflow - Step 3: Cognition (AI Analysis)

**Headline:** Understanding Intent with LLMs

**Key Points:**
*   **The Challenge:** "I might be 10 mins late" vs "Cancel it".
*   **The Process:**
    1.  Construct a Prompt: Includes the teacher's name, subject, reply text, and conversation history.
    2.  API Call: Sends this packet to the Cloud LLM (Gemini/GPT).
    3.  Intent Classification: The AI categorizes the reply into: `CONFIRMED`, `CANCELLED`, `RESCHEDULED`, or `UNCERTAIN`.
*   **Context Awareness:** The AI understands follow-up messages (e.g., "Actually, never mind, I will come").

**Speaker Notes:**
This is the core innovation. We don't use `if reply == "yes"`. We feed the entire context to a Large Language Model. If a teacher says "I'm stuck in traffic, start 15 mins late", the AI correctly tags this as `RESCHEDULED` and extracts the new time. This level of understanding is what makes the system robust.

---

## Slide 8: The Workflow - Step 4: Action

**Headline:** Closing the Loop

**Key Points:**
*   **Decision Tree:**
    *   **If Uncertain:** Bot asks: *"Could you please clarify?"*
    *   **If Confirmed:** Bot asks: *"Any specific instructions?"*
    *   **If Cancelled:** Bot proceeds to notify students.
*   **Notification Generation:** The AI drafts a fun, emoji-rich message for the students (e.g., "Sleep in! Class is cancelled! 🥳").
*   **Broadcast:** The message is forwarded to the official Class Group.

**Speaker Notes:**
Based on the AI's classification, the bot takes action. It's agentic—it decides what to do next. If it needs clarification, it asks. If it has all the info, it informs the students. We specifically instructed the AI to generate "fun" announcements to keep student engagement high.

---

## Slide 9: Why Cloud APIs?

**Headline:** Power vs. Efficiency

**Key Points:**
*   **Reasoning Capability:** Cloud models (GPT-4, Gemini 1.5) have superior reasoning compared to small local models.
*   **Reliability:** 99.9% uptime and consistent API responses.
*   **Speed:** Fast inference times without overheating the local machine.
*   **Scalability:** Can handle multiple conversations simultaneously without hardware bottlenecks.
*   **Ease of Update:** We always have access to the latest model without downloading gigabytes of weights.

**Speaker Notes:**
We chose to move from local models to Cloud APIs for reliability and intelligence. While local models are great for privacy, Cloud APIs give us the "brain power" needed to understand complex, ambiguous human language accurately. It ensures our bot doesn't make embarrassing mistakes.

---

## Slide 10: Technology Stack

**Headline:** Tools of the Trade

**Key Points:**
*   **Language:** Python 3.9+ (Robust, vast library support).
*   **Automation:** Selenium WebDriver (Browser control).
*   **AI/ML:** Google Gemini API / OpenAI API (Intelligence).
*   **Data:** JSON (Lightweight data storage).
*   **Environment:** `python-dotenv` for security (API Key management).

**Speaker Notes:**
Our stack is industry-standard. Python provides the glue code. Selenium handles the "robotic process automation" part. And the API provides the intelligence. We also use best practices like environment variables to keep our API keys secure.

---

## Slide 11: Challenges & Solutions

**Headline:** Overcoming Obstacles

**Key Points:**
*   **Challenge:** WhatsApp Web DOM changes frequently.
    *   *Solution:* Robust XPath selectors and dynamic waiting (WebDriverWait).
*   **Challenge:** Infinite Loops (Bot replying to itself).
    *   *Solution:* Strict checks on "message-in" vs "message-out" classes.
*   **Challenge:** Ambiguous Replies ("Okay").
    *   *Solution:* Feeding conversation history to the AI so it knows "Okay" refers to the previous question.

**Speaker Notes:**
Building this wasn't easy. WhatsApp isn't designed for bots, so we had to build robust scrapers that can handle dynamic page loading. We also had to solve logic loops where the bot would get confused by its own messages. Context-aware AI was the key to solving ambiguity.

---

## Slide 12: Ethical Considerations

**Headline:** AI with Responsibility

**Key Points:**
*   **Privacy:** We only process messages related to class schedules.
*   **Transparency:** The bot identifies itself as an "Automated Coordinator" in the first message.
*   **Human-in-the-loop:** The system is designed to ask for clarification rather than guessing if it's unsure.
*   **Data Security:** API usage adheres to standard data protection policies.

**Speaker Notes:**
We are mindful of ethics. The bot clearly declares it is a machine. It is designed to be conservative—if it's 90% sure, it still asks for clarification to avoid sending wrong info to 60+ students.

---

## Slide 13: Future Scope

**Headline:** What's Next for P.R.O.F.?

**Key Points:**
*   **Multi-Platform Support:** Expanding to Telegram, Slack, and Email.
*   **Voice Integration:** Calling professors who don't reply to texts.
*   **Calendar Integration:** Automatically updating Google Calendar/Outlook for students.
*   **LMS Integration:** Posting updates directly to Moodle/Canvas.
*   **Personalized Assistant:** Allowing students to query the bot individually ("When is the next exam?").

**Speaker Notes:**
This is just the beginning. We plan to integrate Voice AI to actually call professors. We also want to link it to Google Calendar so your phone automatically goes to "Do Not Disturb" when a class is confirmed.

---

## Slide 14: Impact Analysis

**Headline:** The Value Proposition

**Key Points:**
*   **Time Saved:** ~30 minutes per day for class representatives.
*   **Accuracy:** Reduced misinformation and rumors about class cancellations.
*   **Student Satisfaction:** Instant, fun updates directly on their phones.
*   **Modernization:** Showcases the college's adoption of cutting-edge AI technology.

**Speaker Notes:**
The impact is tangible. We save time, reduce stress, and improve the quality of life for students. It also serves as a great showcase of how our department is applying modern AI to solve real-world problems.

---

## Slide 15: Conclusion

**Headline:** Redefining Routine

**Key Points:**
*   P.R.O.F. successfully demonstrates the power of **Agentic AI**.
*   It bridges the gap between **unstructured human communication** and **structured digital schedules**.
*   It is a scalable, efficient, and intelligent solution for modern academic management.

**Closing:**
Thank you for your attention. We are now open for questions.

**Speaker Notes:**
In conclusion, P.R.O.F. is more than a project; it's a vision of an automated future where AI handles the mundane, leaving us free to focus on learning. Thank you.
