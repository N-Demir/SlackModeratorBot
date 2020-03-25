#https://github.com/N-Demir/SlackModeratorBot.git
import os
import time
import re
import requests # *
import json
from slackclient import SlackClient # *
from collections import OrderedDict
import copy

# These are personalized tokens - you should have configured them yourself
# using the 'export' keyword in your terminal.
SLACK_BOT_TOKEN = os.environ.get('SLACK_BOT_TOKEN')
SLACK_API_TOKEN = os.environ.get('SLACK_API_TOKEN')
PERSPECTIVE_KEY = os.environ.get('PERSPECTIVE_KEY')

if (SLACK_BOT_TOKEN == None or SLACK_API_TOKEN == None): #or PERSPECTIVE_KEY == None):
    print("Error: Unable to find environment keys. Exiting.")
    exit()

# Instantiate Slack clients
# bot_slack_client = slack.WebClient(token=SLACK_BOT_TOKEN)
# api_slack_client = slack.WebClient(token=SLACK_API_TOKEN)
bot_slack_client = SlackClient(SLACK_BOT_TOKEN)
api_slack_client = SlackClient(SLACK_API_TOKEN)
# Reportbot's user ID in Slack: value is assigned after the bot starts up
reportbot_id = None

# Constants
RTM_READ_DELAY = 1 # 1 second delay between reading from RTM
REPORT_COMMAND = "report"
CANCEL_COMMAND = "cancel"
HELP_COMMAND = "help"

# Message categories
HATE = "hate speech"
OFFENSIVE = "offensive content"
RACIAL = "racial slurs or racial attacks"
SEX = "sexually explicit content"
OTHER = "other"

# Possible report states - saved as strings for easier debugging.
STATE_REPORT_START       = "report received"    # 1
STATE_MESSAGE_IDENTIFIED = "message identified" # 2
STATE_CATEGORY_IDENTIFIED = "category identified" # 3
STATE_CHECKED_DANGER = "checked for danger" # 4
STATE_DESCRIPTION_SUBMITTED = "description submitted" # 5
STATE_OTHER_MSGS_SUBMITTED = "other messages submitted" # 6
STATE_REPORT_SUBMITTED = "report submitted" # 7


# Currently managed reports. Keys are users, values are report state info.
# Each report corresponds to a single message.
reports = {}

# List of users with bad content
banning_list = {}


# Thresholds for automatically deleting messages
SEVERE_TOXICITY_DELETE_THRESHOLD = 0.8 # Hate speech
TOXICITY_DELETE_THRESHOLD = 0.8 # Offensive speech
SEXUALLY_EXPLICIT_DELETE_THRESHOLD = 0.9 # Sexually explicit speech
IDENTITY_ATTACK_DELETE_THRESHOLD = 0.8 # Racial slurs

SEVERE_TOXICITY_FLAG_THRESHOLD = 0.5 # Hate speech
TOXICITY_FLAG_THRESHOLD = 0.5 # Offensive speech
SEXUALLY_EXPLICIT_FLAG_THRESHOLD = 0.7 # Sexually explicit speech
IDENTITY_ATTACK_FLAG_THRESHOLD = 0.5 # Racial slurs


# Channel identifiers
GROUP_8_MODERATOR_CHANNEL = "GUS458Y0H"

#############################################################
# Begin: Our helper functions
#############################################################

def shouldModerate(scores):
    scores_above_a_deletion_threshold = []
    if scores["SEVERE_TOXICITY"] >= SEVERE_TOXICITY_DELETE_THRESHOLD:
        scores_above_a_deletion_threshold.append((scores["SEVERE_TOXICITY"], "hate speech"))
    if scores["TOXICITY"] >= TOXICITY_DELETE_THRESHOLD:
        scores_above_a_deletion_threshold.append((scores["TOXICITY"] , "offensive content"))
    if scores["IDENTITY_ATTACK"] >= IDENTITY_ATTACK_DELETE_THRESHOLD:
        scores_above_a_deletion_threshold.append((scores["IDENTITY_ATTACK"] , "racial slurs or racial attacks"))
    if scores["SEXUALLY_EXPLICIT"] >= SEXUALLY_EXPLICIT_DELETE_THRESHOLD:
        scores_above_a_deletion_threshold.append((scores["SEXUALLY_EXPLICIT"] , "sexually explicit content"))

    if len(scores_above_a_deletion_threshold) != 0:
        return "delete", max(scores_above_a_deletion_threshold,key=lambda x:x[0])[1]


    scores_above_a_flagging_threshold = []
    if scores["SEVERE_TOXICITY"] >= SEVERE_TOXICITY_FLAG_THRESHOLD:
        scores_above_a_flagging_threshold.append((scores["SEVERE_TOXICITY"], "hate speech"))
    if scores["TOXICITY"] >= TOXICITY_FLAG_THRESHOLD:
        scores_above_a_flagging_threshold.append((scores["TOXICITY"] , "offensive content"))
    if scores["IDENTITY_ATTACK"] >= IDENTITY_ATTACK_FLAG_THRESHOLD:
        scores_above_a_flagging_threshold.append((scores["IDENTITY_ATTACK"] , "racial slurs or racial attacks"))
    if scores["SEXUALLY_EXPLICIT"] >= SEXUALLY_EXPLICIT_FLAG_THRESHOLD:
        scores_above_a_flagging_threshold.append((scores["SEXUALLY_EXPLICIT"] , "sexually explicit content"))

    if len(scores_above_a_flagging_threshold) != 0:
        return "flagging", max(scores_above_a_flagging_threshold,key=lambda x:x[0])[1]

    return "nothing", ""

