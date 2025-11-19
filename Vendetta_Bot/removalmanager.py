import praw, prawcore, time, json, sys
from datetime import datetime

r = praw.Reddit("vendetta")
sub = r.subreddit("AskOuijaRedux")
configfile = open("config.json", "r")
config = json.load(configfile)
last_action_time = 0
ACTION_DELAY = 1.1

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
        tb = sys.exc_info()[2]
        lineno = tb.tb_lineno
        with open("error.log", "a") as f:
            f.write(f"[{datetime.utcnow()}] API action failure: {e}\n, Line: {lineno}\n")
        return None


def getRemovalIDs():
    for id in sub.mod.removal_reasons:
        print(f"TITLE: {id.title} - ID: {id}")


def removeContent(item, ruleName):
    try:
        removalReason = config.get(ruleName, None).get("removalReason", None)
        ruleAction = config.get(ruleName, None).get("modActions", None)
        ruleMessage = sub.mod.removal_reasons[removalReason].message
        item.mod.remove(reason_id=removalReason)
        item.mod.send_removal_message(title="Content Removed", message=str(ruleMessage), type="private")
        try:
            r.comment(item.id).author.notes.create(
                label=str(ruleAction), note=f"{ruleName} Violation.", subreddit=sub
            )
        except (TypeError, AttributeError):
            tb = sys.exc_info()[2]
            lineno = tb.tb_lineno
            with open("error.log", "a") as f:
                f.write(f"[{datetime.utcnow()}] Comment was Deleted: {e}\n, Line: {lineno}\n")
            print("User Deleted Comment")

        warnings = 0
        try:
            for note in sub.mod.notes.redditors(item.author, limit=999):
                if note.type == "NOTE":
                    if note.label in ["SPAM_WATCH", "SPAM_WARNING", "ABUSE_WARNING"]:
                        warnings = warnings + 1

            if warnings > 1:
                user = item.author.name
                link = f"https://reddit.com{item.permalink}"
                body = f"{user} needs to be banned: {link}"
                safe_action(sub.message,
                    subject=f"{user} needs to be banned.",
                    message=body
                    )
                print("User needs to be Banned")
        except Exception as e:
            print(f"Failed to read warnings on user: {e}")
            tb = sys.exc_info()[2]
            lineno = tb.tb_lineno
            with open("error.log", "a") as f:
                f.write(f"[{datetime.utcnow()}] Failed to read mod notes: {e}\n, Line: {lineno}\n")
            user = item.author.name
            link = f"https://reddit.com{item.permalink}"
            body = f"Reddit had a seizure.\n\n"
            body += f"{user} needs to be reviewed by a human incase they need banning: {link}\n\n "
            body += f"I came across this error trying to read the warnings myself: {e}. "
            safe_action(sub.message,
                subject=f"{user} needs a ban review.",
                message=body
                )
            print(f"Notified moderators for human review.")



    except praw.exceptions.RedditAPIException:
        print("User Deleted Comment")


if __name__ == "__main__":
    getRemovalIDs()
