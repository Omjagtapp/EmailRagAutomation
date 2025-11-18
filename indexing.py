import sqlite3
import chromadb
import google.generativeai as genai
import time
import os

# --- Configuration ---

# 1. PASTE YOUR GOOGLE API KEY HERE
# Get your key from https://aistudio.google.com/app/apikey
GOOGLE_API_KEY = "AIzaSyC5FwoT23hPGxai1RDoBydGcVLVl4bXjVM"

# 2. Database file from Phase 1
DB_FILE = "my_emails.db"

# 3. Path to store the new vector database
CHROMA_PATH = "email_vector_db"

# 4. The model to use for embedding
EMBEDDING_MODEL = "models/text-embedding-004"


def get_unprocessed_emails():
    """
    Connects to the SQLite DB and fetches all emails that have not
    been processed for RAG (processed_for_rag = 0).
    """
    print(f"Connecting to {DB_FILE} to fetch new emails...")
    conn = sqlite3.connect(DB_FILE)
    # Return rows as dictionaries for easy column access
    conn.row_factory = sqlite3.Row 
    cursor = conn.cursor()
    
    cursor.execute("SELECT id, subject, body FROM emails WHERE processed_for_rag = 0")
    emails = cursor.fetchall()
    
    conn.close()
    print(f"Found {len(emails)} new emails to index.")
    return emails

def chunk_email_body(email_row):
    """
    Splits an email body into smaller, meaningful chunks (paragraphs).
    Prepends the subject to each chunk for better context.
    """
    MIN_CHUNK_LENGTH = 30  # Don't index tiny chunks like "Hi,"
    chunks = []
    
    email_id = email_row['id']
    subject = email_row['subject']
    body = email_row['body']
    
    # Split by double newline (paragraph)
    paragraphs = body.split('\n\n')
    
    chunk_index = 0
    for para in paragraphs:
        cleaned_para = para.strip()
        
        # Only process chunks that are reasonably long
        if len(cleaned_para) >= MIN_CHUNK_LENGTH:
            
            # Prepend context (subject) to the chunk
            chunk_text = f"Email Subject: {subject}\n\n{cleaned_para}"
            
            # Create a unique ID for this chunk
            chunk_id = f"email_{email_id}_chunk_{chunk_index}"
            
            chunks.append({
                'id': chunk_id,
                'text': chunk_text,
                'metadata': {'email_id': email_id, 'subject': subject}
            })
            chunk_index += 1
            
    return chunks

def mark_emails_as_processed(email_ids):
    """
    Updates the SQLite DB to mark a list of email IDs as processed.
    """
    if not email_ids:
        return
        
    print(f"Marking {len(email_ids)} emails as processed in {DB_FILE}...")
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Create placeholders for the IN clause
    placeholders = ','.join('?' for _ in email_ids)
    query = f"UPDATE emails SET processed_for_rag = 1 WHERE id IN ({placeholders})"
    
    cursor.execute(query, email_ids)
    conn.commit()
    conn.close()

def main():
    """
    Main function to run the indexing pipeline.
    """
    print("Starting Phase 2: Indexing...")

    # --- 1. API Key Check ---
    if GOOGLE_API_KEY == "YOUR_API_KEY_HERE":
        print("="*50)
        print("ERROR: Please get an API key from Google AI Studio")
        print("https://aistudio.google.com/app/apikey")
        print("and paste it into the GOOGLE_API_KEY variable.")
        print("="*50)
        return
    
    try:
        genai.configure(api_key=GOOGLE_API_KEY)
        # Make a test call to validate the key
        _ = genai.embed_content(model=EMBEDDING_MODEL, content="test", task_type="retrieval_document")
        print("Google API Key configured successfully.")
    except Exception as e:
        print(f"Error configuring Google API: {e}")
        print("Please ensure your API key is correct and has permissions.")
        return

    # --- 2. Initialize Vector DB ---
    print(f"Initializing ChromaDB at '{CHROMA_PATH}'...")
    # Create a persistent client that saves to disk
    client = chromadb.PersistentClient(path=CHROMA_PATH)
    
    # Get or create the "emails" collection
    collection = client.get_or_create_collection(
        name="emails",
        metadata={"hnsw:space": "cosine"} # Use cosine distance for semantic search
    )
    
    # --- 3. Fetch New Emails ---
    emails_to_process = get_unprocessed_emails()
    if not emails_to_process:
        print("No new emails to index. Exiting.")
        return

    successful_ids = []

    # --- 4. Process Each Email ---
    for email_row in emails_to_process:
        print(f"\nProcessing email ID: {email_row['id']} (Subject: {email_row['subject'][:40]}...)")
        
        try:
            # --- Step 4a: Chunking ---
            chunks = chunk_email_body(email_row)
            
            if not chunks:
                print("  > No valid chunks found. Marking as processed.")
                successful_ids.append(email_row['id'])
                continue

            print(f"  > Generated {len(chunks)} chunks.")
            
            texts_to_embed = [chunk['text'] for chunk in chunks]
            chunk_ids = [chunk['id'] for chunk in chunks]
            metadatas = [chunk['metadata'] for chunk in chunks]
            
            # --- Step 4b: Embedding ---
            # Gemini API is efficient at batching
            result = genai.embed_content(
                model=EMBEDDING_MODEL,
                content=texts_to_embed,
                task_type="retrieval_document" # Important: specifies this is for DB storage
            )
            embeddings = result['embedding']
            print(f"  > Successfully embedded {len(embeddings)} chunks.")
            
            # --- Step 4c: Storing ---
            collection.add(
                ids=chunk_ids,
                embeddings=embeddings,
                documents=texts_to_embed,
                metadatas=metadatas
            )
            print(f"  > Added chunks to ChromaDB.")
            
            # If all steps succeed, add this email's ID to be marked as processed
            successful_ids.append(email_row['id'])
            
            # Rate limiting to be kind to the API
            print("  > Waiting 1 second...")
            time.sleep(1) # 1 second delay per email (which is one API call)

        except Exception as e:
            print(f"  > ERROR processing email ID {email_row['id']}: {e}")
            print("  > This email will be retried on the next run.")
    
    # --- 5. Update SQLite DB ---
    if successful_ids:
        mark_emails_as_processed(successful_ids)
    
    print("\n" + "="*50)
    print("Phase 2 (Indexing) complete.")
    print(f"Total emails processed this run: {len(successful_ids)}")
    print(f"Your 'smart library' is now in the '{CHROMA_PATH}' folder.")
    print(f"Total documents in vector DB: {collection.count()}")
    print("="*50)

if __name__ == '__main__':
    main()
