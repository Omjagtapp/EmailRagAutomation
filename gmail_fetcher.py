import os.path
import base64
import email
import sqlite3
import datetime
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Define the SCOPES.
SCOPES = ['https://www.googleapis.com/auth/gmail.modify']

# Define the database file
DB_FILE = "my_emails.db"

def setup_database():
    """
    Creates the database and the 'emails' table if it doesn't exist.
    """
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Create table
    # We make gmail_id UNIQUE to automatically prevent duplicates.
    # We add 'processed_for_rag' to track which emails we've indexed.
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS emails (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        gmail_id TEXT UNIQUE NOT NULL,
        from_sender TEXT,
        subject TEXT,
        body TEXT,
        received_at TIMESTAMP,
        processed_for_rag INTEGER DEFAULT 0
    )
    ''')
    
    conn.commit()
    conn.close()
    print(f"Database '{DB_FILE}' is ready.")

def save_email_to_db(email_data):
    """
    Saves a single email dictionary to the SQLite database.
    Uses 'INSERT OR IGNORE' to skip duplicates based on the UNIQUE gmail_id.
    """
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
        INSERT OR IGNORE INTO emails (
            gmail_id, from_sender, subject, body, received_at
        ) VALUES (?, ?, ?, ?, ?)
        ''', (
            email_data['gmail_id'],
            email_data['from'],
            email_data['subject'],
            email_data['body'],
            email_data['received_at']
        ))
        
        conn.commit()
        
        # cursor.rowcount will be 1 if a new row was inserted,
        # and 0 if the gmail_id already existed (and was ignored).
        if cursor.rowcount > 0:
            print(f"  > Saved new email to DB: {email_data['subject'][:40]}...")
        else:
            print(f"  > Email already in DB: {email_data['subject'][:40]}...")
            
    except sqlite3.Error as e:
        print(f"Database error: {e}")
    finally:
        conn.close()

def get_email_body(mime_msg):
    """
    Parses a MIME message to find the plain text body.
    """
    if not mime_msg.is_multipart():
        if mime_msg.get_content_type() == 'text/plain':
            try:
                return mime_msg.get_payload(decode=True).decode()
            except:
                return ""
        else:
            return ""

    body = ""
    for part in mime_msg.walk():
        if part.get_content_type() == 'text/plain':
            if part.get('Content-Disposition') is None:
                try:
                    body = part.get_payload(decode=True).decode()
                    break
                except:
                    continue
    return body

def main():
    """
    Main function to authenticate, fetch, and save emails to the database.
    """
    # Run the database setup first
    setup_database()
    
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())

    try:
        service = build('gmail', 'v1', credentials=creds)

        # We can now fetch more than 1 day old, since the DB handles duplicates.
        # Let's fetch emails from the last 3 days to be safe.
        result = service.users().messages().list(
            userId='me', 
            q="is:unread newer_than:1d", # Changed from 'is:unread'
            maxResults=50 # Fetch up to 50
        ).execute()

        messages = result.get('messages')
        
        if not messages:
            print("No new emails found matching query.")
            return

        print(f"Found {len(messages)} emails. Processing...")

        for msg in messages:
            msg_id = msg['id']
            try:
                # Fetch the full raw message AND metadata
                msg_full = service.users().messages().get(
                    userId='me', 
                    id=msg_id,
                    format='full' # Use 'full' to get metadata
                ).execute()

                # Get the raw data for parsing
                msg_raw = service.users().messages().get(
                    userId='me', 
                    id=msg_id,
                    format='raw'
                ).execute()

                raw_data = msg_raw['raw']
                msg_str = base64.urlsafe_b64decode(raw_data.encode('ASCII'))
                mime_msg = email.message_from_bytes(msg_str)

                # Extract headers
                from_ = str(email.header.make_header(email.header.decode_header(mime_msg['from'])))
                subject = str(email.header.make_header(email.header.decode_header(mime_msg['subject'])))
                
                # Extract body
                body = get_email_body(mime_msg)

                # Get received date from 'full' format response
                internal_date_ms = int(msg_full['internalDate'])
                received_at = datetime.datetime.fromtimestamp(internal_date_ms / 1000.0)

                # Prepare the data dictionary
                email_data = {
                    'gmail_id': msg_id,
                    'from': from_,
                    'subject': subject,
                    'body': body,
                    'received_at': received_at
                }
                
                # Save to our new database
                save_email_to_db(email_data)

            except Exception as e:
                print(f"Could not parse or save email with ID {msg_id}: {e}")

        print("\nPhase 1 (Ingestion & Storage) complete.")

    except HttpError as error:
        print(f'An error occurred: {error}')

if __name__ == '__main__':
    main()
