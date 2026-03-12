"""
PitPixie – Content Understanding Module

Author: Vanessa Perera

Description:
This module integrates with Azure Content Understanding to analyse uploaded
documents and extract printed page numbers. The extracted values are used to
create a page map that helps reference the correct pages when generating AI
responses.
"""

import requests
import time
from load_secrets import get_secret
from azure.identity import DefaultAzureCredential

CU_ENDPOINT = get_secret("cu-endpoint")
CU_KEY = get_secret("cu-key")
CU_ANALYZER_ID = get_secret("cu-analyzer-id")
API_VERSION = "2025-05-01-preview"

def run_page_analyzer(blob_sas_url: str, CU_ENDPOINT: str, API_VERSION: str, CU_ANALYZER_ID: str) -> dict:
    """Runs content understanding page analyzer on a PDF"""

    url = (
        f"{CU_ENDPOINT}/"
        f"contentunderstanding/analyzers/"
        f"{CU_ANALYZER_ID}:analyze"
        f"?api-version={API_VERSION}"
    )

    print("[DEBUG] Sending URL to CU:", blob_sas_url)
    print("[DEBUG] Request URL:", url)

    try:
        credential = DefaultAzureCredential()
        token = credential.get_token("https://ai.azure.com/.default").token

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        payload = {
            "url": blob_sas_url
        }

        submit = requests.post(url, headers=headers, json=payload)

        print(f"[DEBUG] Submit response status: {submit.status_code}")

        if submit.status_code not in (200, 202):
            raise RuntimeError(f"Failed to submit analysis job: {submit.status_code} {submit.text}")
    
        if submit.status_code == 200:
            body = submit.json()
            return body.get("result", body)
    
        op_loc = submit.headers.get("Operation-Location") or submit.headers.get("operation-location")
    
        if not op_loc:
            raise RuntimeError(f"Missing Operation-Location header in response. Headers: {dict(submit.headers)}")
    
        while True:
            poll = requests.get(
                op_loc,
                headers={"Authorization": f"Bearer {token}"}
            )

            if poll.status_code != 200:
                raise RuntimeError(
                    f"Polling failed: {poll.status_code} {poll.text}"
                )
        
            result = poll.json()
            status = result.get("status")
            print(f"[DEBUG] Polling status: {status}")

            if status == "Succeeded":
                return result.get("result", result)
        
            if status in ("Failed", "Cancelled"):
                raise RuntimeError(result)
                   
            time.sleep(2)

    except Exception as e:
        print("[ERROR] CU analyzer failed", e)
        raise

    
def build_page_map(cu_result: dict, min_confidence: float = 0.3) -> dict:
    """Builds a page map from the content understanding response"""

    page_map = {}

    contents = cu_result.get("contents") or cu_result.get("result", {}).get("contents", [])
    
    if not isinstance(contents, list) or not contents:
        return page_map
    
    
    def get_any_value(field:dict):

        return(
            field.get("valueString") or
            field.get("value") or
            field.get("valueNumber") or
            field.get("valueInteger")
        )
    
    for chunk in contents:
        start = chunk.get("startPageNumber")
        end = chunk.get("endPageNumber")
        fields = chunk.get("fields") or {}

        ppn = fields.get("PrintedPageNumber")
        if not ppn:
            continue

        confidence = ppn.get("confidence") 

        if confidence is not None and confidence < min_confidence:
            continue

        value = get_any_value(ppn)
        if value is None:
            continue

        if isinstance(start, int) and isinstance(end, int):
            for pdf_page in range(start, end + 1):
                page_map[str(pdf_page)] = value

    return page_map


def debug_cu_printed_page_number(cu_result: dict, max_chunks: int = 5):
    contents = cu_result.get("contents") or cu_result.get("result",{}).get("contents", [])
    
    print(f"[DEBUG] CU contents count: {len(contents)}")

    for i, c in enumerate(contents[:max_chunks]):
        start = c.get("startPageNumber")
        end = c.get("endPageNumber")
        fields = c.get("fields") or {}
        
        print(f"[DEBUG] chunk[{i}] pages={start}-{end}, fieldKeys={list(fields.keys())}")

        ppn = fields.get("PrintedPageNumber")
        if ppn:
            print(f"[DEBUG] chunk[{i}] PrintedPageNumber raw: {ppn}")
        else:
            print(f"[DEBUG] chunk[{i}] PrintedPageNumber = MISSING")