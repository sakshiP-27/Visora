from fastapi import FastAPI
import json

from cv.processReceipt import ProcessReceipts

app = FastAPI()
print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
print("Starting GenAI Service")
print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

@app.get("/health")
def read_health():
    return {"message": "GenAI Service running"}

@app.post("/uploadreceipt")
def process_uploaded_receipt(request):
    # convert the request json in python dictionary
    requestData: dict = json.loads(request)

    # initalising the CV Service handler
    cvHandler = ProcessReceipts()
    receiptData: dict = cvHandler.convertImageToData(requestData)

@app.get("/generatesummary")
def generate_llm_summary():
    pass

@app.get("/getanalytics")
def get_user_analytics():
    pass