def deleteMessage(event):
    api_slack_client.api_call(
        "chat.delete",
        channel=event["channel"],
        ts=event["ts"],
    )

def getUserNameFromEvent(event):
    return api_slack_client.api_call(
        "users.profile.get",
        user=event["user"],
    )["profile"]["display_name"]


def handle_moderator(event):
    moderater_message = banning_list.get("moderator_message", None)
    if moderater_message == None:
        return []

    reply = []

    if event["text"] == "ban":
        banning_list[moderater_message["user"]] = 2.0
        print("Banned the messager.")
    elif event["text"] == "delete":
        deleteMessage(moderater_message)
        print("Deleted the message.")
    elif event["text"] == "report":
        reply = handle_report(event)
        event["channel"] = get_dm_channel(event, event["user"])
    return reply


def get_dm_channel(event, user):
    response = bot_slack_client.api_call(
        "conversations.list",
        types="im"
    )

    for channel in response["channels"]:
        if channel["user"] == user:
            return channel["id"]


#############################################################
# End: Our helper functions
#############################################################


def handle_slack_events(slack_events):
    '''
    Given the list of all slack events that happened in the past RTM_READ_DELAY,
    this function decides how to handle each of them.

    DMs - potential report
    Public IM - post Perspective score in the same channel
    '''
    for event in slack_events:
        # Ignore other events like typing or reactions
        if event["type"] == "message" and not "subtype" in event:
            if (is_dm(event["channel"])):
                # May or may not be part of a report, but we need to check
                replies = handle_report(event)
            elif event["channel"] == GROUP_8_MODERATOR_CHANNEL:
                replies = handle_moderator(event)
            else:
                # Send all public messages to perspective for review
                scores = eval_text(event["text"], PERSPECTIVE_KEY)

                #############################################################
                # STUDENT TODO: currently this always prints out the scores.#
                # You probably want to change this behavior!                #
                #############################################################
                moderation, reasoning = shouldModerate(scores)
                replies = []

                if moderation == "delete" or banning_list.get(event["user"], 0) >= 2.0:
                    deleteMessage(event)

                    if banning_list.get(event["user"], 0) >= 2.0:
                        break

                    replies = ["Deleted an offending message for {}.".format(reasoning)]

                    # Send a message to moderator channel saying message was deleted
                    bot_slack_client.api_call(
                        "chat.postMessage",
                        channel=GROUP_8_MODERATOR_CHANNEL,
                        text= "I deleted the following message: \"{}\". By user: \"{}\". You can ".format(event["text"], getUserNameFromEvent(event)) \
                            + "respond with a few moderator options: \"ban\" = Ban User. \"report\" = Start reporting flow."
                    )

                    banning_list[event["user"]] = banning_list.get(event["user"], 0) + 1
                    banning_list["moderator_message"] = event

                elif moderation == "flagging":
                    getUserNameFromEvent(event)
                    # Send a message to moderator channel saying message was flagged
                    bot_slack_client.api_call(
                        "chat.postMessage",
                        channel=GROUP_8_MODERATOR_CHANNEL,
                        text= "I flagged the following message: \"{}\". By user: \"{}\". You can ".format(event["text"], getUserNameFromEvent(event)) \
                            + "respond with a few moderator options: \"delete\" = Delete the message. \"ban\" = Ban User. \"report\" = Start reporting flow."
                    )
                    bot_slack_client.api_call(
                        "reactions.add",
                        channel=event["channel"],
                        name="triangular_flag_on_post",
                        timestamp=event["ts"]
                    )

                    banning_list[event["user"]] = banning_list.get(event["user"], 0) + 0.75
                    banning_list["moderator_message"] = event

            # Send bot's response(s) to the same channel the event came from.
            for reply in replies:
                bot_slack_client.api_call(
                    "chat.postMessage",
                    channel=event["channel"],
                    text=reply
                )


