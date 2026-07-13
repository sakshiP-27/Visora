import logging
import os
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from models.uploadModels import (
    UploadReceiptRequest, 
    UploadReceiptResponse
)
from models.summaryModels import (
    SummaryRequest,
    GetAnalyticsResponse,
    GetInsightsResponse
)
from configs.serverConfig import ServerConfig
from services.processReceipt import ProcessReceipts
from services.computeAnalytics import ComputeAnalytics
from services.buildInsights import BuildInsights

logger = logging.getLogger("genai")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI()
config = ServerConfig()

SERVICE_SECRET = os.getenv("SERVICE_SECRET", "")


@app.middleware("http")
async def verify_service_secret(request: Request, call_next):
    # Allow health checks without auth
    if request.url.path == "/health":
        return await call_next(request)

    # If SERVICE_SECRET is configured, enforce it
    if SERVICE_SECRET:
        incoming_secret = request.headers.get("X-Service-Secret", "")
        if incoming_secret != SERVICE_SECRET:
            logger.warning("Rejected request — invalid or missing service secret | Path=%s", request.url.path)
            return JSONResponse(status_code=403, content={"error": "Forbidden"})

    return await call_next(request)

print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
print("Starting the GenAI Service")
print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")


@app.get("/health")
def read_health():
    return {"message": "GenAI Service running"}


@app.post(config.GENAI_UPLOAD_API, response_model=UploadReceiptResponse)
def process_uploaded_receipt(request: UploadReceiptRequest):
    logger.info("Receipt upload request received | Currency=%s", request.userContext.currency)
    try:
        cvHandler = ProcessReceipts(config.OCR_API_KEY, config.MODEL_ID, config.GEMINI_API_KEY, config.GROQ_API_KEY, config.GEMINI_MODEL, config.GROQ_MODEL)
        receiptData = cvHandler.convertImageToData(request.image, request.userContext.currency)
        logger.info("Receipt processed successfully | Merchant=%s ItemCount=%d",
                     receiptData.get("merchant", "unknown"), len(receiptData.get("items", [])))
        return receiptData
    except Exception as e:
        logger.error("Receipt processing failed | Error=%s", str(e))
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )


@app.post(config.GENAI_GENERATE_SUMMARY_API, response_model=GetInsightsResponse)
def generate_llm_summary(request: SummaryRequest):
    logger.info("Generate insights request received | User=%s", request.userID)
    try:
        insightsHandler = BuildInsights(config.GEMINI_API_KEY, config.GROQ_API_KEY, config.GEMINI_MODEL, config.GROQ_MODEL)
        insightsData = insightsHandler.generateInsights(request.model_dump())
        logger.info("Insights generated successfully | WarningCount=%d", len(insightsData.get("warnings", [])))
        return insightsData
    except Exception as e:
        logger.error("Generate insights failed | Error=%s", str(e))
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )


@app.post(config.GENAI_GET_ANALYTICS_API, response_model=GetAnalyticsResponse)
def get_user_analytics(request: SummaryRequest):
    logger.info("Get Analytics request received | User=%s", request.userID)
    try:
        analyticsHandler = ComputeAnalytics()
        analyticsData = analyticsHandler.computeAnalytics(request.model_dump())
        logger.debug("Analytics computed successfully | TotalSpent=%f CategoryWise=%d",
                        analyticsData.get("totalAmount"), len(analyticsData.get("categoryBreakdown", [])))
        return analyticsData
    except Exception as e:
        logger.error("Get analytics failed | Error=%s", str(e))
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )

