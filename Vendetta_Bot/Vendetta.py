import praw, time, json, os, removalmanager, sys, random, prawcore, threading, re, traceback
from datetime import datetime

# --- Reddit login ---
reddit = praw.Reddit("vendetta")
subreddit = reddit.subreddit("AskOuijaRedux")
print(f"✅ Logged in as: {reddit.user.me()}")

# --- Rate limiting ---
ACTION_DELAY = 1.1
last_action_time = 0
processed_reports = set()


def watchdog(timeout):
    def kill_if_hung():
        print(f"Stream Crashed, restarting bot.")
        os.execv(sys.executable, ['python3']+sys.argv)
    timer = threading.Timer(timeout, kill_if_hung)
    timer.start()
    return timer


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
    if comment.author.name not in blacklist:
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
    else:
        comment.mod.remove()
        


def log_removal(user, comment_body, comment_link, reason=""):
    log_file = "/home/mattswain/Downloads/Vendetta_Bot/removals.log"  # adjust path if needed
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    try:
        log_entry = (
            f"[{timestamp}] User: {user} | "
            f"Reason: {reason} | "
            f"Comment: {comment_body} | "
            f"Link: {comment_link} | "
            f"Prohibited word: {ouija_word}\n"
        )
    except NameError:
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
        

def normal_comment_checker(text, nsfw, politics, tos, grey, comment, waluigi_words, bot_words, uk_words, beer_words, reserved):
    status = None
    text = text.upper()
    if any(re.search(rf"\b{re.escape(word)}\b", text) for word in tos):
        status = "Rule 1"
    elif any(re.search(rf"\b{re.escape(word)}\b", text) for word in nsfw):
        status = "Rule 8"
    elif any(re.search(rf"\b{re.escape(word)}\b", text) for word in politics):
        status = "Rule 9"
    elif any(re.search(rf"\b{re.escape(word)}\b", text) for word in grey):
        status = "Grey"
    elif any(re.search(rf"\b{re.escape(word)}\b", text) for word in waluigi_words):
        waluigi(comment)
    elif any(re.search(rf"\b{re.escape(word)}\b", text) for word in bot_words):
        if not any(real_bot.upper() in text for real_bot in reserved):
            bot(comment)
        else:
            print("A bot was mentioned, so not commenting.")
    elif any(re.search(rf"\b{re.escape(word)}\b", text) for word in uk_words):
        uk(comment)
    elif any(re.search(rf"\b{re.escape(word)}\b", text) for word in beer_words):
        beer(comment)
    return status


def waluigi(comment):
    print(f"Found a waluigi answer")
    waluigi_base = ["r/morewalouija", "r/nomorewalouija"]
    with open("waluigi.json", "r", encoding="utf-8") as f:
        waluigi_responses = json.load(f)
    waluigi_message = "r/nomorewalouija " + random.choice(waluigi_responses)
    safe_action(comment.reply, waluigi_message)
    

def uk(comment):
    print(f"Found a UK answer")
    with open("british.json", "r", encoding="utf-8") as f:
        uk_responses = json.load(f)
    uk_message = random.choice(uk_responses)
    safe_action(comment.reply, uk_message)
    

def bot(comment):
    print(f"Found a bot answer")
    with open("clanker.json", "r", encoding="utf-8") as f:
        clanker_responses = json.load(f)
    clanker_message = random.choice(clanker_responses)
    safe_action(comment.reply, clanker_message)
    
    
def beer(comment):
    print(f"Found a beer answer")
    with open("beer.json", "r", encoding="utf-8") as f:
        beer_responses = json.load(f)
    beer_message = random.choice(beer_responses)
    safe_action(comment.reply, beer_message)
    
    
def command_blacklist(comment, text):
    print("Blacklist command triggered.")
    new_blacklist_letters = collect_letters(comment.parent())
    new_blacklist_word = "".join(new_blacklist_letters)
    new_blacklist_word = new_blacklist_word.upper()
    parts = text.split()
    valid_lists = ["grey", "tos", "nsfw", "politics"]
    if len(parts) >= 2:
        reason = parts[1]
        if reason.lower() in valid_lists:
            f_name = reason + ".json"
            with open(f_name, "r") as f:
                data = json.load(f)
            if new_blacklist_word not in data["words"]:
                data["words"].append(new_blacklist_word)
                with open(f_name, "w") as f:
                    json.dump(data, f, indent=4)
                print(f"Successfully added {new_blacklist_word} to {reason}")
                blacklist_message = f"{new_blacklist_word} was added to the {reason} list by {comment.author}."
                safe_action(subreddit.message,
                subject=f"The {reason} list was modified.",
                message=blacklist_message
                )
            else:
                print("Word is already in blacklist.")
                
                
def command_unblacklist(comment, text):
    print("Blacklist command triggered.")
    new_unblacklist_letters = collect_letters(comment.parent())
    new_unblacklist_word = "".join(new_blacklist_letters)
    new_unblacklist_word = new_unblacklist_word.upper()
    parts = text.split()
    valid_lists = ["grey", "tos", "nsfw", "politics"]
    if len(parts) >= 2:
        reason = parts[1]
        if reason.lower() in valid_lists:
            f_name = reason + ".json"
            with open(f_name, "r") as f:
                data = json.load(f)
            if new_unblacklist_word in data["words"]:
                data["words"].remove(new_unblacklist_word)
                with open(f_name, "w") as f:
                    json.dump(data, f, indent=4)
                print(f"Successfully removed {new_unblacklist_word} from {reason}")
                unblacklist_message = f"{new_unblacklist_word} was removed from the {reason} list by {comment.author}."
                safe_action(subreddit.message,
                subject=f"The {reason} list was modified.",
                message=unblacklist_message
                )
            else:
                print("Word was not in blacklist.")
    
def command_block(comment, text):
    print("Block command triggered.")
    new_blacklist_letters = collect_letters(comment.parent())
    new_blacklist_word = "".join(new_blacklist_letters)
    new_blacklist_word = new_blacklist_word.upper()
    parts = text.split()
    valid_lists = ["1", "8", "9"]
    if parts[1] in valid_lists:
        rule = "Rule " + parts[1]
        print(f"Attempting to add {new_blacklist_word} to a post blacklist for violating {rule}.")
        post = comment.submission
        post_id = post.id
        post_blacklist = os.path.join("post_blacklists", post_id + ".json")
        if not os.path.exists(post_blacklist):
            print(f"No previous blacklist found, generating a new one.")
            with open(post_blacklist, "w") as f:
                json.dump({"words":[]}, f, indent=4)
            print(f"File successfully made.")
        else:
            print(f"Post blacklist was found. Modifying now.")
        print("Opening blacklist to check if word is already present.")
        with open(post_blacklist, "r") as f:
                data = json.load(f)
        exists = any(["word"] == new_blacklist_word for entry in data["words"])
        if not exists:
            data["words"].append({"word": new_blacklist_word, "reason": rule})
            with open(post_blacklist, "w") as f:
                json.dump(data, f, indent=4)
            print(f"Successfully added {new_blacklist_word} to a post blacklist for violating {rule}.")
        else:
            print("Word was already present")
    else:
        print("Invalid rule received.")
        
    
# Load blocked words from JSON files
nsfw_words = load_words("nsfw.json")
politics_words = load_words("politics.json")
tos_words = load_words("tos.json")
grey_words = load_words("grey.json")
with open("blacklist.json", "r", encoding="utf-8") as f:
    blacklist = json.load(f)
waluigi_words = ["WALUIGI", "WALOUIJA", "R/WALOUIJA", "R/MOREWALOUIJA"]
uk_words = ["UK", "KING", "MATTSTORMTORNADO", "BRITISH", "GB", "GREATBRITAIN", "ENGLAND"]
beer_words = ["BEER", "BOOZE", "HAWKSTONE", "BARLEY", "DRINK", "PUB", "ALCOHOL", "DRUNK", "BAR", "DRINKING"]
bot_words = ["BOT", "CLANKER", "DROID", "ROBOT"]
reserved_words = ["U/VENDETTA_BOT", "U/OUIJA-BOT"]
command_fail_message = "Command failed. Please directly reply to the goodbye comment."
try:
    while True:
        try:
            timer = watchdog(600)
            # --- Stream comments ---
            for comment in subreddit.stream.comments(skip_existing=True):
                if (not comment.author == "Vendetta_Bot") and (not comment.author == "Ouija-Bot"):
                    grey_area = False
                    # Load blocked words from JSON files
                    nsfw_words = load_words("nsfw.json")
                    politics_words = load_words("politics.json")
                    tos_words = load_words("tos.json")
                    grey_words = load_words("grey.json")
                    submission = comment.submission
                    text = comment.body.strip()
                    # Normal comment check
                    if len(text) > 1:
                        print(f"Checking normal comment: {text}")
                        reason = normal_comment_checker(text, nsfw_words, politics_words, tos_words, grey_words, comment, waluigi_words, bot_words, uk_words, beer_words, reserved_words)
                        if reason is not None:
                            if reason == "Grey":
                                report_message = (
                                f"🚨 Human review required for this grey area comment\n\n"
                                f"**Comment:** {text}\n\n"
                                f"[Link to post]({comment.permalink})"
                                )
                                safe_action(subreddit.message,
                                    subject="Grey area word detected",
                                    message=report_message
                                )
                                continue
                            else:
                                print(f"{reason} violation detected.")
                                removalmanager.removeContent(comment, reason)
                                log_removal(
                                    user=comment.author,
                                    comment_body=comment.body,
                                    comment_link=f"https://reddit.com{comment.permalink}",
                                    reason=reason
                                )
                                print(f"Comment moderated successfully.")
                                continue
                        elif reason is None:
                            print(f"Comment is allowed.")
                    # Commands
                    # User report    
                    if "u/vendetta_bot" in text.lower():
                        handle_report(comment)
                        continue
                    try:
                        if comment.author and comment.author in comment.subreddit.moderator():
                            parent = comment.parent()
                            try:
                                parent_text = parent.body.strip()
                            except Exception as e:
                                parent_text = None
                            if text.startswith("!blacklist"):
                                if is_goodbye(parent_text):
                                    command_blacklist(comment, text)
                                else:
                                    safe_action(comment.reply, command_fail_message)
                            elif text.startswith("!unblacklist"):
                                if is_goodbye(parent_text):
                                    command_unblacklist(comment, text)
                                else:
                                    safe_action(comment.reply, command_fail_message)
                            elif text.startswith("!block"):
                                if is_goodbye(parent_text):
                                    command_block(comment, text)
                                else:
                                    safe_action(comment.reply, command_fail_message)
                    except Exception as e:
                        tb = e.__traceback__
                        while tb.tb_next:
                            tb = tb.tb_next
                        function = tb.tb_frame.f_code.co_name
                        tb = sys.exc_info()[2]
                        lineno = tb.tb_lineno
                        safe_action(subreddit.message,
                        subject="Vendetta_Bot command failed unexpectedly.",
                        message=f"{function} failed unexpectedly.\n Error{e} \nLine: {lineno} "
                        )
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
                        
                        # Check grey area and alert mods    
                        elif ouija_word.upper() in grey_words:
                            grey_area = True
                            report_message = (
                                f"🚨 Human review required for this grey area answer\n\n"
                                f"**Post Title:** {submission.title}\n\n"
                                f"**Answer:** {ouija_word}\n\n"
                                f"[Link to post]({comment.permalink})"
                            )
                            safe_action(subreddit.message,
                                subject="Grey area word detected",
                                message=report_message
                            )
                        # Check if post has local blacklist
                        post = comment.submission
                        post_id = post.id
                        post_blacklist = os.path.join("post_blacklists", post_id + ".json")
                        if os.path.exists(post_blacklist):
                            with open(post_blacklist, "r") as f:
                                data = json.load(f)
                            for entry in data["words"]:
                                if entry["word"].upper() == ouija_word.upper():
                                    reason = entry["reason"]
                                    action_taken = True
                                    break
                                    
                        # Check for fun trigger words
                        elif ouija_word.upper() in waluigi_words:
                            waluigi(comment)
                            
                        elif ouija_word.upper() in bot_words:
                            bot(comment)
                            
                        elif ouija_word.upper() in beer_words:
                            beer(comment)
                            
                        elif ouija_word.upper() in uk_words:
                            uk(comment)
                        # Moderate if bad words are found.
                        if action_taken:
                            print(f"Answer breaks rules. Reason: {reason}")
                            removalmanager.removeContent(comment, reason)
                            log_removal(
                                    user=comment.author,
                                    comment_body=comment.body,
                                    comment_link=f"https://reddit.com{comment.permalink}",
                                    reason=reason
                                )
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
                                    user=bad_letter_comment.author,
                                    comment_body=bad_letter_comment.body,
                                    comment_link=f"https://reddit.com{bad_letter_comment.permalink}",
                                    reason=reason
                                )
                                print(f"🚫 Removed letter comment: {bad_letter_comment.body} ({reason})")
                            print(f"Removal completed.")
                        else:
                            if grey_area is False:
                                safe_action(comment.mod.approve)
                                print(f"✅ Allowed answer: {ouija_word} (no action taken)")
                            else:
                                print(f"Grey area answer: {ouija_word}, forwarding for human review.")
                    timer.cancel()
                    timer = watchdog(600)
                else:
                    print("Self comment, no moderation")
        except prawcore.exceptions.ServerError as e:
            print(f"Error encountered on reddit's side: {e}, attempting to restart")
            tb = sys.exc_info()[2]
            lineno = tb.tb_lineno
            with open("error.log", "a") as f:
                f.write(f"[{datetime.utcnow()}] Server side error: {e}\n, Line: {lineno}\n")
            time.sleep(10)
            print(f"Attempting to restart")
            continue

except Exception as e:
    tb = sys.exc_info()[2]
    lineno = tb.tb_lineno
    tb = e.__traceback__
    while tb.tb_next:
        tb = tb.tb_next
    function = tb.tb_frame.f_code.co_name
    error_message = f"🚨 I've had a seizure and have stopped working.\n\nError: {e}\n\n Line: {lineno}\n\n Function: {function}"
    with open("error.log", "a") as f:
        f.write(f"[{datetime.utcnow()}] Fatal Crash: {e}, Line: {lineno}\n")
    safe_action(subreddit.message,
                subject="Vendetta_Bot crashed",
                message=error_message
                )
