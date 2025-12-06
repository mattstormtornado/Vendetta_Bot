import praw, time, json, os, removalmanager, sys
from datetime import datetime

# --- Reddit login ---
reddit = praw.Reddit("vendetta")
subreddit = reddit.subreddit("AskOuijaRedux")
print(f"✅ Logged in as: {reddit.user.me()}")

# --- Rate limiting ---
ACTION_DELAY = 1.1
last_action_time = 0
processed_reports = set()


def safe_action(func, *args, **kwargs):
    global last_action_time
    elapsed = time.time() - last_action_time
    if elapsed < ACTION_DELAY:
        time.sleep(ACTION_DELAY - elapsed)
    try:
        result = func(*args, **kwargs)
        last_action_time = time.time()
        return result
    except Exception as e:
        print(f"⚠️ API action failed: {e}")
        return None


# --- Helper functions ---
def collect_letters(comment):
    """Walk up the comment chain and collect single-letter comments"""
    letters = []
    current = comment.parent()
    while isinstance(current, praw.models.Comment):
        body = current.body.strip()
        if len(body) == 1 and body.isalpha():
            letters.append(body.upper())
        current = current.parent()
    return letters[::-1]


def is_goodbye(text: str) -> bool:
    """Check if text starts with 'goodbye' or 'good bye' (case-insensitive)"""
    lowered = text.lower()
    return lowered.startswith("goodbye") or lowered.startswith("good bye")


# --- Blocked word lists ---
def load_words(filename):
    if not os.path.exists(filename):
        print(f"⚠️ Missing {filename}, using empty list")
        return set()
    with open(filename, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {w.upper() for w in data.get("words", [])}


def handle_report(comment):
    if comment.id in processed_reports:
        return
    try:
        # --- Determine submission and target comment ---
        parent = comment.parent()
        if not isinstance(parent, praw.models.Comment) or not is_goodbye(parent.body):
            # Parent either doesn't exist or is not a Goodbye comment
            invalid_message = (
                f"Hi u/{comment.author}, unfortunately your report isn't valid.\n\n"
                f"Please reply to the actual 'Goodbye' comment you want to report, tagging me."
            )
            safe_action(comment.reply, invalid_message)
            print(f"ℹ️ Invalid report by {comment.author}, replied with guidance.")
            return  # Stop further processing
        if isinstance(parent, praw.models.Comment):
            # Goodbye is a reply to another comment
            target_comment = parent
            submission = target_comment.submission
        else:
            # Goodbye is a direct reply to the submission
            target_comment = None
            submission = parent  # this is the Submission itself
        submission = comment.submission
        title = submission.title
        letters = collect_letters(comment.parent())
        ouija_word = "".join(letters).upper() if letters else "UNKNOWN"

        # Notify moderators via modmail
        report_message = (
            f"🚨 User u/{comment.author} reported a possible Rule 1, 8 or 9 violation.\n\n"
            f"**Post Title:** {title}\n\n"
            f"**Answer:** {ouija_word}\n\n"
            f"[Link to report]({comment.permalink})"
        )
        safe_action(subreddit.message,
                    subject="Report for Rule 1, 8 or 9 ",
                    message=report_message
                    )
        print(f"📬 Sent modmail to moderators about {ouija_word}")
        # --- Remove the Goodbye comment if possible ---
        if target_comment:
            safe_action(target_comment.mod.remove)
            print(f"🚫 Removed reported Goodbye: {target_comment.body}")

            # --- Lock the parent comment if it exists ---
            grandparent = target_comment.parent()
            if isinstance(grandparent, praw.models.Comment):
                safe_action(grandparent.mod.lock)
                print(f"🔒 Locked parent comment: {grandparent.body}")

        # Acknowledge reporter and call Ouija-Bot
        ack_message = (
            f"You have reported this answer chain for a Rule 1, 8 or 9 violation.\n\n"
            f"**Post Title:** {title}\n\n"
            f"**Reported Answer:** {ouija_word}\n\n"
            f"I've notified the human mods to take another look and they'll take the appropriate action\n\n"
            f"Thank you 🫡\n"
        )
        safe_action(comment.reply, ack_message)
        print(f"📨 Acknowledged report from {comment.author}")

    except Exception as e:
        print(f"⚠️ Failed to handle report: {e}")


def log_removal(user, comment_body, comment_link, reason=""):
    log_file = "/home/mattswain/Downloads/Vendetta_Bot/removals.log"  # adjust path if needed
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    log_entry = (
        f"[{timestamp}] User: {user} | "
        f"Reason: {reason} | "
        f"Comment: {comment_body} | "
        f"Link: {comment_link}\n"
    )
    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(log_entry)
        print(f"📝 Logged removal: {log_entry.strip()}")
    except Exception as e:
        print(f"⚠️ Failed to log removal: {e}")

# Load blocked words from JSON files
nsfw_words = load_words("nsfw.json")
politics_words = load_words("politics.json")
tos_words = load_words("tos.json")

try:
    # --- Stream comments ---
    for comment in subreddit.stream.comments(skip_existing=True):
        submission = comment.submission
        text = comment.body.strip()
        print(f"{comment.author}: {text}")
        # Report handler
        if "u/vendetta_bot" in text.lower():
            handle_report(comment)
            continue
        # Scan answers for bad words
        if is_goodbye(text):
            letters = collect_letters(comment)
            if not letters:
                print("🤔 No letters found in chain")
                continue

            ouija_word = "".join(letters)
            print(f"📜 Built word: {ouija_word}")

            action_taken = False
            reason = ""
            message = ""

            # Check NSFW
            if ouija_word.upper() in nsfw_words:
                reason = "Rule 8"
                action_taken = True

            # Check Politics
            elif ouija_word.upper() in politics_words:
                reason = "Rule 9"
                action_taken = True

            # Check TOS Violations
            elif ouija_word.upper() in tos_words:
                reason = "Rule 1"
                action_taken = True

            if action_taken:
                print(f"Answer breaks rules. Reason: {reason}")
                removalmanager.removeContent(comment, reason)
                
                # --- Determine how many letter comments to remove ---
                letters_to_remove = 0
                if len(ouija_word) == 3:
                    letters_to_remove = 1
                elif len(ouija_word) == 4:
                    letters_to_remove = 2
                elif len(ouija_word) >= 5:
                    letters_to_remove = 3

                # Collect all parent letter comments
                parent_comments = []
                current = comment.parent()
                while isinstance(current, praw.models.Comment):
                    body = current.body.strip()
                    if len(body) == 1 and body.isalpha():
                        parent_comments.append(current)
                    current = current.parent()

                # Reverse to get order from first letter to last
                parent_comments = parent_comments[::-1]

                # Remove last N letters
                for bad_letter_comment in parent_comments[-letters_to_remove:]:
                    removalmanager.removeContent(bad_letter_comment, reason)
                    log_removal(
                        user=comment.author,
                        comment_body=comment.body,
                        comment_link=f"https://reddit.com{comment.permalink}",
                        reason=reason 
                    )
                    print(f"🚫 Removed letter comment: {bad_letter_comment.body} ({reason})")
            else:
                safe_action(comment.mod.approve)
                print(f"✅ Allowed answer: {ouija_word} (no action taken)")

except Exception as e:
    tb = sys.exc_info()[2]
    lineno = tb.tb_lineno
    error_message = f"🚨 I have just eaten shit and died! Please help me.\n\nError: {e} Line: {lineno}"
    safe_action(subreddit.message,
                subject="Vendetta_Bot crashed",
                message=error_message
                )
