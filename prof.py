import os
import json
import time
import argparse
import datetime
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import google.generativeai as genai
import platform

# --- Configuration ---
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# --- Configuration ---
# GEMINI_API_KEY is now loaded from .env
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    print("ERROR: GEMINI_API_KEY not found in .env file.")
    exit(1)

# WhatsApp Web Selectors (These may need updating if WhatsApp Web changes)
# Using generic XPaths where possible to be more robust
SEARCH_BOX_XPATH = '//div[@contenteditable="true"][@data-tab="3"]'
MESSAGE_BOX_XPATH = '//div[@contenteditable="true"][@data-tab="10"]'
LAST_MESSAGE_XPATH = '(//div[contains(@class, "message-in")])[last()]//span[contains(@class, "selectable-text")]'
CONTACT_NAME_ON_HEADER_XPATH = '//header//span[@title]'

# --- System Prompt ---
SYSTEM_PROMPT = """
You are 'P.R.O.F.' (Programmed Routine for Operational Flow). Your goal is to interpret college professor replies and inform students.

Input:
Teacher Name
Subject
Teacher's Reply Text
Teacher's Specific Instructions (Optional)
Context: The question you asked the teacher (e.g., "Do you have the class?")

Your Task:
Classify the status: CONFIRMED, CANCELLED, RESCHEDULED, or UNCERTAIN.
IMPORTANT: If the teacher says "Yes" or "I will take it" in response to "Do you have the class?", status is CONFIRMED.
Draft a concise, emoji-rich WhatsApp announcement for the students.
If RESCHEDULED: Clearly state the new time/venue.
If CANCELLED: Tell students to enjoy their free time.

Output Format:
Return ONLY a raw JSON object:
{ "status": "...", "announcement": "..." }

Examples:
1. Input: Reply="Yes", Context="Do you have the class?" -> Output: {"status": "CONFIRMED", "announcement": "..."}
2. Input: Reply="No", Context="Do you have the class?" -> Output: {"status": "CANCELLED", "announcement": "..."}
3. Input: Reply="I will take it at 10", Context="Do you have the class?" -> Output: {"status": "RESCHEDULED", "announcement": "..."}
4. Input: Reply="Yes", Context="Could you please clarify if the class is confirmed?" -> Output: {"status": "CONFIRMED", "announcement": "..."}
"""

def init_driver():
    """Initialize Chrome WebDriver with options."""
    print("Initializing Chrome Driver...")
    options = webdriver.ChromeOptions()
    options.add_argument("--start-maximized")
    
    # Persistent Login: Save session to a local folder
    script_dir = os.path.dirname(os.path.abspath(__file__))
    user_data_dir = os.path.join(script_dir, "chrome_data")
    options.add_argument(f"user-data-dir={user_data_dir}")
    print(f"Using Chrome user data dir: {user_data_dir}")

    # Automatically install/manage ChromeDriver
    service = Service(ChromeDriverManager().install())
    try:
        driver = webdriver.Chrome(service=service, options=options)
        return driver
    except Exception as e:
        if "Chrome failed to start: crashed" in str(e) or "DevToolsActivePort file doesn't exist" in str(e):
            print("\n" + "="*60)
            print("ERROR: Chrome failed to start.")
            print("Likely cause: Chrome is already running with the same profile.")
            print("SOLUTION: Please CLOSE ALL CHROME WINDOWS and try again.")
            print("="*60 + "\n")
        raise e

def load_routine(file_path):
    """Load the routine from a JSON file."""
    print(f"Loading routine from {file_path}...")
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Routine file not found: {file_path}")
    with open(file_path, 'r') as f:
        return json.load(f)

def wait_for_whatsapp_login(driver):
    """Wait for the user to scan the QR code."""
    print("Opening WhatsApp Web...")
    driver.get("https://web.whatsapp.com")
    
    # Check if already logged in by looking for search box immediately
    try:
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, SEARCH_BOX_XPATH))
        )
        print("Already logged in!")
        return
    except:
        print("Not logged in. Please scan the QR code.")

    # Wait until the search box is visible, indicating login is complete
    try:
        WebDriverWait(driver, 300).until( # Increased timeout for initial login
            EC.presence_of_element_located((By.XPATH, SEARCH_BOX_XPATH))
        )
        print("Login detected!")
    except Exception:
        print("Login timed out. Please restart the script and scan quickly.")
        pass

