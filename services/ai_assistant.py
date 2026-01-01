import os
import base64
import json
from datetime import datetime

# You need to add 'openai' to your requirements.txt
try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

def get_ai_client():
    """Securely gets the API key from the Server Environment"""
    api_key = os.environ.get('OPENAI_API_KEY')
    if not api_key or not OpenAI:
        return None
    return OpenAI(api_key=api_key)

def encode_image(image_path):
    """Converts image to format OpenAI can read"""
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

def scan_receipt(file_path):
    """
    Reads a receipt and extracts Cost, Date, and Vendor.
    """
    client = get_ai_client()
    if not client: return {"success": False, "error": "AI Not Configured"}

    try:
        base64_image = encode_image(file_path)
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a data extraction assistant. Output ONLY valid JSON."},
                {"role": "user", "content": [
                    {"type": "text", "text": "Extract these fields from this receipt image: 'total_cost' (number), 'date' (YYYY-MM-DD), 'vendor' (string). If unsure, return null."},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                ]}
            ],
            response_format={"type": "json_object"}
        )
        return {"success": True, "data": json.loads(response.choices[0].message.content)}
    except Exception as e:
        return {"success": False, "error": str(e)}

def verify_license(file_path, staff_name):
    """
    Checks if the Driving License belongs to the Staff Member.
    """
    client = get_ai_client()
    if not client: return {"success": True, "verified": True} # Skip check if no AI

    try:
        base64_image = encode_image(file_path)
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a compliance officer. Output ONLY valid JSON."},
                {"role": "user", "content": [
                    {"type": "text", "text": f"Look at this driving license. Does the name roughly match '{staff_name}'? Return JSON: 'match' (boolean) and 'reason' (short string)."},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                ]}
            ],
            response_format={"type": "json_object"}
        )
        result = json.loads(response.choices[0].message.content)
        return {"success": True, "verified": result.get('match', False), "reason": result.get('reason')}
    except:
        return {"success": False}