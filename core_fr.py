#!/usr/bin/env python3
"""
text2sql_core.py  – offline CodeGen + optional OpenAI refinement
"""

import os
import torch
import openai
from transformers import (
    AutoTokenizer,
    AutoModelForCausalLM,
    TextGenerationPipeline
)

# ---------------- 1. Offline generator ------------------ #
class SQLGenerator:
    def __init__(self, model_name="Salesforce/codegen-350M-multi"):
        device = 0 if torch.cuda.is_available() else -1
        self.tokenizer = AutoTokenizer.from_pretrained(model_name, use_auth_token=False)
        self.model = AutoModelForCausalLM.from_pretrained(model_name, use_auth_token=False).to(
            "cuda" if torch.cuda.is_available() else "cpu"
        )
        self.pipe = TextGenerationPipeline(
            model=self.model,
            tokenizer=self.tokenizer,
            device=device,
            max_new_tokens=256,
            do_sample=False,
            temperature=0.0,
        )

    def generate(self, request: str) -> str:
        prompt = f"""### SQL Generation
# Schema:
#   users(user_id INT, first_name VARCHAR, last_name VARCHAR, email VARCHAR, signup_date DATE)
#   orders(order_id INT, user_id INT, order_total FLOAT, order_date DATE)
#   products(product_id INT, name VARCHAR, price FLOAT)

# Examples:
# Input: Find total number of orders placed by each user.
# Output: SELECT u.first_name, u.last_name, COUNT(o.order_id) AS total_orders FROM users u JOIN orders o ON u.user_id = o.user_id GROUP BY u.user_id;

# Input: Create a table of employees with columns emp_id, emp_name, emp_address.
# Output: CREATE TABLE employees (emp_id INT, emp_name VARCHAR(255), emp_address VARCHAR(255));

# Now your request:
# Input: {request}
# Output:"""

        out = self.pipe(prompt)[0]["generated_text"]
        sql_part = out.split("# Output:")[-1] if "# Output:" in out else out
        lines = [l for l in sql_part.splitlines() if not l.strip().startswith("#")]
        return "\n".join(lines).strip()

# global offline generator
_generator = SQLGenerator()
# -------------------------------------------------------- #

# ------------- 2. Optional OpenAI refinement ------------ #
def _refine_with_openai(prompt: str, draft_sql: str) -> str:
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        return draft_sql                      

    from openai import OpenAI
    client = OpenAI(api_key=key)

    try:
        sys_msg = (
            "You are a senior database engineer. "
            "Return ONLY one valid SQL statement. No explanations."
        )
        user_msg = (
            f"User request: {prompt}\n"
            f"# Draft SQL (may be wrong):\n{draft_sql}\n"
            f"# Final SQL:"
        )
        resp = client.chat.completions.create(
            model="gpt-4o-mini",               # change to "gpt-4o" if you have access
            messages=[
                {"role": "system", "content": sys_msg},
                {"role": "user",   "content": user_msg}
            ],
            temperature=0.0
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        print("[OpenAI ERROR]", e)
        return draft_sql                       # fallback
# -------------------------------------------------------- #

# ------------- 3. Strip ``` fences if present ----------- #
def _strip_fence(text: str) -> str:
    """
    Remove leading/trailing ``` or ```sql code fences.
    """
    t = text.strip()
    if t.startswith("```"):
        lines = t.splitlines()
        # Drop first line (``` or ```sql)
        lines = lines[1:]
        # Drop last line if it's closing fence
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        t = "\n".join(lines).strip()
    return t
# -------------------------------------------------------- #

# 4. Public function
def text_to_sql(request: str) -> str:
    prompt  = request.strip()
    draft   = _generator.generate(prompt)
    refined = _refine_with_openai(prompt, draft)
    return _strip_fence(refined)

# 5. Simple CLI test
if __name__ == "__main__":
    print("=== Text→SQL CLI ===\n(leave blank to quit)\n")
    while True:
        q = input("Prompt> ").strip()
        if not q:
            break
        try:
            print("\n" + text_to_sql(q) + "\n")
        except Exception as e:
            print(f"[ERROR] {e}\n")
