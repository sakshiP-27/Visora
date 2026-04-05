import base64
import json
import logging
import time
import requests
from io import BytesIO
from google import genai
from groq import Groq
from PIL import Image
from mindee import (
    ClientV2,
    InferenceParameters,
    InferenceResponse,
    BytesInput,
)
from utils.categoriesList import categoriesList
from models.uploadModels import UploadReceiptResponse, ReceiptItem

logger = logging.getLogger("genai.cv")

# retry limits
MAX_RETRIES = 3

# module level toggle so it persists across requests
_llm_toggle = True


class ProcessReceipts:
    def __init__(self, ocrApiKey, modelId, geminiApiKey, groqApiKey, geminiModel, groqModel):
        # api keys
        self.ocrApiKey = ocrApiKey
        self.geminiApiKey = geminiApiKey
        self.groqApiKey = groqApiKey
        
        # model versions
        self.ocrModelId = modelId
        self.geminiModel = geminiModel
        self.groqModel = groqModel

        # initialising clients
        self.ocrClient = ClientV2(self.ocrApiKey)
        self.geminiClient = genai.Client(api_key=self.geminiApiKey)
        self.groqClient = Groq(api_key=self.groqApiKey)

    def convertImageToData(self, image: str, currency: str) -> dict:
        # Decode the base64 image
        imageBytes = base64.b64decode(image)
        try:
            pilImage = Image.open(BytesIO(imageBytes))
            extension = (pilImage.format or "jpg").lower()
        except Exception:
            raise RuntimeError("Unsupported image format. Please upload a JPEG or PNG image.")

        logger.info("Image decoded | Format=%s SizeBytes=%d", extension, len(imageBytes))

        # Set up Mindee OCR params
        params = InferenceParameters(
            model_id=self.ocrModelId,
            rag=None,
            raw_text=None,
            polygon=None,
            confidence=True
        )

        inputSource = BytesInput(imageBytes, filename=f"receipt.{extension}")

        # Call Mindee OCR with retry logic
        result = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                logger.info("Calling Mindee OCR | Attempt=%d/%d", attempt, MAX_RETRIES)
                result = self.ocrClient.enqueue_and_get_result(
                    InferenceResponse,
                    inputSource,
                    params
                )
                break
            except Exception as e:
                logger.error("Mindee OCR attempt %d failed | Error=%s", attempt, str(e))
                if attempt == MAX_RETRIES:
                    raise RuntimeError(f"Mindee OCR failed after {MAX_RETRIES} attempts: {e}")
                time.sleep(2 * attempt)


        # Extract fields
        fields = result.inference.result.fields
        merchantName = fields.get("supplier_name").value
        date = fields.get("date").value
        totalAmount = fields.get("total_amount").value
        currencyCode = fields["locale"].fields["currency"].value

        # Fallback: use today's date if OCR couldn't extract one
        if not date:
            from datetime import date as dt_date
            date = str(dt_date.today())
            logger.info("Date not found in receipt, using today's date | Date=%s", date)

        # Fallback: use the user's selected currency if OCR couldn't detect one
        if not currencyCode:
            currencyCode = currency
            logger.info("Currency not found in receipt, using user currency | Currency=%s", currencyCode)

        logger.info("OCR extraction complete | Merchant=%s Date=%s Total=%s Currency=%s",
                     merchantName, date, totalAmount, currencyCode)

        # Calculate confidence score
        confidenceMap = {"Certain": 1.0, "High": 0.85, "Medium": 0.6, "Low": 0.3}
        keyFields = ["supplier_name", "date", "total_amount"]
        confidenceValues = []
        for key in keyFields:
            field = fields.get(key)
            if field and field.confidence:
                confidenceValues.append(confidenceMap.get(str(field.confidence), 0.0))
        confidenceScore = sum(confidenceValues) / len(confidenceValues) if confidenceValues else 0.0

        logger.info("Confidence score calculated | Score=%.2f", confidenceScore)

        # Extract line items
        items = fields.get("line_items").items
        itemsList: list = []

        for item in items:
            itemFields = item.fields
            itemName = itemFields["description"].value
            itemQuantity = itemFields["quantity"].value
            itemPrice = itemFields["total_price"].value

            itemObject: dict = {
                "name": itemName,
                "price": itemPrice,
                "quantity": itemQuantity if itemQuantity is not None else 1
            }
            itemsList.append(itemObject)

        logger.info("Line items extracted | Count=%d", len(itemsList))

        # Categorize items via LLM
        itemsList: ReceiptItem = self.addCategoriesToList(itemsList)

        responseData: UploadReceiptResponse = {
            "merchant": merchantName,
            "date": date,
            "totalAmount": totalAmount,
            "currency": currencyCode,
            "items": itemsList,
            "confidenceScore": confidenceScore
        }
        return responseData

    def addCategoriesToList(self, itemsList: list) -> list:
        categories = ", ".join(categoriesList)
        itemSummaries = [{"name": item["name"], "price": item["price"]} for item in itemsList]

        prompt = (
            f"You are a categorization assistant. Given a list of items with their prices, assign each item a category "
            f"from ONLY this list: [{categories}].\n\n"
            f"Items: {json.dumps(itemSummaries)}\n\n"
            f"IMPORTANT: If an item has a negative price or its name suggests a discount, cashback, "
            f"club card savings, loyalty reward, or any kind of price reduction, assign it the category "
            f"\"Discounts & Cashback\". These often appear as negative amounts on receipts.\n\n"
            f"Respond with a JSON array of objects with 'name' and 'category' fields. "
            f"No explanation, just the JSON array."
        )

        global _llm_toggle

        if _llm_toggle:
            primary, fallback = self._call_gemini, self._call_groq
            primaryName, fallbackName = "Gemini", "Groq"
        else:
            primary, fallback = self._call_groq, self._call_gemini
            primaryName, fallbackName = "Groq", "Gemini"
        _llm_toggle = not _llm_toggle

        logger.info("Categorizing %d items | Primary=%s Fallback=%s", len(itemSummaries), primaryName, fallbackName)

        result = primary(prompt)
        if not result:
            logger.warn("Primary LLM (%s) failed, trying fallback (%s)", primaryName, fallbackName)
            result = fallback(prompt)

        if result:
            try:
                # strip markdown code fences if present (e.g. ```json ... ```)
                cleaned = result.strip()
                if cleaned.startswith("```"):
                    cleaned = cleaned.split("\n", 1)[1]  
                    cleaned = cleaned.rsplit("```", 1)[0]
                    cleaned = cleaned.strip()

                parsed = json.loads(cleaned)
                category_map = {entry["name"]: entry["category"] for entry in parsed}
                for item in itemsList:
                    item["category"] = category_map.get(item["name"], "Miscellaneous")
                logger.info("LLM categorization successful | CategoriesAssigned=%d", len(category_map))
            except (json.JSONDecodeError, KeyError) as e:
                logger.error("Failed to parse LLM response | Error=%s", str(e))
                for item in itemsList:
                    item["category"] = "Miscellaneous"
        else:
            logger.error("Both LLM providers failed, defaulting all items to Miscellaneous")
            for item in itemsList:
                item["category"] = "Miscellaneous"

        return itemsList

    def _call_gemini(self, prompt: str) -> str | None:
        try:
            logger.info("Calling Gemini API")
            for attempt in range(1, MAX_RETRIES + 1):
                response = self.geminiClient.models.generate_content(
                    model=self.geminiModel,
                    contents=prompt
                )
                if response and response.text:
                    logger.info("Gemini API responded successfully | Attempt=%d", attempt)
                    return response.text.strip()
                logger.warning("Gemini returned empty response | Attempt=%d/%d", attempt, MAX_RETRIES)
                if attempt < MAX_RETRIES:
                    time.sleep(2 * attempt)
            return None
        except Exception as e:
            logger.error("Gemini API call failed | Error=%s", str(e))
            return None

    def _call_groq(self, prompt: str) -> str | None:
        try:
            logger.info("Calling Groq API")
            for attempt in range(1, MAX_RETRIES + 1):
                response = self.groqClient.chat.completions.create(
                    model=self.groqModel,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=1024
                )
                if response and response.choices[0].message.content:
                    logger.info("Groq API responded successfully | Attempt=%d", attempt)
                    return response.choices[0].message.content.strip()
                logger.warning("Groq returned empty response | Attempt=%d/%d", attempt, MAX_RETRIES)
                if attempt < MAX_RETRIES:
                    time.sleep(2 * attempt)
            return None
        except Exception as e:
            logger.error("Groq API call failed | Error=%s", str(e))
            return None