def open_chat(driver, contact_name):
    """Search for a contact and open their chat."""
    try:
        search_box = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable((By.XPATH, SEARCH_BOX_XPATH))
        )
        search_box.click()
        # Robust clear: Ctrl+A (or Cmd+A) -> Backspace
        modifier = Keys.COMMAND if platform.system() == 'Darwin' else Keys.CONTROL
        search_box.send_keys(modifier + "a")
        search_box.send_keys(Keys.BACKSPACE)
        time.sleep(0.5) 
        search_box.send_keys(contact_name)
        search_box.send_keys(Keys.ENTER)
        
        # Verify that the chat actually opened
        print(f"Verifying chat with {contact_name}...")
        try:
            # Wait for header to appear (specifically the chat header in #main)
            header = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.XPATH, "//div[@id='main']//header"))
            )
            
            # Check if contact name is in the header text (case-insensitive)
            # This is robust because it ignores DOM structure and just looks for the name
            if contact_name.lower() in header.text.lower():
                return True
            else:
                print(f"ERROR: Header mismatch. Expected '{contact_name}' in '{header.text}'")
                return False
        except Exception as e:
            print(f"ERROR: Could not verify chat with '{contact_name}'. {e}")
            return False
            
    except Exception as e:
        print(f"Failed to open chat with {contact_name}: {e}")
        return False

def send_whatsapp_message(driver, contact_name, message):
    """Search for a contact and send a message."""
    print(f"Sending message to {contact_name}...")
    if not open_chat(driver, contact_name):
        return False

    try:
        # Type and send message
        message_box = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable((By.XPATH, MESSAGE_BOX_XPATH))
        )
        message_box.click()
        
        # Check if message contains non-BMP characters (emojis)
        is_bmp = True
        for char in message:
            if ord(char) > 0xFFFF:
                is_bmp = False
                break
        
        if is_bmp:
            # Use standard send_keys for normal text (Reliable)
            message_box.send_keys(message)
            message_box.send_keys(Keys.ENTER)
        else:
            # Use JS for emojis (Workaround for ChromeDriver crash)
            driver.execute_script("""
                var elm = arguments[0], txt = arguments[1];
                elm.innerHTML = txt;
                elm.dispatchEvent(new Event('input', {bubbles: true}));
            """, message_box, message)
            time.sleep(1)
            
            # Force focus and trigger UI update
            message_box.click()
            message_box.send_keys(" ") 
            message_box.send_keys(Keys.BACKSPACE)
            
            # VERIFY: Check if text was actually inserted
            time.sleep(1)
            box_text = message_box.text
            if not box_text or len(box_text.strip()) == 0:
                print("WARNING: Text insertion failed. Retrying with execCommand...")
                # Fallback: Try deprecated but effective execCommand for rich text
                driver.execute_script("document.execCommand('insertText', false, arguments[0]);", message)
                time.sleep(1)
            
            # Try to click the Send button explicitly
            try:
                send_button = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.XPATH, '//span[@data-icon="send"] | //button[@aria-label="Send"]'))
                )
                send_button.click()
            except:
                # Fallback to Enter key
                print("Send button not found, using Enter key.")
                message_box.send_keys(Keys.ENTER)
            
        print(f"Message sent to {contact_name}.")
        return True
    except Exception as e:
        print(f"Failed to send message to {contact_name}: {e}")
        return False

def check_for_reply(driver, contact_name):
    """Check for the latest message in the chat."""
    print(f"Checking for reply from {contact_name}...")
    if not open_chat(driver, contact_name):
        return None
    
    try:
        # Robust way to get ALL messages (incoming, outgoing, system) using accessibility role
        all_rows = driver.find_elements(By.XPATH, '//div[@role="row"]')
        
        if not all_rows:
            return None
            
        last_row = all_rows[-1]
        
        # Check if this row contains an incoming message bubble
        # Incoming messages usually have a child with class 'message-in'
        if last_row.find_elements(By.XPATH, './/div[contains(@class, "message-in")]'):
            # It is an incoming message! Get text.
            try:
                text_span = last_row.find_element(By.XPATH, './/span[contains(@class, "selectable-text")]')
                return text_span.text
            except:
                return "[Non-text message]"
        else:
            # It's outgoing, system message, or date separator. Ignore.
            return None
            
    except Exception as e:
        # print(f"Error checking reply: {e}") 
        pass
    return None

def heuristic_analysis(reply_text, teacher, subject, time_slot="Scheduled Time"):
    """Simple keyword-based analysis to bypass AI for obvious replies."""
    text = reply_text.lower().strip()
    
    # CONFIRMED keywords
    if any(word in text for word in ["yes", "yeah", "yep", "confirm", "sure", "ok", "okay"]):
        return {"status": "CONFIRMED", "announcement": f"Class Confirmed! ✅\n\nTeacher: {teacher}\nSubject: {subject}\nTime: {time_slot}\n\nSee you there! 🎓"}
        
    # CANCELLED keywords
    if any(word in text for word in ["no", "nope", "cancel", "not taking", "busy"]):
        return {"status": "CANCELLED", "announcement": f"Class Cancelled! ❌\n\nTeacher: {teacher}\nSubject: {subject}\n\nEnjoy your free time! 🎉"}
        
    return None

