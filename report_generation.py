import chromadb
import google.generativeai as genai
import datetime

# --- Configuration ---

# 1. PASTE YOUR GOOGLE API KEY HERE (from Phase 2)
# Get your key from https://aistudio.google.com/app/apikey
GOOGLE_API_KEY = "YOUR API KEY
"

# 2. Path to the vector database (from Phase 2)
CHROMA_PATH = "email_vector_db"

# 3. Embedding model (must be the same as Phase 2)
EMBEDDING_MODEL = "models/text-embedding-004"

# 4. Generation model (for writing the report)
GENERATION_MODEL = "gemini-2.5-flash"

# 5. How many email chunks to send to the LLM for context
TOP_K_RESULTS = 5


def initialize_services():
    """
    Initializes and validates both the ChromaDB client and the Gemini API.
    """
    print("Initializing services...")
    
    # --- API Key Check ---
    if GOOGLE_API_KEY == "YOUR_API_KEY_HERE":
        print("="*50)
        print("ERROR: Please get an API key from Google AI Studio")
        print("https://aistudio.google.com/app/apikey")
        print("and paste it into the GOOGLE_API_KEY variable.")
        print("="*50)
        return None, None
    
    try:
        genai.configure(api_key=GOOGLE_API_KEY)
        # Test API key
        _ = genai.embed_content(model=EMBEDDING_MODEL, content="test", task_type="retrieval_query")
        print("Google API Key configured successfully.")
    except Exception as e:
        print(f"Error configuring Google API: {e}")
        return None, None

    # --- ChromaDB Check ---
    try:
        client = chromadb.PersistentClient(path=CHROMA_PATH)
        collection = client.get_collection(name="emails")
        print(f"ChromaDB collection 'emails' loaded. Total documents: {collection.count()}")
    except Exception as e:
        print(f"Error connecting to ChromaDB at {CHROMA_PATH}: {e}")
        print("Please ensure Phase 2 has been run at least once.")
        return None, None

    return collection, genai

def query_vector_db(collection, query_text, k=TOP_K_RESULTS):
    """
    Embeds the query and retrieves the top-k most relevant text chunks
    from the vector database.
    """
    print(f"\nQuerying vector DB for: '{query_text[:50]}...'")
    
    # 1. Embed the query
    result = genai.embed_content(
        model=EMBEDDING_MODEL,
        content=query_text,
        task_type="retrieval_query" # Important: specifies this is for search
    )
    query_embedding = result['embedding']
    
    # 2. Query ChromaDB
    # 'n_results' is the number of results to return (our k)
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=k
    )
    
    # Extract the 'documents' (the original text chunks)
    # The 'documents' list is nested, so we access the first (and only) query's results
    retrieved_chunks = results['documents'][0]
    
    print(f"  > Found {len(retrieved_chunks)} relevant chunks.")
    return retrieved_chunks

def generate_section(gemini_model, system_prompt, query, context_chunks):
    """
    Calls the Gemini API with a system prompt, context, and a query
    to generate a single section of the report.
    """
    if not context_chunks:
        return "No relevant information found in today's emails."
    
    print(f"  > Calling LLM to generate report section...")

    # Build the context string
    context_str = "\n\n---\n\n".join(context_chunks)
    
    # Construct the full prompt
    full_prompt = f"""
    Here is the context from relevant emails:
    --- CONTEXT START ---
    {context_str}
    --- CONTEXT END ---

    Based *only* on the context provided above, answer the following query:
    QUERY: {query}
    """
    
    try:
        # Set up the generation model
        model = gemini_model.GenerativeModel(
            model_name=GENERATION_MODEL,
            system_instruction=system_prompt
        )
        
        # Make the API call
        response = model.generate_content(full_prompt)
        
        return response.text.strip()
        
    except Exception as e:
        print(f"  > ERROR generating text: {e}")
        return "Error generating this section."