def handle_report(message):
    '''
    Given a DM sent to the bot, decide how to respond based on where the user
    currently is in the reporting flow and progress them to the next state
    of the reporting flow.
    '''
    user = message["user"]

    if HELP_COMMAND in message["text"]:
        return response_help()

    # If the user isn't in the middle of a report, check if this message has the keyword "report."
    if user not in reports:
        if not REPORT_COMMAND in message["text"]:
            return response_help()
            
        # Add report with initial state.
        reports[user] = {"state" : STATE_REPORT_START}
        return response_report_instructions()

    # Otherwise, we already have an ongoing conversation with them.
    else:
        if CANCEL_COMMAND in message["text"]:
            reports.pop(user) # Remove this report from the map of active reports.
            return ["Report cancelled."]

        report = reports[user]

        ####################################################################
        # STUDENT TODO:                                                    #
        # Here's where you should expand on the reporting flow and build   #
        # in a progression. You're welcome to add branching options and    #
        # the like. Get creative!                                          #
        ####################################################################
        if report["state"] == STATE_REPORT_START:
            # Fill in the report with reported message info.
            result = populate_report(report, message)

            # If we received anything other than None, it was an error.
            if result:
                reports.pop(user)
                return result

            # Progress to the next state.
            report["state"] = STATE_MESSAGE_IDENTIFIED
            return response_identify_message(user)

        elif report["state"] == STATE_MESSAGE_IDENTIFIED:
            return categorize_message(user, message["text"].lower())

        elif report["state"] == STATE_CATEGORY_IDENTIFIED:
            return check_danger(user, message["text"].lower())

        elif report["state"] == STATE_CHECKED_DANGER:
            report["description"] = []
            return gather_description(user, message["text"])

        elif report["state"] == STATE_DESCRIPTION_SUBMITTED:
            report["other messages"] = []
            return get_other_msgs(user, message["text"])

        elif report["state"] == STATE_OTHER_MSGS_SUBMITTED:
            return finish_report(user, message["text"].lower())

        elif report["state"] == STATE_REPORT_SUBMITTED:
            return submitted(user, message["text"].lower())


def response_help():
    reply =  "Use the `report` command to begin the reporting process.\n"
    reply += "Use the `cancel` command to cancel the report process.\n"
    return [reply]


def response_report_instructions():
    reply =  "Thank you for starting the reporting process. "
    reply += "Say `help` at any time for more information," \
             + " or say `cancel` at any time to cancel your report.\n\n"
    reply += "Please copy paste the link to the message you want to report.\n"
    reply += "You can obtain this link by clicking on the three dots in the" \
          +  " corner of the message and clicking `Copy link`."
    return [reply]


def response_identify_message(user):
    replies = []
    report = reports[user]

    reply =  "I found the message "
    reply += format_code(report["text"])
    reply += " from user " + report["author_full"]
    reply += " (" + report["author_name"] + ").\n\n"
    replies.append(reply)

    reply =  "Now, I'd like to ask you a few questions to help" \
             + " our moderators respond to your report.\n\n"
    reply += "First, please tell us what category of message you're reporting." \
             + " If the message you're reporting falls into multiple categories," \
             + " please choose the category that best descripes it." \
             + " You'll have a chance afterward to provide additional details.\n\n"
    reply += "1 - `hate speech`\n"
    reply += "2 - `offensive content`\n"
    reply += "3 - `racial slurs`\n"
    reply += "4 - `sexually explicit content`\n"
    reply += "5 - `other`"
    replies.append(reply)

    return replies
    

def categorize_message(user, text):
    replies = []
    report = reports[user]
    if "hate speech" in text or "1" in text:
        report["category"] = HATE
    elif "offensive" in text or "2" in text:
        report["category"] = OFFENSIVE
    elif "racial" in text or "race" in text or "slur" in text or "3" in text:
        report["category"] = RACIAL
    elif "sex" in text or "4" in text:
        report["category"] = SEX
    else:
        report["category"] = OTHER

    reply = "I see; you're reporting this message because it contains " \
            + report["category"] \
            + ".\n\n"
    replies.append(reply)
    report["state"] = STATE_CATEGORY_IDENTIFIED
    
    reply = "Before we go any further, I need to make sure nobody's in danger.\n\n"
    reply += "If the person whose message you're reporting is encouraging you" \
             + " to harm yourself, or if you're concerned that you might harm yourself," \
             + " please enter `self` so that we can appropriately categorize your report.\n\n"
    reply += "Or if you believe that the person whose message you're reporting is " \
             + "likely to harm someone else, please enter `someone else`.\n\n"
    reply += "Otherwise, if you don't believe that anyone's physical safety is in" \
             + " imminent danger, please enter `none`."
    replies.append(reply)

    return replies