def analyze_reply_with_gemini(reply_text, teacher_name, subject, instructions=None, bot_question=None):
    """Send the reply to Gemini API for analysis."""
    print("Analyzing reply with Gemini...")
    if not reply_text:
        return None

    genai.configure(api_key=GEMINI_API_KEY)
    # UPDATED: Use gemini-pro-latest
    model = genai.GenerativeModel('gemini-pro-latest') 

    prompt = f"""
    Teacher Name: {teacher_name}
    Subject: {subject}
    Teacher Name: {teacher_name}
    Subject: {subject}
    Teacher's Reply Text: "{reply_text}"
    Teacher's Specific Instructions: "{instructions if instructions else 'None'}"
    Context (Your Question): "{bot_question if bot_question else 'Unknown'}"
    """
    
    try:
        response = model.generate_content(SYSTEM_PROMPT + "\n" + prompt)
        
        # Clean up response to ensure it's valid JSON
        json_text = response.text.strip()
        if json_text.startswith("```json"):
            json_text = json_text[7:]
        if json_text.endswith("```"):
            json_text = json_text[:-3]
            
        result = json.loads(json_text)
        return result
    except Exception as e:
        print(f"Gemini analysis failed: {e}")
        return None

def notify_students(driver, announcement):
    """Send the announcement to the Student Group."""
    target_group = "demo group" 
    print(f"Notifying {target_group}...")
    send_whatsapp_message(driver, target_group, announcement)