def main():
    """
    Main function to run the full RAG pipeline and generate the report.
    """
    print("Starting Phase 3: Report Generation...")
    
    collection, gemini = initialize_services()
    if not collection:
        return

    # --- 1. Define Your Custom Queries ---
    
    # Query for Job Applications
    q_jobs = "What is the status of my job applications? List any emails about online assessments, rejections, interviews, or offers."
    # System prompt defines the AI's persona and rules
    sp_jobs = """
    You are a helpful assistant summarizing a student's job application status.
    - Analyze the email context provided.
    - List any updates related to job applications (assessments, rejections, interviews, next steps, offers).
    - If no relevant updates are found, just write: "No updates on job applications found today."
    - Be concise and list items as bullet points.
    """
    
    # Query for Banking
    q_bank = "What are the key updates from my bank? List any important transactions, statements, or alerts."
    sp_bank = """
    You are a financial assistant.
    - Analyze the banking-related emails provided.
    - List any important transactions, low balance warnings, statement availability, or security alerts.
    - Do *not* list common marketing or promotional emails.
    - If nothing important is found, write: "No important banking alerts today."
    - Use bullet points.
    """

    # Query for LinkedIn
    q_linkedin = "Did I receive any new messages or important notifications from LinkedIn? Summarize them."
    sp_linkedin = """
    You are a networking assistant.
    - Analyze the LinkedIn notification emails provided.
    - Summarize any new *direct messages* or *connection requests from people*.
    - Ignore "Someone viewed your profile" or "Jobs you may like" notifications.
    - If no direct messages are found, write: "No new direct messages or important connections on LinkedIn."
    - Use bullet points.
    """
    
    # Query for Rent/Utilities
    q_rent = "Are there any urgent emails about my apartment rent or utilities? Look for due dates, bills, or pending payments."
    sp_rent = """
    You are a personal assistant helping with bills.
    - Analyze the emails for any mention of rent, utilities (electric, gas, internet), or lease agreements.
    - Extract any upcoming due dates, bill amounts, or urgent payment reminders.
    - If no rent/utility bills are found, write: "No new information on rent or utilities."
    - Use bullet points.
    """
    
    # Query for General Action Items
    q_actions = "What are all the clear action items, tasks, or requests for me from other emails? Do not include items from the sections above."
    sp_actions = """
    You are an executive assistant.
    - Analyze the email context provided.
    - Identify any clear, direct tasks, requests, or action items for the user.
    - Do *not* repeat information about jobs, banking, LinkedIn, or rent.
    - If no other actions are found, write: "No other action items found."
    - List them as a numbered list.
    """
    
    queries = [
        ("Job Application Status", q_jobs, sp_jobs),
        ("Banking Updates", q_bank, sp_bank),
        ("LinkedIn Messages", q_linkedin, sp_linkedin),
        ("Rent & Utilities", q_rent, sp_rent),
        ("Other Action Items", q_actions, sp_actions),
    ]
    
    report_sections = []
    
    # --- 2. Generate Each Report Section ---
    for title, query, system_prompt in queries:
        # 2a. Retrieve context chunks from ChromaDB
        context_chunks = query_vector_db(collection, query)
        
        # 2b. Generate the summary for this section
        section_content = generate_section(gemini, system_prompt, query, context_chunks)
        
        report_sections.append(f"## {title}\n\n{section_content}\n")

    # --- 3. Assemble and Save the Final Report ---
    today_date = datetime.date.today().strftime("%Y-%m-%d")
    report_filename = f"daily_report_{today_date}.md"
    
    final_report_content = f"# Daily Email Report: {today_date}\n\n"
    final_report_content += "\n".join(report_sections)
    
    with open(report_filename, "w", encoding="utf-8") as f:
        f.write(final_report_content)
        
    print("\n" + "="*50)
    print("Phase 3 (Generation) complete!")
    print(f"Your new report is saved as: {report_filename}")
    print("="*50)

if __name__ == '__main__':
    main()
