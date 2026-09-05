import os

def rewrite_sherlock():
    path = "backend/sherlock/agent.py"
    with open(path, "r") as f:
        code = f.read()
    
    code = code.replace("from google import genai\nfrom google.genai import types as genai_types", "from openai import OpenAI")
    code = code.replace("self._client = genai.Client(api_key=resolved_key)", "self._client = OpenAI(api_key=resolved_key, base_url='https://openrouter.ai/api/v1')")
    code = code.replace("model: str = DEFAULT_MODEL", "model: str = 'google/gemini-2.5-flash'")
    code = code.replace("DEFAULT_MODEL        = \"gemini-2.5-flash\"", "DEFAULT_MODEL        = \"google/gemini-2.5-flash\"")
    
    # Rewrite _call_llm
    call_llm_old = '''    def _call_llm(self, messages: list[dict[str, str]]) -> str:
        """
        Make one call directly against the Gemini API. Returns raw text.

        The system prompt is passed via system_instruction (Gemini's
        equivalent of an OpenAI-style role='system' message). Subsequent
        messages (user / assistant) carry the conversation history across
        retries so the model sees exactly what it returned previously —
        'assistant' maps to Gemini's 'model' role.
        """
        contents = [
            genai_types.Content(
                role="model" if m["role"] == "assistant" else "user",
                parts=[genai_types.Part(text=m["content"])],
            )
            for m in messages
        ]
        response = self._client.models.generate_content(
            model=self._model,
            contents=contents,
            config=genai_types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                temperature=self._temperature,
                max_output_tokens=DEFAULT_MAX_TOKENS,
            ),
        )
        raw = (response.text or "").strip()
        log.debug("LLM raw response: %s", raw[:300])
        return raw'''

    call_llm_new = '''    def _call_llm(self, messages: list[dict[str, str]]) -> str:
        api_messages = [{"role": "system", "content": SYSTEM_PROMPT}] + messages
        response = self._client.chat.completions.create(
            model=self._model,
            messages=api_messages,
            temperature=self._temperature,
            max_tokens=DEFAULT_MAX_TOKENS,
        )
        raw = (response.choices[0].message.content or "").strip()
        log.debug("LLM raw response: %s", raw[:300])
        return raw'''
    
    code = code.replace(call_llm_old, call_llm_new)
    
    with open(path, "w") as f:
        f.write(code)


def rewrite_athena():
    path = "backend/athena/agent.py"
    with open(path, "r") as f:
        code = f.read()
    
    code = code.replace("from google import genai\nfrom google.genai import types as genai_types", "from openai import OpenAI")
    code = code.replace("self._client = genai.Client(api_key=resolved_key)", "self._client = OpenAI(api_key=resolved_key, base_url='https://openrouter.ai/api/v1')")
    code = code.replace("model: str = DEFAULT_MODEL", "model: str = 'google/gemini-2.5-flash'")
    code = code.replace("DEFAULT_MODEL        = \"gemini-2.5-flash\"", "DEFAULT_MODEL        = \"google/gemini-2.5-flash\"")
    
    # Rewrite _call_llm
    call_llm_old = '''    def _call_llm(self, messages: list[dict[str, str]]) -> str:
        contents = [
            genai_types.Content(
                role="model" if m["role"] == "assistant" else "user",
                parts=[genai_types.Part(text=m["content"])],
            )
            for m in messages
        ]
        response = self._client.models.generate_content(
            model=self._model,
            contents=contents,
            config=genai_types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                temperature=self._temperature,
                max_output_tokens=DEFAULT_MAX_TOKENS,
            ),
        )
        raw = (response.text or "").strip()
        log.debug("ATHENA LLM raw response: %s", raw[:300])
        return raw'''

    call_llm_new = '''    def _call_llm(self, messages: list[dict[str, str]]) -> str:
        api_messages = [{"role": "system", "content": SYSTEM_PROMPT}] + messages
        response = self._client.chat.completions.create(
            model=self._model,
            messages=api_messages,
            temperature=self._temperature,
            max_tokens=DEFAULT_MAX_TOKENS,
        )
        raw = (response.choices[0].message.content or "").strip()
        log.debug("ATHENA LLM raw response: %s", raw[:300])
        return raw'''
    
    code = code.replace(call_llm_old, call_llm_new)
    
    with open(path, "w") as f:
        f.write(code)

rewrite_sherlock()
rewrite_athena()