def check_danger(user, text):
    replies = []
    report = reports[user]

    if "self" in text:
        reply = "Please, don't hurt yourself. The National Suicide Prevention Hotline" \
                + " has live counselors available to talk 24/7. Their number is 1-800-273-8255.\n\n"
        reply += "I'll wait as long as you need; we can finish the report together when you're safe."
        replies.append(reply)
    elif "someone" in text:
        reply = "If the person whose message you're reporting is likely to harm someone else," \
                + " please call 911 and report them to law enforcement before going any further.\n\n"
        reply += "I'll wait as long as you need; we can finish the report together when everyone's safe."
        replies.append(reply)
    else:
        reply = "Okay. I'm glad nobody's in danger.\n\n"
        replies.append(reply)

    report["state"] = STATE_CHECKED_DANGER
    reply = "Whenever you're ready, could you please describe, in your own words, what kind" \
            + " of content you're reporting, as well as why you're reporting it?\n\n"
    replies.append(reply)
    return replies
    
def gather_description(user, text):
    report = reports[user]
    if text.lower() != "done":
        report["description"].append(text)
        reply = "I see. Is that everything? If so, please enter `done`, and" \
                + " we'll proceed to the next step of the report.\n"
        reply += "But if you've got more to add, please share as much detail" \
                 + " as you like, and I'll include it all in the report."
        return [reply]
    else:
        report["state"] = STATE_DESCRIPTION_SUBMITTED
        reply = "Got it; thank you!\n\n"
        reply += "Next question: Are there any other messages from this user" \
                 + " that you want to report, or that you think might provide" \
                 + " helpful context for our moderators?\n\n"
        reply += "If so, please copy and paste the link to the message(s) you" \
                 + " want to add to your report, one at a time. If not, enter `none`."
        return [reply]

def get_other_msgs(user, text):
    report = reports[user]
    replies = []
    if text == "none":
        reply = "Okay then!"
        replies.append(reply)
    elif "slack.com" in text:
        report["other messages"].append(text)
        reply = "Got it!\n\n"
        reply += "If you want to add additional messages to your report, please" \
                 + " copy and paste the link to the message(s), one at a time." \
                 + " Or if you're done adding messages, please enter `none`."
        replies.append(reply)
        return replies
    else:
        reply = "I'm sorry; that reply wasn't quite what I was expecting.\n\n"
        reply += "If you want to add additional messages to your report, please" \
                 + " copy and paste the link to the message(s), one at a time." \
                 + " If you don't want to add additional messages, but you want to" \
                 + " continue submitting your report, please enter `none`. Or if you" \
                 + " want to cancel your report, you can enter `cancel`."
        replies.append(reply)
        return replies

    report["state"] = STATE_OTHER_MSGS_SUBMITTED
    reply = "We're almost done. Last question: do you want to block the person" \
            + " who sent you this message?\n\n"
    reply += "If so, they won't be able to DM you anymore, and you won't see their" \
             + " messages in any group chats.\n\n"
    reply += "If you want to block them, please enter `block`. Otherwise, please enter" \
             + " `continue`."
    replies.append(reply)
    return replies

def finish_report(user, text):
    report = reports[user]
    replies = []
    if text == "block":
        report["block"] = True
        reply = "Got it--you won't see any more messages from them."
        replies.append(reply)
    elif text == "continue":
        report["block"] = False
        reply = "Okay! We'll leave them unblocked for now."
        replies.append(reply)
    else:
        reply = "I'm sorry; that reply wasn't quite what I was expecting.\n\n"
        reply += "If you want to block the person whose message you're reporting," \
                 + " please enter `block`. If not, enter `continue`. Or if you want" \
                 + " to cancel your report, you can enter `cancel`."
        return [reply]

    report["state"] = STATE_REPORT_SUBMITTED
    reply = "Well, that's everything I needed for the report.\n\n"
    reply += "I'm going to package this up and present it to a human moderator. They'll" \
             + " takes things from here.\n\n"
    reply += "Thank you for taking the time to help make Slack a safer and more inclusive" \
             + " space. If you encounter any other harmful content, we hope you'll feel" \
             + " comfortable bringing it to us.\n\n"
    reply += "Please be safe!"
    replies.append(reply)
    return replies

