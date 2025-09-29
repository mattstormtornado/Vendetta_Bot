import praw, prawcore, time, json

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
            print("User Delted Comment")

        warnings = 0
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




    except praw.exceptions.RedditAPIException:
        print("User Deleted Comment")


if __name__ == "__main__":
    getRemovalIDs()
