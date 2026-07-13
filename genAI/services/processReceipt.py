import base64
import json
import logging
import time
from google import genai
from google.genai import types
from groq import Groq
from utils.categoriesList import categoriesList
from models.uploadModels import UploadReceiptResponse, ReceiptItem

logger = logging.getLogger("genai.cv")

# retry limits
MAX_RETRIES = 3

# module level toggle so it persists across requests
_llm_toggle = True

# The structured prompt for receipt extraction via Gemini Vision
RECEIPT_EXTRACTION_PROMPT = """You are a receipt OCR and data extraction assistant. Analyze the provided receipt image and extract the following information in JSON format.

IMPORTANT RULES:
1. Extract ALL line items from the receipt, including discounts (which appear as negative amounts).
2. If you cannot read the date, return null for the date field.
3. If you cannot determine the currency from the receipt, use "{currency}" as the currency code.
4. For quantity, default to 1 if not explicitly shown on the receipt.
5. The totalAmount should be the final total paid (after discounts/tax).
6. Return ONLY valid JSON, no explanation or markdown formatting.

Respond with this exact JSON structure:
{{
    "merchant": "Store/merchant name",
    "date": "YYYY-MM-DD or null if unreadable",
    "totalAmount": 0.00,
    "currency": "3-letter currency code (e.g., USD, EUR, INR, GBP)",
    "items": [
        {{
            "name": "Item description",
            "price": 0.00,
            "quantity": 1
        }}
    ],
    "confidenceScore": 0.85
}}

For confidenceScore, rate your own extraction confidence:
- 0.9-1.0: Receipt is clearly legible, all fields extracted with certainty
- 0.7-0.9: Most fields clear, some minor uncertainty
- 0.5-0.7: Partially legible, some guessing involved
- Below 0.5: Poor quality, significant guessing

Now extract the data from this receipt image:"""


class ProcessReceipts:
    def __init__(self, ocrApiKey, modelId, geminiApiKey, groqApiKey, geminiModel, groqModel):
        # api keys
        self.geminiApiKey = geminiApiKey
        self.groqApiKey = groqApiKey

        # model versions
        self.geminiModel = geminiModel
        self.groqModel = groqModel

        # initialising clients
        self.geminiClient = genai.Client(api_key=self.geminiApiKey)
        self.groqClient = Groq(api_key=self.groqApiKey)

    def convertImageToData(self, image: str, currency: str) -> dict:
        # Decode the base64 image to determine format
        imageBytes = base64.b64decode(image)

        # Detect image MIME type from magic bytes
        mimeType = self._detect_mime_type(imageBytes)
        if not mimeType:
            raise RuntimeError("Unsupported image format. Please upload a JPEG or PNG image.")

        logger.info("Image decoded | MimeType=%s SizeBytes=%d", mimeType, len(imageBytes))

        # Extract receipt data using Gemini Vision
        extractedData = self._extract_receipt_with_gemini(imageBytes, mimeType, currency)

        if not extractedData:
            raise RuntimeError("Failed to extract receipt data. Please try again with a clearer image.")

        logger.info("Receipt extraction complete | Merchant=%s Date=%s Total=%s Currency=%s",
                    extractedData.get("merchant"), extractedData.get("date"),
                    extractedData.get("totalAmount"), extractedData.get("currency"))

        # Fallback: use today's date if extraction couldn't find one
        if not extractedData.get("date"):
            from datetime import date as dt_date
            extractedData["date"] = str(dt_date.today())
            logger.info("Date not found in receipt, using today's date | Date=%s", extractedData["date"])

        # Fallback: use user's selected currency if not detected
        if not extractedData.get("currency"):
            extractedData["currency"] = currency
            logger.info("Currency not found in receipt, using user currency | Currency=%s", currency)

        # Extract items list and categorize
        itemsList = extractedData.get("items", [])

        # Ensure all items have quantity defaulted to 1
        for item in itemsList:
            if item.get("quantity") is None:
                item["quantity"] = 1

        logger.info("Line items extracted | Count=%d", len(itemsList))

        # Categorize items via LLM
        itemsList = self.addCategoriesToList(itemsList)

        responseData: UploadReceiptResponse = {
            "merchant": extractedData.get("merchant", "Unknown"),
            "date": extractedData.get("date"),
            "totalAmount": extractedData.get("totalAmount", 0.0),
            "currency": extractedData.get("currency", currency),
            "items": itemsList,
            "confidenceScore": extractedData.get("confidenceScore", 0.7)
        }
        return responseData

    def _detect_mime_type(self, imageBytes: bytes) -> str | None:
        """Detect MIME type from image magic bytes."""
        if imageBytes[:8] == b'\x89PNG\r\n\x1a\n':
            return "image/png"
        elif imageBytes[:2] == b'\xff\xd8':
            return "image/jpeg"
        elif imageBytes[:4] == b'RIFF' and imageBytes[8:12] == b'WEBP':
            return "image/webp"
        return None

    def _extract_receipt_with_gemini(self, imageBytes: bytes, mimeType: str, currency: str) -> dict | None:
        """Use Gemini Vision to extract structured data from a receipt image."""
        prompt = RECEIPT_EXTRACTION_PROMPT.format(currency=currency)

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                logger.info("Calling Gemini Vision for receipt extraction | Attempt=%d/%d", attempt, MAX_RETRIES)

                response = self.geminiClient.models.generate_content(
                    model=self.geminiModel,
                    contents=[
                        types.Content(
                            parts=[
                                types.Part.from_bytes(data=imageBytes, mime_type=mimeType),
                                types.Part.from_text(text=prompt),
                            ]
                        )
                    ]
                )

                if response and response.text:
                    # Parse the JSON response
                    cleaned = response.text.strip()

                    # Strip markdown code fences if present
                    if cleaned.startswith("```"):
                        cleaned = cleaned.split("\n", 1)[1]
                        cleaned = cleaned.rsplit("```", 1)[0]
                        cleaned = cleaned.strip()

                    parsed = json.loads(cleaned)
                    logger.info("Gemini Vision extraction successful | Attempt=%d", attempt)
                    return parsed

                logger.warning("Gemini Vision returned empty response | Attempt=%d/%d", attempt, MAX_RETRIES)

            except json.JSONDecodeError as e:
                logger.error("Failed to parse Gemini Vision response as JSON | Attempt=%d Error=%s", attempt, str(e))
            except Exception as e:
                logger.error("Gemini Vision call failed | Attempt=%d Error=%s", attempt, str(e))

            if attempt < MAX_RETRIES:
                time.sleep(2 * attempt)

        return None

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
                # strip markdown code fences if present
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