def submitted(user, text):
    report = reports[user]
    replies = []
    if "report" in text:
        report["state"] = STATE_REPORT_START
        return response_report_instructions()
    reply = "I've brought your report to a human moderator. They'll be responsible for" \
            + " taking things from here.\n\n"
    reply += "In the meantime, if you need to submit another report, please enter `report`.\n\n"
    reply += "Otherwise, please be safe!"
    replies.append(reply)
    return replies
    
        



###############################################################################
# UTILITY FUNCTIONS - you probably don't need to read/edit these, but you can #
# if you're curious!                                                          #
###############################################################################


def populate_report(report, message):
    '''
    Given a URL of some message, parse/lookup:
    - ts (timestamp)
    - channel
    - author_id (unique user id)
    - author_name
    - author_full ("real name")
    - text
    and save all of this info in the report.
    '''
    report["ts"],     \
    report["channel"] \
    = parse_message_from_link(message["text"])

    if not report["ts"]:
        return ["I'm sorry, that link was invalid. Report cancelled."]

    # Specifically have to use api slack client
    found = api_slack_client.api_call(
        "conversations.history",
        channel=report["channel"],
        latest=report["ts"],
        limit=1,
        inclusive=True
    )

    # If the key messages isn't in found, odds are we are missing some permissions.
    if "messages" not in found:
        print(json.dumps(found, indent=2))
        return ["I'm sorry, I don't have the right permissions too look up that message."]

    if len(found["messages"]) < 1:
        return ["I'm sorry, I couldn't find that message."]

    reported_msg = found["messages"][0]
    if "subtype" in reported_msg:
        return ["I'm sorry, you cannot report bot messages at this time."]
    report["author_id"] = reported_msg["user"]
    report["text"] = reported_msg["text"]

    author_info = bot_slack_client.api_call(
        "users.info",
        user=report["author_id"]
    )
    report["author_name"] = author_info["user"]["name"]
    report["author_full"] = author_info["user"]["real_name"]


def is_dm(channel):
    '''
    Returns whether or not this channel is a private message between
    the bot and a user.
    '''
    response = bot_slack_client.api_call(
        "conversations.info",
        channel=channel,
        include_num_members="true"
    )
    channel_info = response["channel"]

    # If this is an IM with only two people, necessarily it is someone DMing us.
    if channel_info["is_im"] and channel_info["num_members"] == 2:
        return True
    return False


def parse_message_from_link(link):
    '''
    Parse and return the timestamp and channel name from a message link.
    '''
    parts = link.strip('>').strip('<').split('/') # break link into meaningful chunks
    # invalid link
    if len(parts) < 2:
        return None, None
    ts = parts[-1][1:] # remove the leading p
    ts = ts[:10] + "." + ts[10:] # insert the . in the correct spot
    channel = parts[-2]
    return ts, channel


def eval_text(message, key):
    '''
    Given a message and a perspective key, forwards the message to Perspective
    and returns a dictionary of scores.
    '''
    PERSPECTIVE_URL = 'https://commentanalyzer.googleapis.com/v1alpha1/comments:analyze'

    url = PERSPECTIVE_URL + '?key=' + key
    data_dict = {
        'comment': {'text': message},
        'languages': ['en'],
        'requestedAttributes': {
                                'SEVERE_TOXICITY': {}, 'PROFANITY': {},
                                'IDENTITY_ATTACK': {}, 'THREAT': {},
                                'TOXICITY': {}, 'FLIRTATION': {},
                                'SEXUALLY_EXPLICIT': {}, 'INSULT': {}
                               },
        'doNotStore': True
    }
    response = requests.post(url, data=json.dumps(data_dict))
    response_dict = response.json()

    scores = OrderedDict()
    for attr in response_dict["attributeScores"]:
        scores[attr] = response_dict["attributeScores"][attr]["summaryScore"]["value"]

    return scores


def format_code(text):
    '''
    Code format messages for Slack.
    '''
    return '```' + text + '```'

def main():
    '''
    Main loop; connect to slack workspace and handle events as they come in.
    '''
    if bot_slack_client.rtm_connect(with_team_state=False):
        print("Report Bot connected and running! Press Ctrl-C to quit.")
        # Read bot's user ID by calling Web API method `auth.test`
        reportbot_id = bot_slack_client.api_call("auth.test")["user"]
        while True:
            handle_slack_events(bot_slack_client.rtm_read())
            time.sleep(RTM_READ_DELAY)
    else:
        print("Connection failed. Exception traceback printed above.")


# Main loop
if __name__ == "__main__":
    main()