def run_daily_cycle(routine_file, demo_mode):
    """The core logic to run one daily coordination cycle."""
    print(f"\n--- Starting Daily Cycle at {datetime.datetime.now()} ---")
    
    # Load Routine (Reload every day to catch updates)
    try:
        routine_data = load_routine(routine_file)
    except Exception as e:
        print(f"Error loading routine: {e}")
        return

    # Initialize Driver
    try:
        driver = init_driver()
    except Exception as e:
        print(f"Failed to initialize driver: {e}")
        return
    
    try:
        wait_for_whatsapp_login(driver)
        
        schedule = routine_data.get("schedule", [])
        pending_replies = [] # List to track teachers we are waiting for

        # --- PHASE 1: SEND MESSAGES ---
        print("\n--- Phase 1: Sending Messages ---")
        for slot in schedule:
            teacher = slot["teacher_name"]
            subject = slot["subject"]
            time_slot = slot["time"]
            
            initial_msg = f"Hello {teacher}, this is the automated class coordinator. Do you have the {subject} class at {time_slot} today?"
            
            if send_whatsapp_message(driver, teacher, initial_msg):
                pending_replies.append({
                    "teacher": teacher,
                    "subject": subject,
                    "time": time_slot, # Added time for announcement
                    "last_msg": initial_msg,
                    "state": "WAITING_FOR_CONFIRMATION",
                    "last_seen_msg": None # Track last seen message to detect new ones
                })
            
            time.sleep(2) # Small delay between sends

        # --- PHASE 2: POLL FOR REPLIES ---
        print("\n--- Phase 2: Waiting for Replies ---")
        
        # Demo: 300 seconds (5 mins) to allow for conversation, Real: 600 seconds (10 minutes)
        timeout = 300 if demo_mode else 600
        start_time = time.time()
        
        while pending_replies and (time.time() - start_time < timeout):
            print(f"\nPolling... ({int(timeout - (time.time() - start_time))}s remaining)")
            
            for item in list(pending_replies): # Iterate copy to modify original
                teacher = item["teacher"]
                subject = item["subject"]
                state = item.get("state", "WAITING_FOR_CONFIRMATION")
                
                # Check for reply
                current_reply = check_for_reply(driver, teacher)
                
                if current_reply and current_reply != item.get("last_seen_msg"):
                    print(f"New reply detected from {teacher}: {current_reply}")
                    item["last_seen_msg"] = current_reply # Update last seen to avoid re-processing

                    if state == "WAITING_FOR_CONFIRMATION":
                        # 1. Try Heuristic Analysis first (Fast & Deterministic)
                        pre_analysis = heuristic_analysis(current_reply, teacher, subject, item.get("time"))
                        
                        # 2. Fallback to AI if heuristic is uncertain
                        if not pre_analysis:
                            pre_analysis = analyze_reply_with_gemini(current_reply, teacher, subject, bot_question=item.get("last_msg"))
                        
                        status = pre_analysis.get("status", "UNCERTAIN") if pre_analysis else "UNCERTAIN"
                        
                        if status == "CANCELLED":
                            print(f"{teacher} cancelled. Notifying students immediately.")
                            announcement = pre_analysis.get("announcement")
                            if announcement:
                                notify_students(driver, announcement)
                            pending_replies.remove(item)
                            
                        elif status == "UNCERTAIN":
                            print(f"Status is UNCERTAIN. Asking for clarification...")
                            clarification_msg = "Could you please clarify if the class is confirmed?"
                            send_whatsapp_message(driver, teacher, clarification_msg)
                            item["last_msg"] = clarification_msg # UPDATE CONTEXT
                            # Stay in WAITING_FOR_CONFIRMATION state
                            
                        else:
                            # CONFIRMED or RESCHEDULED
                            print(f"Status is {status}. Asking for instructions...")
                            follow_up = "Do you want any specific instruction for the class?"
                            if send_whatsapp_message(driver, teacher, follow_up):
                                item["state"] = "WAITING_FOR_INSTRUCTIONS"
                                item["first_reply"] = current_reply
                                item["status"] = status

                    elif state == "WAITING_FOR_INSTRUCTIONS":
                        print(f"Received instructions from {teacher}: {current_reply}")
                        
                        # Send Exit Message
                        exit_msg = "Okay, noting that down. Exiting now. Have a great day!"
                        send_whatsapp_message(driver, teacher, exit_msg)
                        
                        # Final Analysis with instructions
                        # Final Analysis with instructions
                        first_reply = item.get("first_reply", "")
                        # Pass the context of the instruction question
                        final_analysis = analyze_reply_with_gemini(first_reply, teacher, subject, instructions=current_reply, bot_question="Do you want any specific instruction for the class?")
                        
                        announcement = None
                        if final_analysis:
                            print(f"Final Status: {final_analysis.get('status')}")
                            announcement = final_analysis.get("announcement")
                        
                        # Fallback: If AI failed or didn't return announcement, generate one manually
                        if not announcement and item.get("status") == "CONFIRMED":
                            print("WARNING: AI failed to generate announcement. Using fallback.")
                            instr_text = f"\nNote: {current_reply}" if len(current_reply) > 3 and "no" not in current_reply.lower() else ""
                            announcement = f"Class Confirmed! ✅\n\nTeacher: {teacher}\nSubject: {subject}\nTime: {item.get('time', 'Scheduled Time')}{instr_text}\n\nSee you there! 🎓"

                        # Notify Students
                        if announcement:
                            notify_students(driver, announcement)
                        else:
                            print("ERROR: Could not generate announcement.")
                        
                        # Remove from pending
                        pending_replies.remove(item)
                
                time.sleep(2) # Small delay between checking teachers
            
            time.sleep(10) # Wait before next polling cycle

        if pending_replies:
            print("\nTimeout reached. Some teachers did not reply:")
            for item in pending_replies:
                print(f"- {item['teacher']}")

    except KeyboardInterrupt:
        print("Cycle interrupted by user.")
    except Exception as e:
        print(f"An error occurred during the daily cycle: {e}")
    finally:
        print("Closing driver...")
        try:
            driver.quit()
        except:
            pass
    print(f"--- Daily Cycle Finished at {datetime.datetime.now()} ---\n")

def run_scheduler(routine_file, demo_mode, start_time_str="08:00"):
    """Runs the daily cycle continuously at a specific time."""
    print(f"Antigravity Automation Started. Scheduled to run daily at {start_time_str}.")
    print("Press Ctrl+C to stop.")
    
    while True:
        now = datetime.datetime.now()
        current_time = now.strftime("%H:%M")
        
        # Check if it's time to run
        if current_time == start_time_str:
            run_daily_cycle(routine_file, demo_mode)
            
            # Sleep for 61 seconds to ensure we don't run twice in the same minute
            time.sleep(61)
        else:
            # Sleep for a bit before checking again
            # Calculate seconds until next minute to be precise, or just sleep 30s
            time.sleep(30)

def main():
    parser = argparse.ArgumentParser(description="Project Antigravity: Autonomous Class Coordinator")
    parser.add_argument("--routine", default="routine.json", help="Path to routine JSON file")
    parser.add_argument("--demo", action="store_true", help="Run in Demo Mode (reduced wait times)")
    parser.add_argument("--continuous", action="store_true", help="Run in continuous mode (daily schedule)")
    parser.add_argument("--time", default="08:00", help="Time to run in continuous mode (HH:MM, 24hr format)")
    args = parser.parse_args()

    if args.continuous:
        run_scheduler(args.routine, args.demo, args.time)
    else:
        run_daily_cycle(args.routine, args.demo)

if __name__ == "__main__":
    main()
