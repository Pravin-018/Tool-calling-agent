"""Streamlit chat interface for the Shop Stock Helper Agent."""

import streamlit as st
from google.genai.errors import APIError
from langchain_core.exceptions import LangChainException

from agent_core import run_agent


st.set_page_config(page_title="Shop Stock Helper Agent", page_icon="📦", layout="centered")
st.title("Shop Stock Helper Agent")
st.write(
    "Ask about products and stock levels, calculate what needs restocking, "
    "or prepare a reorder note for your review."
)

with st.sidebar:
    st.header("Gemini setup")
    api_key = st.text_input(
        "Your Gemini API key",
        type="password",
        help="Used only for requests in this app session; never displayed in chat.",
    )
    st.caption("Get a key from Google AI Studio. Do not share or commit your key.")
    if st.button("Clear chat", use_container_width=True):
        st.session_state["chat_history"] = []

if "chat_history" not in st.session_state:
    st.session_state["chat_history"] = []

for index, message in enumerate(st.session_state["chat_history"]):
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if message["role"] == "assistant":
            with st.expander("Agent Steps", expanded=False):
                trace = message.get("trace", [])
                if not trace:
                    st.caption("No tools were needed for this answer.")
                for step_number, step in enumerate(trace, start=1):
                    st.markdown(f"**Step {step_number}: `{step['tool']}`**")
                    st.caption(f"Input: {step['input']}")
                    st.code(step["result"], language="text")
            if message.get("step_limit_reached"):
                st.warning("The agent stopped because it reached the step limit.")

prompt = st.chat_input("Ask about your shop stock...")
if prompt is not None:
    if not prompt.strip():
        st.warning("Please enter a question before sending.")
    elif not api_key.strip():
        st.error("Enter your Gemini API key in the sidebar before sending a question.")
    else:
        st.session_state["chat_history"].append({"role": "user", "content": prompt.strip()})
        with st.chat_message("user"):
            st.markdown(prompt.strip())

        with st.chat_message("assistant"):
            with st.spinner("Checking your stock..."):
                try:
                    result = run_agent(
                        prompt,
                        api_key,
                        st.session_state["chat_history"][:-1],
                    )
                except (APIError, LangChainException, OSError, TimeoutError, ValueError) as error:
                    # Do not expose provider exception text, which could contain request details.
                    error_hint = str(error).casefold()
                    if any(term in error_hint for term in ("invalid api key", "api_key_invalid", "unauthenticated", "401")):
                        friendly_error = "The Gemini API key appears to be invalid. Check it and try again."
                    elif any(term in error_hint for term in ("quota", "resource_exhausted", "429")):
                        friendly_error = "The Gemini API quota or rate limit was reached. Please try again later."
                    else:
                        friendly_error = (
                            "Gemini could not complete the request. Check your connection, API key, "
                            "and model availability, then try again."
                        )
                    st.error(friendly_error)
                    result = None

            if result is not None:
                answer = str(result["answer"])
                st.markdown(answer)
                if result["step_limit_reached"]:
                    st.warning("The agent stopped because it reached the step limit.")
                trace = result["trace"]
                with st.expander("Agent Steps", expanded=False):
                    if not trace:
                        st.caption("No tools were needed for this answer.")
                    for step_number, step in enumerate(trace, start=1):
                        st.markdown(f"**Step {step_number}: `{step['tool']}`**")
                        st.caption(f"Input: {step['input']}")
                        st.code(step["result"], language="text")
                st.session_state["chat_history"].append(
                    {
                        "role": "assistant",
                        "content": answer,
                        "trace": trace,
                        "step_limit_reached": result["step_limit_reached"],
                    }
                )
