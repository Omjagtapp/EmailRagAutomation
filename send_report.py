import os.path
import base64
import datetime
from email.mime.text import MIMEText
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# This MUST match the scope in gmail_fetcher_v2.py
SCOPES = ['https://www.googleapis.com/auth/gmail.modify']

def create_message(sender, to, subject, message_text):
    """Create a message for an email.

    Args:
      sender: Email address of the sender.
      to: Email address of the receiver.
      subject: The subject of the email message.
      message_text: The plain text content of the email message.

    Returns:
      A dictionary formatted as a JSON string for the Gmail API.
    """
    message = MIMEText(message_text, 'plain')
    message['to'] = to
    message['from'] = sender
    message['subject'] = subject
    
    # Encode the message in base64url
    raw_message = base64.urlsafe_b64encode(message.as_bytes())
    return {'raw': raw_message.decode()}

def send_message(service, user_id, message):
    """Send an email message.

    Args:
      service: Authorized Gmail API service instance.
      user_id: User's email address. The special value "me"
      can be used to indicate the authenticated user.
      message: Message to be sent.

    Returns:
      Sent Message.
    """
    try:
        message = (service.users().messages().send(userId=user_id, body=message)
                   .execute())
        print(f'Message Id: {message["id"]} sent.')
        return message
    except HttpError as error:
        print(f'An error occurred: {error}')

def main():
    """
    Loads credentials, finds today's report, and emails it.
    """
    print("Starting Phase 4: Sending Report...")
    creds = None
    # The file token.json stores the user's access and refresh tokens.
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("Refreshing expired credentials...")
            creds.refresh(Request())
        else:
            # This should not happen in an automated setup, 
            # as token.json should be valid from the prerequisite step.
            print("Error: No valid token.json found.")
            print("Please run the prerequisite step (modify and run gmail_fetcher_v2.py).")
            return
        # Save the credentials for the next run
        with open('token.json', 'w') as token:
            token.write(creds.to_json())

    try:
        service = build('gmail', 'v1', credentials=creds)

        # --- 1. Find and Read the Report File ---
        today_date = datetime.date.today().strftime("%Y-%m-%d")
        report_filename = f"daily_report_{today_date}.md"
        
        if not os.path.exists(report_filename):
            print(f"Error: Report file {report_filename} not found.")
            return

        with open(report_filename, "r", encoding="utf-8") as f:
            report_content = f.read()

        # --- 2. Get User's Own Email Address ---
        profile = service.users().getProfile(userId='me').execute()
        user_email = profile['emailAddress']
        
        if not user_email:
            print("Error: Could not retrieve your email address.")
            return

        print(f"Report file found. Preparing to send to {user_email}...")

        # --- 3. Create and Send the Email ---
        subject = f"Your Daily Email Report - {today_date}"
        message = create_message(user_email, user_email, subject, report_content)
        
        send_message(service, 'me', message)
        
        print("Phase 4 (Email Report) complete.")

    except HttpError as error:
        print(f'An error occurred: {error}')
    except Exception as e:
        print(f'An unexpected error occurred: {e}')

if __name__ == '__main__':
    main()
