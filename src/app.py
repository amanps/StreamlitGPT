 # Importing required packages
import streamlit as st
import uuid
import time
import pandas as pd
from openai import OpenAI
from openai import AssistantEventHandler

import json
from sqlalchemy import create_engine
import glob


# Set up the page
st.set_page_config(page_title="Campus Assistant", page_icon=":robot:")


@st.cache_resource()
def set_up_sql_backend():
    engine = create_engine('sqlite://', echo=False)

    # Get a list of all CSV files in the directory
    csv_files = glob.glob('data/*.csv')

    # Create an empty list to store the dataframes
    dfs = []

    # Iterate over each CSV file and read it into a dataframe
    for file in csv_files:
        df = pd.read_csv(file)
        table_name = file.split('/')[-1].split('.')[0]
        df=df.dropna(axis=1,how='all')
        df.to_sql(name=table_name,con=engine)

    return engine


sql_engine = set_up_sql_backend()



def run_sql_query(query,output_type="Table"):
    try:
        result = pd.read_sql(query,con=sql_engine)
        if len(result)>5:
            output_type = "Table"
        if output_type == "Table":
            return result.to_markdown()
        elif output_type == "JSON":
            return result.to_json()
        else:
            return result.to_csv()
    except:
        return "Having trouble checking this. Please check the info you've provided and try again."


function_json = {
    "name": "run_sql_query",
    "description": "When you generater an sql query, run the query through this function and output a table or a json or a csv.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "output_type": {
                "type": "string",
            }
        },
        "required": ["query"],
    },
}


# Initialize OpenAI client
client = OpenAI()

MODEL = "gpt-4-turbo" # Latest model

# Initialize session state variables
if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())

if "run" not in st.session_state:
    st.session_state.run = {"status": None}

if "messages" not in st.session_state:
    st.session_state.messages = []

if "retry_error" not in st.session_state:
    st.session_state.retry_error = 0


run_sql_query("SELECT * FROM 'Student Master' LIMIT 5")


with open("data/instructions.txt","r") as rfile:
    instructions = rfile.read()


if "assistant" not in st.session_state:
    client = OpenAI(api_key="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")
    st.session_state.assistant = client.beta.assistants.create(
        name="Campus Chatbot",
        instructions=instructions,
        tools=[
            {"type": "function", "function": function_json},
            ],
            model=MODEL
        )
    st.session_state.thread = client.beta.threads.create(
        metadata={'session_id': st.session_state.session_id}
    )

# Display chat messages
elif hasattr(st.session_state.run, 'status') and st.session_state.run.status == "completed":
    st.session_state.messages = client.beta.threads.messages.list(
        thread_id=st.session_state.thread.id
    )
    for message in reversed(st.session_state.messages.data):
        if message.role in ["user", "assistant"]:
            with st.chat_message(message.role):
                for content_part in message.content:
                    message_text = content_part.text.value
                    st.markdown(message_text)

# Chat input and message creation with file ID
if prompt := st.chat_input("Hello, this is your campus assistant. How can I help you?"):
    with st.chat_message('user'):
        st.write(prompt)


    message_data = {
        "thread_id": st.session_state.thread.id,
        "role": "user",
        "content": prompt
    }

    st.session_state.messages = client.beta.threads.messages.create(**message_data)

    st.session_state.run = client.beta.threads.runs.create(
        thread_id=st.session_state.thread.id,
        assistant_id=st.session_state.assistant.id,
    )

# Handle run status
if hasattr(st.session_state.run, 'status'):
    if st.session_state.run.status == "running":
        with st.chat_message('assistant'):
            st.write("Thinking ......")
        if st.session_state.retry_error < 3:
            time.sleep(1)
            st.rerun()

    elif st.session_state.run.status == "failed":
        st.session_state.retry_error += 1
        with st.chat_message('assistant'):
            if st.session_state.retry_error < 3:
                st.write("Run failed, retrying ......")
                time.sleep(3)
                st.rerun()
            else:
                st.error("FAILED: The OpenAI API is currently processing too many requests. Please try again later ......")

    
    elif st.session_state.run.status=="requires_action":
        print("inside requires action")
        tool_outputs = []
        for tool in st.session_state.run.required_action.submit_tool_outputs.tool_calls:
            if tool.function.name == "run_sql_query":
                function_args = json.loads(tool.function.arguments)
                function_response = run_sql_query(
                    query=function_args.get("query")
                )
                if len(function_response)>1048576:
                    function_response = "The output is too large to display here. Please run this externally"
                tool_outputs.append({
                    "tool_call_id": tool.id,
                    "output": function_response
                })

            # Submit all tool outputs at once after collecting them in a list
        if tool_outputs:
            try:
                st.session_state.run = client.beta.threads.runs.submit_tool_outputs_and_poll(
                    thread_id=st.session_state.thread.id,
                    run_id=st.session_state.run.id,
                    tool_outputs=tool_outputs
                )
                print("Tool outputs submitted successfully.")
            except Exception as e:
                print("Failed to submit tool outputs:", e)
        else:
            print("No tool outputs to submit.")


        if st.session_state.retry_error < 3:
            time.sleep(3)
            st.rerun()

    
    elif st.session_state.run.status != "completed":

        st.session_state.run = client.beta.threads.runs.retrieve(
            thread_id=st.session_state.thread.id,
            run_id=st.session_state.run.id,
        )

        if st.session_state.retry_error < 3:
            time.sleep(3)
            st.rerun()
